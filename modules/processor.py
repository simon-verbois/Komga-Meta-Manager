"""
Core processing logic for the Manga Manager.
"""
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Callable
from dataclasses import dataclass

from modules.config import AppConfig
from modules.komga_client import KomgaClient
from modules.providers import get_provider
from modules.providers.base import MetadataProvider
from modules.translators import get_translator, Translator
from modules.models import KomgaSeries, AniListMedia, KomgaBook
from modules.utils import clean_html
from modules.utils import log_frame
from thefuzz import fuzz

logger = logging.getLogger(__name__)

ANILIST_STATUS_TO_KOMGA = {
    'RELEASING': 'ONGOING',
    'FINISHED': 'ENDED',
    'CANCELLED': 'ABANDONED',
    'HIATUS': 'HIATUS'
}

@dataclass
class FieldHandler:
    """Handles processing of a single metadata field."""
    field_name: str
    operation: str  # 'update' or 'remove'
    config_attr: str

    def process(self, payload: Dict, series: KomgaSeries, best_match: Optional[AniListMedia], config: AppConfig, translator: Optional[Translator], komga_client: Optional[KomgaClient] = None) -> Optional[str]:
        """Process this field and return change description if any."""
        metadata = series.metadata

        # Check if operation is enabled in config
        config_field = getattr(config.processing.update_fields if self.operation == 'update' else config.processing.remove_fields, self.config_attr, False)
        if not config_field:
            return None

        # For updates, we need a best_match
        if self.operation == 'update' and not best_match:
            return None

        # Check lock/force unlock logic
        if self.operation == 'update':
            should_process = should_update_field(getattr(metadata, self.field_name), getattr(metadata, self.field_name + '_lock'), config)
        else:
            should_process = should_remove_field(getattr(metadata, self.field_name), getattr(metadata, self.field_name + '_lock'), config)

        if not should_process:
            return None

        # Process the field
        return self._process_field(payload, series, best_match, config, translator, komga_client)

    def _process_field(self, payload, series, best_match, config, translator, komga_client) -> Optional[str]:
        """Subclass-specific field processing logic."""
        raise NotImplementedError

@dataclass
class SummaryHandler(FieldHandler):
    def _process_field(self, payload, series, best_match, config, translator, komga_client) -> Optional[str]:
        metadata = series.metadata

        if self.operation == 'update':
            new_value = clean_html(best_match.description) if best_match.description else None
            if new_value and translator and config.translation:
                new_value = translator.translate(new_value, config.translation.target_language)
            if not config.processing.overwrite_existing and new_value == metadata.summary:
                return None
        else:
            new_value = ""

        payload[self.field_name] = new_value
        if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
            payload[self.field_name + 'Lock'] = False
        return f"- {self.field_name.title()}: {'Will be updated' if self.operation == 'update' else 'Will be removed'}."

@dataclass
class GenresHandler(FieldHandler):
    def _process_field(self, payload, series, best_match, config, translator, komga_client) -> Optional[str]:
        metadata = series.metadata

        if self.operation == 'update':
            if not best_match.genres:
                return None
            translated_genres = set(best_match.genres)
            if translator and config.translation:
                translated_genres = {translator.translate(g, config.translation.target_language) for g in best_match.genres}
            new_value = sorted(list(translated_genres))
            if not config.processing.overwrite_existing and set(new_value) == set(metadata.genres or []):
                return None
        else:
            new_value = []

        payload[self.field_name] = new_value
        if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
            payload[self.field_name + 'Lock'] = False
        return f"- {self.field_name.title()}: Set to {new_value}" if self.operation == 'update' else f"- {self.field_name.title()}: Will be removed."

@dataclass
class StatusHandler(FieldHandler):
    field_name = "status"

    def _process_field(self, payload, series, best_match, config, translator, komga_client) -> Optional[str]:
        metadata = series.metadata

        if self.operation == 'update':
            if not best_match.status:
                return None
            new_value = ANILIST_STATUS_TO_KOMGA.get(best_match.status.upper())
            if not new_value or (not config.processing.overwrite_existing and new_value == metadata.status):
                return None
        else:
            new_value = None

        payload[self.field_name] = new_value
        if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
            payload[self.field_name + 'Lock'] = False
        return f"- {self.field_name.title()}: Set to '{new_value}'" if self.operation == 'update' else f"- {self.field_name.title()}: Will be removed."

