"""
Core processing logic for the Manga Manager.
"""
import logging
import re
import threading
import unicodedata
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass

from modules.config import AppConfig
from modules.komga_client import KomgaClient
from modules.providers import ConfiguredProvider, ProviderChain, get_providers
from modules.providers.base import MetadataProvider, MetadataProviderError
from modules.translators import get_translator, Translator
from modules.models import KomgaSeries, MetadataCandidate, MetadataRecord, KomgaBook
from modules.utils import clean_description
from modules.utils import log_frame
from thefuzz import fuzz

logger = logging.getLogger(__name__)
PROVIDER_LABELS = {
    "anilist": "AniList",
    "mangadex": "MangaDex",
    "mangaupdates": "MangaUpdates",
}


@dataclass
class ProcessingResult:
    """Outcome of a complete library processing run."""
    success: bool = True
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    translator: Optional[Translator] = None


@dataclass
class WatcherPollResult:
    """Outcome of one watcher polling cycle."""
    found: int = 0
    processed: int = 0
    failed: int = 0

    def __bool__(self) -> bool:
        return self.found > 0

# Field processing configurations - centralized to avoid repetition
FIELD_CONFIGS = {
    'summary': {
        'update': {
            'get_value': lambda best_match, translator, config: (
                clean_description(best_match.description) if best_match.description else None,
                lambda val: translator.translate(
                    val,
                    config.translation.target_language,
                    source_language=best_match.description_language,
                ) if val and translator and config.translation else val
            ),
            'default_remove': "",
            'compare_func': lambda new_val, current_val, config: (
                None if not config.processing.overwrite_existing and new_val == current_val else True
            )
        },
        'remove': {'default_value': ""}
    },
    'publisher': {
        'update': {
            'get_value': lambda best_match, translator, config: (
                best_match.publisher,
                None,
            ),
            'compare_func': lambda new_val, current_val, config: (
                None if not config.processing.overwrite_existing and new_val == current_val else True
            ),
        },
        'remove': {'default_value': ""},
    },
    'language': {
        'remove': {'default_value': ""},
    },
    'reading_direction': {
        'remove': {
            'default_value': None,
            'payload_key': 'readingDirection',
            'lock_key': 'readingDirectionLock',
            'label': 'Reading Direction',
        },
    },
    'genres': {
        'update': {
            'get_value': lambda best_match, translator, config: (
                sorted(list(set(
                    translator.translate(
                        g,
                        config.translation.target_language,
                        source_language=best_match.genre_languages.get(g),
                    ) for g in best_match.genres
                ))) if best_match.genres and translator and config.translation
                else sorted(list(set(best_match.genres))) if best_match.genres else None,
                None
            ),
            'compare_func': lambda new_val, current_val, config: (
                None if not config.processing.overwrite_existing and set(new_val or []) == set(current_val or []) else True
            )
        },
        'remove': {'default_value': []}
    },
    'status': {
        'update': {
            'get_value': lambda best_match, translator, config: (
                best_match.status,
                None
            ),
            'compare_func': lambda new_val, current_val, config: (
                None if not new_val or (not config.processing.overwrite_existing and new_val == current_val) else True
            )
        },
        'remove': {'default_value': None}
    },
    'tags': {
        'update': {
            'custom_handler': lambda payload, series, best_match, config, translator, komga_client: _process_tags_update(payload, series, best_match, config)
        },
        'remove': {
            'custom_handler': lambda payload, series, best_match, config, translator, komga_client: _process_tags_remove(payload, series, best_match, config)
        }
    },
    'links': {
        'update': {
            'custom_handler': lambda payload, series, best_match, config, translator, komga_client: _process_links_update(payload, series, best_match, config)
        },
        'remove': {
            'custom_handler': lambda payload, series, best_match, config, translator, komga_client: _process_links_remove(payload, series, best_match, config)
        }
    }
}

def _process_tags_update(payload, series, best_match, config):
    """Custom handler for tags update."""
    metadata = series.metadata
    new_tags = set(metadata.tags or [])
    changes = []

    if config.processing.update_fields.tags.score and best_match and best_match.score is not None and best_match.score > 0:
        score_tag = f"Score: {best_match.score / 10:.1f}"
        new_tags = {tag for tag in new_tags if "score:" not in tag.lower()}
        new_tags.add(score_tag)
        changes.append(f"added score tag '{score_tag}'")

    new_tags_list = sorted(list(new_tags))
    current_tags_set = set(metadata.tags or [])

    if current_tags_set == set(new_tags_list):
        return None

    payload['tags'] = new_tags_list
    if getattr(metadata, 'tags_lock') and config.processing.force_unlock:
        payload['tagsLock'] = False
    return f"- Tags: {', '.join(changes)}" if changes else None

def _process_tags_remove(payload, series, best_match, config):
    """Custom handler for tags remove."""
    metadata = series.metadata

    if config.processing.remove_fields.tags.score:
        new_tags = set(metadata.tags or [])
        original_count = len(new_tags)
        new_tags = {tag for tag in new_tags if "score:" not in tag.lower()}

        if len(new_tags) < original_count:
            new_tags_list = sorted(list(new_tags))
            payload['tags'] = new_tags_list
            if getattr(metadata, 'tags_lock') and config.processing.force_unlock:
                payload['tagsLock'] = False
            return "- Tags: removed score tag."
        else:
            return None
    return None


def _provider_links(record: MetadataRecord) -> Dict[str, str]:
    """Return every normalized provider link, including legacy site_url records."""
    links = dict(record.provider_links)
    if record.site_url:
        links.setdefault(record.source_provider("site_url"), record.site_url)
    return links


def _process_links_update(payload, series, best_match, config):
    """Custom handler for links update."""
    metadata = series.metadata
    provider_links = _provider_links(best_match) if best_match else {}

    if config.processing.update_fields.link and provider_links:
        current_links = list(getattr(metadata, 'links', []))
        labels_by_provider = {
            provider_name: PROVIDER_LABELS.get(provider_name, provider_name.capitalize())
            for provider_name in provider_links
        }
        replaced_labels = {label.casefold() for label in labels_by_provider.values()}

        new_links = [
            link for link in current_links
            if link.get('label', '').strip().casefold() not in replaced_labels
        ]
        new_links.extend(
            {"label": labels_by_provider[provider_name], "url": url}
            for provider_name, url in provider_links.items()
        )

        if new_links == current_links:
            return None

        payload['links'] = new_links
        if hasattr(metadata, 'links_lock') and getattr(metadata, 'links_lock') and config.processing.force_unlock:
            payload['linksLock'] = False
        return f"- Links: synchronized {', '.join(labels_by_provider.values())}"
    return None

def _process_links_remove(payload, series, best_match, config):
    """Custom handler for links remove."""
    metadata = series.metadata

    if config.processing.remove_fields.link:
        current_links = list(getattr(metadata, 'links', []))
        provider_labels = {label.casefold() for label in PROVIDER_LABELS.values()}
        new_links = [
            link for link in current_links
            if link.get('label', '').strip().casefold() not in provider_labels
        ]
        removed_count = len(current_links) - len(new_links)

        if removed_count:
            payload['links'] = new_links
            if hasattr(metadata, 'links_lock') and getattr(metadata, 'links_lock') and config.processing.force_unlock:
                payload['linksLock'] = False
            return f"- Links: removed {removed_count} provider link(s)."
        else:
            return None
    return None

@dataclass
class GenericFieldHandler:
    """Generic field handler that uses configuration mapping."""
    field_name: str
    operation: str
    config_attr: str

    def process(self, payload: Dict, series: KomgaSeries, best_match: Optional[MetadataRecord], config: AppConfig, translator: Optional[Translator], komga_client: Optional[KomgaClient] = None) -> Optional[str]:
        """Process this field using the configuration mapping."""
        metadata = series.metadata

        # Check if operation is enabled in config
        config_field = getattr(config.processing.update_fields if self.operation == 'update' else config.processing.remove_fields, self.config_attr, False)
        if not config_field:
            return None

        # For updates, we need a best_match
        if self.operation == 'update' and not best_match:
            return None

        # Check lock/force unlock logic
        current_value = getattr(metadata, self.field_name)
        is_locked = getattr(metadata, self.field_name + '_lock', False)

        if is_locked and not config.processing.force_unlock:
            return None

        # Collection handlers implement additive/idempotent semantics and must
        # run even when a collection already contains unrelated values.
        field_config = FIELD_CONFIGS.get(self.field_name, {}).get(self.operation)
        if field_config and 'custom_handler' in field_config:
            return field_config['custom_handler'](payload, series, best_match, config, translator, komga_client)

        if self.operation == 'update':
            should_process = should_update_field(current_value, is_locked, config)
        else:
            should_process = should_remove_field(current_value, is_locked, config)

        if not should_process:
            return None

        # Generic processing logic
        return self._process_generic_field(payload, series, best_match, config, translator, field_config)

    def _process_generic_field(self, payload, series, best_match, config, translator, field_config) -> Optional[str]:
        """Generic field processing using configuration."""
        metadata = series.metadata

        if self.operation == 'update':
            value_getter, transformer = field_config['get_value'](best_match, translator, config)
            new_value = transformer(value_getter) if transformer else value_getter

            if new_value is None:
                return None

            # Check if we should skip due to existing value
            if 'compare_func' in field_config:
                skip = field_config['compare_func'](new_value, getattr(metadata, self.field_name), config)
                if skip is None:  # Comparison indicated to skip
                    return None

        else:  # remove operation
            new_value = field_config['default_value']

        payload_key = field_config.get('payload_key', self.field_name)
        payload[payload_key] = new_value
        if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
            lock_key = field_config.get('lock_key', self.field_name + 'Lock')
            payload[lock_key] = False

        label = field_config.get('label', self.field_name.title())
        if self.operation == 'update':
            if self.field_name == "summary":
                return "- Summary: Will be updated."
            return f"- {label}: Set to {new_value}"
        else:
            return f"- {label}: Will be removed."