@dataclass
class TagsHandler(FieldHandler):
    def _process_field(self, payload, series, best_match, config, translator, komga_client) -> Optional[str]:
        metadata = series.metadata

        if self.operation == "remove":
            if config.processing.remove_fields.tags.score:
                new_tags = set(metadata.tags or [])
                original_count = len(new_tags)
                new_tags = {tag for tag in new_tags if "score:" not in tag.lower()}
                if len(new_tags) < original_count:
                    new_tags_list = sorted(list(new_tags))
                    payload[self.field_name] = new_tags_list
                    if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
                        payload[self.field_name + 'Lock'] = False
                    return "- Tags: removed score tag."
                else:
                    return "- Tags: processed (no score tag to remove)."
            return None

        # Update operation
        new_tags = set(metadata.tags or [])  # Start with existing tags

        changes = []

        if config.processing.update_fields.tags.score and best_match and best_match.averageScore is not None and best_match.averageScore > 0:
            score_tag = f"Score: {best_match.averageScore / 10:.1f}"
            # Remove any existing score tags to avoid duplicates with different values (contains "score:")
            new_tags = {tag for tag in new_tags if "score:" not in tag.lower()}
            new_tags.add(score_tag)
            changes.append(f"added score tag '{score_tag}'")

        # Future: handle anilist_tags here

        new_tags_list = sorted(list(new_tags))

        # Check if changed
        current_tags_set = set(metadata.tags or [])
        if current_tags_set == set(new_tags_list):
            return "- Tags: processed (no changes needed)."

        payload[self.field_name] = new_tags_list
        if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
            payload[self.field_name + 'Lock'] = False
        return f"- {self.field_name.title()}: {', '.join(changes)}" if changes else None

@dataclass
class LinksHandler(FieldHandler):
    def _process_field(self, payload, series, best_match, config, translator, komga_client) -> Optional[str]:
        metadata = series.metadata

        if self.operation == "remove":
            if config.processing.remove_fields.link:
                new_links = getattr(metadata, self.field_name, [])
                original_count = len(new_links)
                provider_name = config.provider.name.upper()
                new_links = [link for link in new_links if not link.get('label', '').upper().startswith(provider_name)]
                if len(new_links) < original_count:
                    payload[self.field_name] = new_links
                    if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
                        payload[self.field_name + 'Lock'] = False
                    return "- Links: removed provider link."
                else:
                    return "- Links: processed (no provider link to remove)."
            return None

        # Update operation
        if config.processing.update_fields.link and best_match:
            new_links = getattr(metadata, self.field_name, [])
            provider_label = config.provider.name.capitalize()

            # Remove any existing provider links to avoid duplicates
            new_links = [link for link in new_links if link.get('label') != provider_label]

            # Always add the provider link
            new_links.append({"label": provider_label, "url": f"https://anilist.co/manga/{best_match.id}"})

            payload[self.field_name] = new_links
            links_lock_attr = self.field_name + '_lock'
            if hasattr(metadata, links_lock_attr) and getattr(metadata, links_lock_attr) and config.processing.force_unlock:
                payload[self.field_name + 'Lock'] = False
            return f"- {self.field_name.title()}: added provider link"

        return None



@dataclass
class CoverImageHandler:
    operation: str = "update"
    config_attr: str = "cover_image"

    def process(self, payload, series, best_match, config, translator, komga_client):
        if not config.processing.update_fields.cover_image or not best_match or not best_match.coverImage:
            return None

        image_url = best_match.coverImage.extraLarge or best_match.coverImage.large or best_match.coverImage.medium
        if not image_url:
            return None

        if config.system.dry_run:
            return f"- Cover Image: Will be updated from {image_url}"
        else:
            success = komga_client.upload_series_poster(series.id, image_url) if komga_client else False
            return f"- Cover Image: {'Successfully updated' if success else 'Failed to update'} from {image_url}"

# Global field handlers
FIELD_HANDLERS = [
    SummaryHandler("summary", "update", "summary"),
    SummaryHandler("summary", "remove", "summary"),
    GenresHandler("genres", "update", "genres"),
    GenresHandler("genres", "remove", "genres"),
    TagsHandler("tags", "update", "tags"),
    TagsHandler("tags", "remove", "tags"),
    LinksHandler("links", "update", "link"),
    LinksHandler("links", "remove", "link"),
    StatusHandler("status", "update", "status"),
    StatusHandler("status", "remove", "status"),
]