@dataclass
class CoverImageHandler:
    operation: str = "update"
    config_attr: str = "cover_image"

    def process(self, payload, series, best_match, config, translator, komga_client):
        if not config.processing.update_fields.cover_image or not best_match or not best_match.cover_urls:
            return None

        image_url = best_match.cover_urls[0]
        if not image_url:
            return None

        if not komga_client:
            return None

        status = komga_client.update_series_poster(
            series.id,
            image_url,
            overwrite_existing=config.processing.overwrite_existing,
            dry_run=config.system.dry_run,
        )
        if status == 'would_upload':
            return f"- Cover Image: Will be updated from {image_url}"
        if status == 'uploaded':
            return f"- Cover Image: Successfully updated from {image_url}"
        logger.debug("Cover image for '%s' was %s", series.name, status)
        return None

# Global field handlers - now using generic handler with configuration
FIELD_HANDLERS = [
    GenericFieldHandler("summary", "update", "summary"),
    GenericFieldHandler("summary", "remove", "summary"),
    GenericFieldHandler("publisher", "update", "publisher"),
    GenericFieldHandler("publisher", "remove", "publisher"),
    GenericFieldHandler("language", "remove", "language"),
    GenericFieldHandler("reading_direction", "remove", "reading_direction"),
    GenericFieldHandler("genres", "update", "genres"),
    GenericFieldHandler("genres", "remove", "genres"),
    GenericFieldHandler("tags", "update", "tags"),
    GenericFieldHandler("tags", "remove", "tags"),
    GenericFieldHandler("links", "update", "link"),
    GenericFieldHandler("links", "remove", "link"),
    GenericFieldHandler("status", "update", "status"),
    GenericFieldHandler("status", "remove", "status"),
]




def choose_best_match(
    series_title: str,
    candidates: List[MetadataCandidate],
    min_score: int = 80,
    allow_adult: bool = False,
) -> Optional[MetadataCandidate]:
    """
    Selects the best match from a list of candidates.
    It first filters candidates by a minimum fuzzy match score, then sorts by score,
    and finally by popularity as a tie-breaker.
    """
    if not candidates:
        return None

    normalized_series_title = _normalize_title(series_title)
    if not normalized_series_title:
        return None
    scored_candidates = []
    excluded_exact_matches = []
    for candidate in candidates:
        titles_to_check = candidate.titles

        if not titles_to_check:
            continue

        normalized_titles = [_normalize_title(title) for title in titles_to_check]
        is_exact_match = normalized_series_title in normalized_titles
        if candidate.adult and not allow_adult:
            if is_exact_match:
                excluded_exact_matches.append(candidate.display_title)
            continue

        # WRatio relies on partial matching and gives a misleading score of 90
        # when a short query is merely contained in a much longer title (for
        # example "Berserk" and "Boushoku no Berserk ..."). A plain ratio plus
        # token sorting still tolerates typos and reordered words without that
        # substring bias.
        score = 100 if is_exact_match else max(
            max(
                fuzz.ratio(normalized_series_title, title),
                fuzz.token_sort_ratio(normalized_series_title, title),
            )
            for title in normalized_titles
        )

        if score >= min_score:
            scored_candidates.append({'candidate': candidate, 'score': score})

    if excluded_exact_matches:
        logger.warning(
            "Excluded exact adult title match(es) %s because this provider's allow_adult is false; "
            "set it to true to allow this match. Fuzzy alternatives will not be used.",
            ", ".join(f"'{title}'" for title in excluded_exact_matches),
        )
        scored_candidates = [item for item in scored_candidates if item['score'] == 100]

    if not scored_candidates:
        return None

    # Sort by score (desc), then by popularity (desc) as a tie-breaker
    ranked = sorted(scored_candidates, key=lambda x: (x['score'], x['candidate'].popularity), reverse=True)
    best = ranked[0]
    
    logger.info(
        "Top candidates: %s",
        ", ".join(f"'{item['candidate'].display_title}'={item['score']}" for item in ranked[:3]),
    )
    logger.info(
        "Found %s candidates with score >= %s. Best match: '%s' with score %s.",
        len(scored_candidates), min_score, best['candidate'].display_title, best['score'],
    )
    
    return best['candidate']