def choose_best_match(series_title: str, candidates: List[AniListMedia], min_score: int = 80) -> Optional[AniListMedia]:
    """
    Selects the best match from a list of candidates.
    It first filters candidates by a minimum fuzzy match score, then sorts by score,
    and finally by popularity as a tie-breaker.
    """
    if not candidates:
        return None

    scored_candidates = []
    for candidate in candidates:
        titles_to_check = [candidate.title.english, candidate.title.romaji]
        titles_to_check = [t for t in titles_to_check if t]  # Filter out None titles
        
        if not titles_to_check:
            continue

        # Calculate the highest score among the available titles
        score = max(fuzz.ratio(series_title.lower(), t.lower()) for t in titles_to_check)
        
        if score >= min_score:
            scored_candidates.append({'candidate': candidate, 'score': score})

    if not scored_candidates:
        return None

    # Sort by score (desc), then by popularity (desc) as a tie-breaker
    best = sorted(scored_candidates, key=lambda x: (x['score'], x['candidate'].popularity), reverse=True)[0]
    
    logger.info(f"Found {len(scored_candidates)} candidates with score >= {min_score}. Best match: '{best['candidate'].title.english or best['candidate'].title.romaji}' with score {best['score']}.")
    
    return best['candidate']

def should_update_field(current_value, is_locked: bool, config: AppConfig) -> bool:
    """Helper function to determine if a metadata field should be updated."""
    if is_locked and not config.processing.force_unlock:
        return False
    if config.processing.overwrite_existing:
        return True
    return not current_value

def process_libraries(config: AppConfig) -> Optional[Translator]:
    """
    Main processing function that iterates through libraries and series.
    It now returns the translator instance so its cache can be saved.
    """
    cache_dir = Path("/config/cache")
    cache_dir.mkdir(exist_ok=True)

    komga_client = KomgaClient(config.komga)
    metadata_provider = get_provider(config.provider, cache_dir)
    if not metadata_provider:
        logger.error(f"Failed to initialize provider '{config.provider.name}'. Aborting.")
        return None

    translator: Optional[Translator] = None
    if config.translation and config.translation.enabled:
        translator_provider = config.translation.provider.lower()
        translator_kwargs = {}
        if translator_provider == 'deepl':
            if config.translation.deepl:
                translator_kwargs['config'] = config.translation.deepl
            else:
                logger.error("DeepL provider is selected but its configuration is missing.")
                return None
        
        translator = get_translator(translator_provider, **translator_kwargs)

        if translator:
            logger.info(f"Translation enabled to target language: '{config.translation.target_language}'")
        else:
            logger.error("Failed to initialize translator. Translation will be disabled.")

    all_libraries = komga_client.get_libraries()
    if not all_libraries:
        logger.error("Could not retrieve libraries from Komga. Aborting.")
        return translator

    target_libraries = {lib.name: lib.id for lib in all_libraries if lib.name in config.komga.libraries}
    if not target_libraries:
        logger.warning("No matching libraries found on Komga server based on your config. Exiting.")
        return translator

    logger.info(f"Found {len(target_libraries)} target library/libraries to process: {list(target_libraries.keys())}")

    for lib_name, lib_id in target_libraries.items():
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
            if series.name in config.processing.exclude_series:
                logger.info(f"Skipping series '{series.name}', excluded.")
                continue

            try:
                proposed_changes = process_single_series(series, config, komga_client, metadata_provider, translator)
            except Exception as e:
                logger.error(f"Error processing series '{series.name}': {e} - skipping to next series")
                continue

    if metadata_provider:
        metadata_provider.save_cache()
        metadata_provider.log_cache_summary()

    if translator and hasattr(translator, 'log_cache_summary'):
        translator.log_cache_summary()

    return translator

def watch_for_new_series(config: AppConfig, komga_client: KomgaClient, target_libraries: dict, known_series: dict, metadata_provider, translator):
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
    new_series_found = False
    komga_logger = logging.getLogger('modules.komga_client')
    original_level = komga_logger.level

    for lib_name, lib_id in target_libraries.items():
        # Silence komga_client logs during polling to reduce noise
        komga_logger.setLevel(logging.WARNING)
        current_series = komga_client.get_series_in_library(lib_id, lib_name)
        komga_logger.setLevel(original_level)

        new_series = [s for s in current_series if s.id not in known_series[lib_id]]
        if new_series:
            new_series_found = True
            logging.info("|                                                                                                    |")
            logging.info("|====================================================================================================|")
            log_frame("Watcher", 'center')
            logging.info("|====================================================================================================|")
            logger.info(f"Watcher: Found {len(new_series)} new series in library '{lib_name}'")
            for series in new_series:
                if series.name in config.processing.exclude_series:
                    logger.info(f"Watcher: Skipping excluded series '{series.name}'")
                    continue
                logger.info(f"Watcher: Processing new series '{series.name}'")
                process_single_series(series, config, komga_client, metadata_provider, translator)
                known_series[lib_id].add(series.id)
        else:
            logger.debug(f"Watcher: No new series in library '{lib_name}'")

    if new_series_found:
        # Save caches after processing
        metadata_provider.save_cache()
        if translator and hasattr(translator, 'save_cache_to_disk'):
            translator.save_cache_to_disk()

    return new_series_found



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