def _normalize_title(title: str) -> str:
    """Normalize punctuation, Unicode and whitespace before fuzzy matching."""
    normalized = unicodedata.normalize('NFKC', title).casefold()
    normalized = re.sub(r'[^\w\s]', ' ', normalized, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', normalized).strip()

def should_update_field(current_value, is_locked: bool, config: AppConfig) -> bool:
    """Helper function to determine if a metadata field should be updated."""
    if is_locked and not config.processing.force_unlock:
        return False
    if config.processing.overwrite_existing:
        return True
    return not current_value

def process_libraries(
    config: AppConfig,
    stop_event: Optional[threading.Event] = None,
) -> ProcessingResult:
    """
    Main processing function that iterates through libraries and series.
    Returns a structured outcome suitable for CLI exit codes and scheduling.
    """
    cache_dir = Path("/config/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    result = ProcessingResult()

    komga_client = KomgaClient(config.komga)
    metadata_provider = get_providers(config.providers, cache_dir)
    if not metadata_provider:
        logger.error("Failed to initialize metadata providers. Aborting.")
        result.success = False
        return result

    translator: Optional[Translator] = None
    if config.translation and config.translation.enabled:
        translator_provider = config.translation.provider.lower()
        translator_kwargs = {}
        if translator_provider == 'deepl':
            if config.translation.deepl:
                translator_kwargs['config'] = config.translation.deepl
            else:
                logger.error("DeepL provider is selected but its configuration is missing.")
                result.success = False
                return result
        
        translator = get_translator(translator_provider, **translator_kwargs)

        if translator:
            logger.info(f"Translation enabled to target language: '{config.translation.target_language}'")
        else:
            logger.error("Failed to initialize translator. Translation will be disabled.")
            result.success = False
            return result

    result.translator = translator

    all_libraries = komga_client.get_libraries()
    if not all_libraries:
        logger.error("No libraries were returned by Komga. Aborting.")
        result.success = False
        return result

    target_libraries = {lib.name: lib.id for lib in all_libraries if lib.name in config.komga.libraries}
    if not target_libraries:
        logger.warning("No matching libraries found on Komga server based on your config. Exiting.")
        result.success = False
        return result

    logger.info(f"Found {len(target_libraries)} target library/libraries to process: {list(target_libraries.keys())}")

    for lib_name, lib_id in target_libraries.items():
        if stop_event and stop_event.is_set():
            logger.info("Processing interrupted before the next library.")
            break
        logging.info("|                                                                                                    |")
        logging.info("|====================================================================================================|")
        log_frame(f"Processing Library: {lib_name}", 'center')
        logging.info("|====================================================================================================|")
        #logger.info(f"---  '{lib_name}' (ID: {lib_id}) ---")
        series_list = komga_client.get_series_in_library(lib_id, lib_name)

        if not series_list:
            logger.info("No series found in this library.")
            continue

        for series in series_list:
            if stop_event and stop_event.is_set():
                logger.info("Processing interrupted before the next series.")
                break
            if series.name in config.processing.exclude_series:
                logger.info(f"Skipping series '{series.name}', excluded.")
                result.skipped += 1
                continue

            try:
                process_single_series(series, config, komga_client, metadata_provider, translator)
                result.processed += 1
            except Exception as e:
                result.failed += 1
                result.success = False
                logger.error(
                    f"Error processing series '{series.name}': {e} - skipping to next series",
                    exc_info=config.system.debug,
                )
                continue

    if metadata_provider:
        metadata_provider.save_cache()
        metadata_provider.log_cache_summary()

    if translator and hasattr(translator, 'log_cache_summary'):
        translator.log_cache_summary()

    return result

def watch_for_new_series(
    config: AppConfig,
    komga_client: KomgaClient,
    target_libraries: dict,
    known_series: dict,
    metadata_provider,
    translator,
) -> WatcherPollResult:
    """
    Poll for new series in libraries and process only the new ones.
    Updates known_series in place.

    Args:
        config: App config
        komga_client: Komga client instance
        target_libraries: Dict of lib_name -> lib_id
        known_series: Dict of lib_id -> set(series_ids)
        metadata_provider: Pre-initialized metadata provider
        translator: Pre-initialized translator (can be None)
    """
    result = WatcherPollResult()
    komga_logger = logging.getLogger('modules.komga_client')
    original_level = komga_logger.level

    for lib_name, lib_id in target_libraries.items():
        # Silence komga_client logs during polling to reduce noise
        komga_logger.setLevel(logging.WARNING)
        try:
            current_series = komga_client.get_series_in_library(lib_id, lib_name)
        finally:
            komga_logger.setLevel(original_level)

        new_series = [s for s in current_series if s.id not in known_series[lib_id]]
        if new_series:
            result.found += len(new_series)
            logging.info("|                                                                                                    |")
            logging.info("|====================================================================================================|")
            log_frame("Watcher", 'center')
            logging.info("|====================================================================================================|")
            logger.info(f"Watcher: Found {len(new_series)} new series in library '{lib_name}'")
            for series in new_series:
                if series.name in config.processing.exclude_series:
                    logger.info(f"Watcher: Skipping excluded series '{series.name}'")
                    known_series[lib_id].add(series.id)
                    continue
                logger.info(f"Watcher: Processing new series '{series.name}'")
                try:
                    process_single_series(series, config, komga_client, metadata_provider, translator)
                except Exception as e:
                    result.failed += 1
                    logger.error(f"Watcher: Failed to process '{series.name}': {e}", exc_info=config.system.debug)
                else:
                    result.processed += 1
                    known_series[lib_id].add(series.id)
        else:
            logger.debug(f"Watcher: No new series in library '{lib_name}'")

    if result.found:
        # Save caches after processing
        metadata_provider.save_cache()
        if translator and hasattr(translator, 'save_cache_to_disk'):
            translator.save_cache_to_disk()

    return result



def _remove_authors(books: List[KomgaBook], config: AppConfig, dry_run_changes: List[str], komga_client: KomgaClient, series_name: str) -> Optional[str]:
    """
    Remove authors from all books in the series if requested in config.

    Args:
        books: List of books in the series
        config: Application configuration
        dry_run_changes: List to collect change descriptions for dry run
        komga_client: Komga client instance

    Returns:
        Summary message if authors were processed, None otherwise
    """
    remove_writers = config.processing.remove_fields.authors.writers
    remove_pencillers = config.processing.remove_fields.authors.pencillers

    if not remove_writers and not remove_pencillers:
        return None

    logger.info(f"Processing authors removal for '{series_name}' ({len(books)} books)")
    logger.debug(f"_remove_authors for '{series_name}': remove_writers={remove_writers}, remove_pencillers={remove_pencillers}")
    books_to_process = 0
    roles_found = set()
    books_with_writers_removed = 0
    books_with_pencillers_removed = 0
    for book in books:
        try:
            metadata = book.metadata
            logger.debug(f"Book '{book.name}' authors: {metadata.authors}, locked: {metadata.authors_lock}")
            if should_remove_field(metadata.authors, metadata.authors_lock, config):
                logger.debug(f"Book '{book.name}' should process removal")
                # Filter out the authors to remove
                filtered_authors = []
                for author in metadata.authors:
                    role = author.get('role', '').lower() if isinstance(author, dict) else ''
                    roles_found.add(role)
                    logger.debug(f"Book '{book.name}' author: {author}, extracted role: '{role}'")
                    keep = True
                    if remove_writers and role == 'writer':
                        logger.debug(f"  Removing writer: {author}")
                        keep = False
                        books_with_writers_removed += 1
                    elif remove_pencillers and role == 'penciller':
                        logger.debug(f"  Removing penciller: {author}")
                        keep = False
                        books_with_pencillers_removed += 1
                    else:
                        logger.debug(f"  Keeping author: {author}")
                    if keep:
                        filtered_authors.append(author)

                if len(filtered_authors) != len(metadata.authors):
                    logger.debug(f"Book '{book.name}' authors filtered from {len(metadata.authors)} to {len(filtered_authors)}")
                    books_to_process += 1
                    if config.system.dry_run:
                        dry_run_changes.append(f"- Book '{book.name}' Authors: Will be updated to remove writers/pencillers.")
                    else:
                        payload = {'authors': filtered_authors}
                        if metadata.authors_lock and config.processing.force_unlock:
                            payload['authorsLock'] = False

                        success = komga_client.update_book_metadata(book.id, payload)
                        if success:
                            logger.debug(f"Successfully updated authors for book '{book.name}': removed writers/pencillers")
                        else:
                            logger.error(f"Failed to update authors for book '{book.name}'")
                else:
                    logger.debug(f"Book '{book.name}' no authors to filter")
        except Exception as e:
            logger.error(f"Error processing book '{book.name}' in series '{series_name}': {e} - skipping")
            continue

    logger.info(f"Author roles found in '{series_name}': {sorted([r for r in roles_found if r])}")
    if books_with_writers_removed > 0 or books_with_pencillers_removed > 0:
        summary_parts = []
        if books_with_writers_removed > 0:
            summary_parts.append(f"writers from {books_with_writers_removed} books")
        if books_with_pencillers_removed > 0:
            summary_parts.append(f"pencillers from {books_with_pencillers_removed} books")
        summary_text = f"Removed authors from '{series_name}': {', '.join(summary_parts)}"
        logger.info(summary_text)
        return f"- Authors (remove): Removed {', '.join(summary_parts)}" if config.system.dry_run else f"- Authors (remove): Removed {', '.join(summary_parts)}"
    else:
        types = []
        if remove_writers:
            types.append("writers")
        if remove_pencillers:
            types.append("pencillers")
        type_str = ', '.join(types) if types else "authors"
        return f"- Authors (remove {type_str}): No changes needed."

def _remove_cover_image(series: KomgaSeries, config: AppConfig, komga_client: KomgaClient) -> Optional[str]:
    if not config.processing.remove_fields.cover_image:
        return None

    removed_count = komga_client.remove_uploaded_series_posters(
        series.id,
        dry_run=config.system.dry_run,
    )
    if removed_count == 0:
        return None
    action = "Will remove" if config.system.dry_run else "Removed"
    return f"- Cover Image: {action} {removed_count} user-uploaded thumbnail(s)."

def _update_authors(books: List[KomgaBook], best_match: MetadataRecord, config: AppConfig, dry_run_changes: List[str], komga_client: KomgaClient) -> Optional[str]:
    """
    Update authors for all books in the series from normalized provider data.

    Args:
        books: List of books in the series
        best_match: normalized provider record with creator information
        config: Application configuration
        dry_run_changes: List to collect change descriptions for dry run
        komga_client: Komga client instance

    Returns:
        Summary message if authors were processed, None otherwise
    """
    logger.debug(f"_update_authors: Starting author update processing for {len(books)} books")
    creators_provider = best_match.source_provider("creators")
    logger.debug(
        "_update_authors: creators from %s; primary media ID: %s, title: %s",
        creators_provider, best_match.external_id, best_match.display_title,
    )
    logger.debug(f"_update_authors: config.processing.update_fields.authors = {config.processing.update_fields.authors}")

    writers_enabled = config.processing.update_fields.authors.writers
    pencillers_enabled = config.processing.update_fields.authors.pencillers

    if not writers_enabled and not pencillers_enabled:
        logger.debug("_update_authors: Authors updates disabled in config")
        return None

    if not best_match.creators:
        return f"- Authors: No creators found on {creators_provider}."

    writers = [creator.name for creator in best_match.creators if writers_enabled and creator.role == "writer"]
    pencillers = [
        creator.name for creator in best_match.creators
        if pencillers_enabled and creator.role == "penciller"
    ]

    # Sort authors alphabetically
    writers = sorted(set(writers))  # Use set to avoid duplicates if same person has multiple roles
    pencillers = sorted(set(pencillers))
    logger.debug(f"_update_authors: Extracted {len(writers)} writers: {writers}")
    logger.debug(f"_update_authors: Extracted {len(pencillers)} pencillers: {pencillers}")

    if not writers and not pencillers:
        logger.debug("_update_authors: No writers or pencillers found")
        return f"- Authors: No matching creator roles found on {creators_provider}."

    # Create the authors list in Komga format
    komga_authors = []
    komga_authors.extend([{"name": author, "role": "writer"} for author in writers])
    komga_authors.extend([{"name": author, "role": "penciller"} for author in pencillers])
    logger.debug(f"_update_authors: Prepared Komga authors format: {komga_authors}")

    books_to_update = 0
    for book in books:
        logger.debug(f"_update_authors: Processing book '{book.name}' (ID: {book.id})")
        logger.debug(f"_update_authors: Book current authors: {book.metadata.authors}")
        logger.debug(f"_update_authors: Book authors lock: {book.metadata.authors_lock}")

        # Check update conditions
        should_update = should_update_field(book.metadata.authors, book.metadata.authors_lock, config)
        logger.debug(f"_update_authors: should_update_field returned {should_update}")

        if should_update:
            # Check if the authors list is different
            current_authors = [{'name': a['name'], 'role': a['role']} for a in book.metadata.authors if 'name' in a and 'role' in a]
            new_authors = [{'name': a['name'], 'role': a['role']} for a in komga_authors]

            logger.debug(f"_update_authors: Current normalized authors: {current_authors}")
            logger.debug(f"_update_authors: New normalized authors: {new_authors}")

            current_set = set(tuple(a.items()) for a in current_authors)
            new_set = set(tuple(a.items()) for a in new_authors)

            authors_different = current_set != new_set
            logger.debug(f"_update_authors: Authors are different: {authors_different}")

            if authors_different:
                books_to_update += 1
                if config.system.dry_run:
                    dry_run_changes.append(f"- Book '{book.name}' Authors: Will be set to {[a['name'] for a in komga_authors]}")
                    logger.debug(f"_update_authors: [DRY-RUN] Would update book '{book.name}' authors to {komga_authors}")
                else:
                    payload = {'authors': komga_authors}
                    if book.metadata.authors_lock and config.processing.force_unlock:
                        payload['authorsLock'] = False
                        logger.debug(f"_update_authors: Force unlocking authors lock for book '{book.name}'")

                    logger.debug(f"_update_authors: Updating book '{book.id}' with payload: {payload}")
                    success = komga_client.update_book_metadata(book.id, payload)
                    if success:
                        logger.debug(f"Successfully updated authors for book '{book.name}': {[a['name'] for a in komga_authors]}")
                        logger.info(f"Updated authors for book '{book.name}': {[a['name'] for a in komga_authors]}")
                    else:
                        logger.error(f"Failed to update authors for book '{book.name}'")
            else:
                logger.debug(f"_update_authors: No author changes needed for book '{book.name}'")
        else:
            logger.debug(f"_update_authors: Skipping author update for book '{book.name}' (locked or already set)")

    logger.debug(f"_update_authors: Finished processing, books_to_update = {books_to_update}")
    if books_to_update > 0:
        return "- Authors (update): Will be updated." if config.system.dry_run else f"- Authors (update): Updated on {books_to_update} books."
    else:
        types = []
        if writers_enabled:
            types.append("writers")
        if pencillers_enabled:
            types.append("pencillers")
        type_str = ', '.join(types) if types else "authors"
        return f"- Authors (update {type_str}): No changes needed."

def should_remove_field(current_value, is_locked: bool, config: AppConfig) -> bool:
    """Helper function to determine if a metadata field should be removed."""
    if is_locked and not config.processing.force_unlock:
        return False
    return bool(current_value)


FALLBACK_METADATA_FIELDS = (
    "description",
    "publisher",
    "genres",
    "status",
    "creators",
    "cover_urls",
    "score",
    "site_url",
)


def _required_metadata_fields(config: AppConfig) -> set[str]:
    """Map enabled Komga updates to normalized provider fields."""
    update = config.processing.update_fields
    required = set()
    if update.summary:
        required.add("description")
    if update.publisher:
        required.add("publisher")
    if update.genres:
        required.add("genres")
    if update.status:
        required.add("status")
    if update.authors.writers or update.authors.pencillers:
        required.add("creators")
    if update.cover_image:
        required.add("cover_urls")
    if update.tags.score:
        required.add("score")
    if update.link:
        required.add("site_url")
    return required


def _metadata_value_is_missing(field_name: str, value) -> bool:
    if value is None or value == "":
        return True
    if field_name == "score" and value <= 0:
        return True
    return isinstance(value, (list, tuple, set, dict)) and not value


def _missing_metadata_fields(record: MetadataRecord, required_fields: set[str]) -> set[str]:
    return {
        field_name
        for field_name in required_fields
        if _metadata_value_is_missing(field_name, getattr(record, field_name))
    }


def _merge_missing_metadata(primary: MetadataRecord, fallback: MetadataRecord) -> MetadataRecord:
    """Fill only missing normalized fields, preserving provider priority."""
    merged = primary.model_copy(deep=True)
    merged.provider_links = _provider_links(primary)
    for provider_name, url in _provider_links(fallback).items():
        merged.provider_links.setdefault(provider_name, url)

    for field_name in FALLBACK_METADATA_FIELDS:
        current_value = getattr(merged, field_name)
        fallback_value = getattr(fallback, field_name)
        if _metadata_value_is_missing(field_name, current_value) and not _metadata_value_is_missing(
            field_name, fallback_value
        ):
            setattr(merged, field_name, fallback_value)
            if field_name == "description":
                merged.description_language = fallback.description_language
            elif field_name == "genres":
                merged.genre_languages = fallback.genre_languages.copy()
            merged.set_field_source(field_name, fallback.source_provider(field_name))
    return merged


def _provider_entries(provider, config: AppConfig) -> List[ConfiguredProvider]:
    """Accept a provider chain while keeping direct single-provider calls usable."""
    if isinstance(provider, ProviderChain):
        return provider.entries
    return [ConfiguredProvider(config=config.providers[0], provider=provider)]


def _find_metadata_with_fallback(
    search_title: str,
    provider,
    config: AppConfig,
) -> Optional[MetadataRecord]:
    """Search providers by priority and fill missing fields from lower entries."""
    required_fields = _required_metadata_fields(config)
    best_match: Optional[MetadataRecord] = None

    for entry in _provider_entries(provider, config):
        if (
            best_match
            and not config.processing.update_fields.link
            and not _missing_metadata_fields(best_match, required_fields)
        ):
            break

        provider_config = entry.config
        metadata_provider = entry.provider

        try:
            candidates = metadata_provider.search(search_title)
            candidate = choose_best_match(
                search_title,
                candidates,
                provider_config.min_score,
                allow_adult=provider_config.allow_adult,
            )
            if not candidate:
                logger.info("No suitable match found on %s; trying the next provider.", provider_config.name)
                continue
            record = metadata_provider.get_metadata(candidate)
        except MetadataProviderError as exc:
            logger.warning("%s failed: %s; trying the next provider.", provider_config.name, exc)
            continue

        if record.adult and not provider_config.allow_adult:
            logger.warning(
                "Selected %s record is adult content and allow_adult is false; trying the next provider.",
                provider_config.name,
            )
            continue

        if best_match is None:
            best_match = record
            logger.info(
                "Primary match: '%s' (%s ID: %s)",
                record.display_title,
                record.provider,
                record.external_id,
            )
        else:
            missing_before = _missing_metadata_fields(best_match, required_fields)
            link_providers_before = set(_provider_links(best_match))
            best_match = _merge_missing_metadata(best_match, record)
            supplied = missing_before - _missing_metadata_fields(best_match, required_fields)
            if set(_provider_links(best_match)) - link_providers_before:
                supplied.add("link")
            if supplied:
                logger.info(
                    "%s supplied fallback metadata: %s",
                    provider_config.name,
                    ", ".join(sorted(supplied)),
                )

    return best_match

def process_single_series(
    series: KomgaSeries,
    config: AppConfig,
    komga_client: KomgaClient,
    provider: MetadataProvider | ProviderChain,
    translator: Optional[Translator],
) -> Optional[List[str]]:
    """
    Processes a single Komga series.
    In dry run mode, it returns a list of proposed changes.
    In normal mode, it applies changes and returns None.
    """
    logging.info("|                                                                                                    |")
    logging.info("|====================================================================================================|")
    log_frame(f"Processing Series: {series.name}", 'center')
    logging.info("|====================================================================================================|")
    payload = {}
    change_descriptions: List[str] = []

    books = []

    # 1. Handle removals first (don't need best_match)
    for handler in FIELD_HANDLERS:
        if handler.operation == 'remove':
            change = handler.process(payload, series, None, config, translator, komga_client)
            if change:
                change_descriptions.append(change)

    # Cover image remove (special case)
    if cover_remove_change := _remove_cover_image(series, config, komga_client):
        change_descriptions.append(cover_remove_change)

    books = []

    # Special handling for author removal
    remove_authors = config.processing.remove_fields.authors.writers or config.processing.remove_fields.authors.pencillers
    if remove_authors:
        books = komga_client.get_books_in_series(series.id, series.name)
        logger.debug(f"Retrieved {len(books)} books for series '{series.name}' for author removal")
        summary = _remove_authors(books, config, change_descriptions, komga_client, series.name)
        if summary:
            change_descriptions.append(summary)

    # Check if we need provider metadata for updates.
    need_metadata_search = (
        config.processing.update_fields.summary
        or config.processing.update_fields.publisher
        or config.processing.update_fields.genres
        or config.processing.update_fields.status
        or (config.processing.update_fields.authors.writers or config.processing.update_fields.authors.pencillers)
        or config.processing.update_fields.cover_image
        or config.processing.update_fields.tags.score
        or config.processing.update_fields.link
    )

    if need_metadata_search:
        search_title = (series.metadata.title or series.name).strip()
        logger.info("Matching '%s' using title '%s'", series.name, search_title)

        best_match = _find_metadata_with_fallback(search_title, provider, config)

        if best_match:
            logger.info(
                "Found best match: '%s' (%s ID: %s)",
                best_match.display_title, best_match.provider, best_match.external_id,
            )

            # Get books for author updates if not already retrieved
            update_authors_enabled = (config.processing.update_fields.authors.writers or config.processing.update_fields.authors.pencillers)
            if not books and update_authors_enabled:
                books = komga_client.get_books_in_series(series.id, series.name)
                logger.debug(f"Retrieved {len(books)} books for series '{series.name}' for author updates")

            # 3. Handle updates
            for handler in FIELD_HANDLERS:
                if handler.operation == 'update':
                    # Skip if remove was requested for this field
                    remove_requested = getattr(config.processing.remove_fields, handler.config_attr, False)
                    if isinstance(remove_requested, bool) and remove_requested:
                        continue
                    if hasattr(remove_requested, 'score') and remove_requested.score:
                        continue
                    change = handler.process(payload, series, best_match, config, translator, komga_client)
                    if change:
                        change_descriptions.append(change)

            # Special handling for author updates
            if update_authors_enabled:
                summary = _update_authors(books, best_match, config, change_descriptions, komga_client)
                if summary:
                    change_descriptions.append(summary)

            # Cover image update (special case)
            cover_handler = CoverImageHandler(operation="update", config_attr="cover_image")
            cover_change = cover_handler.process(payload, series, best_match, config, translator, komga_client)
            if cover_change:
                change_descriptions.append(cover_change)
        else:
            logger.warning(f"No suitable match found for '{series.name}' on any provider. Skipping metadata updates.")

    # 4. Finalize based on accumulated changes.
    if not change_descriptions:
        logger.info("No metadata changes required for this series.")
        return None

    # Log the changes immediately
    if config.system.dry_run:
        logger.info(f"[DRY-RUN] Proposed changes for '{series.name}':")
    for change in change_descriptions:
        logger.info(change)

    logger.info(f"Completed processing series '{series.name}'")

    if config.system.dry_run:
        return change_descriptions
    else:
        if payload:
            logger.info(f"Updating metadata for '{series.name}' on Komga...")
            success = komga_client.update_series_metadata(series.id, payload)
            if success:
                logger.info(f"Successfully updated metadata for '{series.name}'.")
            else:
                logger.error(f"Failed to update metadata for '{series.name}'.")
        return None