def _remove_cover_image(series: KomgaSeries, config: AppConfig) -> Optional[str]:
    if not config.processing.remove_fields.cover_image:
        return None

    if config.system.dry_run:
        return "- Cover Image: Will be removed."
    else:
        # Note: Komga API doesn't have a specific endpoint to delete cover image
        # We could upload a placeholder or leave it as is for now
        logger.warning("Cover image removal not fully implemented in Komga API")
        return "- Cover Image: Removal not supported by Komga API."
    return None

def is_story_writer_role(role: str) -> bool:
    """Check if a role indicates story writing (case-insensitive match for 'story')."""
    return 'story' in role.lower()

def is_art_penciller_role(role: str) -> bool:
    """Check if a role indicates art/pencilling (case-insensitive match for 'art' but not 'touch-up art')."""
    role_lower = role.lower()
    return 'art' in role_lower and 'touch-up art' not in role_lower

def _update_authors(books: List[KomgaBook], best_match: AniListMedia, config: AppConfig, dry_run_changes: List[str], komga_client: KomgaClient) -> Optional[str]:
    """
    Update authors for all books in the series from AniList staff data.

    Args:
        books: List of books in the series
        best_match: AniList media match with staff information
        config: Application configuration
        dry_run_changes: List to collect change descriptions for dry run
        komga_client: Komga client instance

    Returns:
        Summary message if authors were processed, None otherwise
    """
    logger.debug(f"_update_authors: Starting author update processing for {len(books)} books")
    logger.debug(f"_update_authors: AniList media ID: {best_match.id}, title: {best_match.title.romaji or best_match.title.english}")
    logger.debug(f"_update_authors: config.processing.update_fields.authors = {config.processing.update_fields.authors}")

    writers_enabled = config.processing.update_fields.authors.writers
    pencillers_enabled = config.processing.update_fields.authors.pencillers

    if not writers_enabled and not pencillers_enabled:
        logger.debug("_update_authors: Authors updates disabled in config")
        return None

    if not best_match.staff or not best_match.staff.edges:
        logger.debug(f"_update_authors: No staff edges found for AniList media {best_match.id}")
        logger.debug(f"_update_authors: best_match.staff = {best_match.staff}")
        return "- Authors: No staff found on AniList."

    logger.debug(f"_update_authors: Found {len(best_match.staff.edges)} staff edges")

    # Extract authors with story writing and art roles from AniList staff
    writers = []
    pencillers = []
    for edge in best_match.staff.edges:
        logger.debug(f"_update_authors: Processing staff edge with role '{edge.role}' and name '{edge.node.name.full if edge.node.name else None}'")
        if edge.node.name.full:
            if writers_enabled and is_story_writer_role(edge.role):
                writers.append(edge.node.name.full)
                logger.debug(f"_update_authors: Added writer '{edge.node.name.full}' with role '{edge.role}'")
            if pencillers_enabled and is_art_penciller_role(edge.role):
                pencillers.append(edge.node.name.full)
                logger.debug(f"_update_authors: Added penciller '{edge.node.name.full}' with role '{edge.role}'")

    # Sort authors alphabetically
    writers = sorted(set(writers))  # Use set to avoid duplicates if same person has multiple roles
    pencillers = sorted(set(pencillers))
    logger.debug(f"_update_authors: Extracted {len(writers)} writers: {writers}")
    logger.debug(f"_update_authors: Extracted {len(pencillers)} pencillers: {pencillers}")

    if not writers and not pencillers:
        logger.debug("_update_authors: No writers or pencillers found")
        return "- Authors: No authors found on AniList."

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
    return True

def process_single_series(
    series: KomgaSeries,
    config: AppConfig,
    komga_client: KomgaClient,
    provider: MetadataProvider,
    translator: Optional[Translator]
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
    if cover_remove_change := _remove_cover_image(series, config):
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

    # Check if we need to query AniList for updates
    need_anilist_search = (
        config.processing.update_fields.summary
        or config.processing.update_fields.genres
        or config.processing.update_fields.status
        or (config.processing.update_fields.authors.writers or config.processing.update_fields.authors.pencillers)
        or config.processing.update_fields.cover_image
        or config.processing.update_fields.tags.score
        or config.processing.update_fields.link
    )

    if need_anilist_search:
        # 2. Search for a match to perform updates.
        candidates = provider.search(series.name)
        best_match = choose_best_match(series.name, candidates, config.provider.min_score)

        if best_match:
            logger.info(f"Found best match: '{best_match.title.english or best_match.title.romaji}' (ID: {best_match.id})")

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
                    if hasattr(remove_requested, 'anilist') and remove_requested.anilist:
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
            logger.warning(f"No suitable match found for '{series.name}' on {type(provider).__name__}. Skipping metadata updates.")

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
