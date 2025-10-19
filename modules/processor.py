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
    field_name = "tags"

    def _process_field(self, payload, series, best_match, config, translator, komga_client) -> Optional[str]:
        metadata = series.metadata

        if self.operation == 'update':
            if not best_match.tags:
                return None
            extracted_tags = {tag['name'] for tag in best_match.tags if 'name' in tag}
            translated_tags = extracted_tags
            if translator and config.translation:
                translated_tags = {translator.translate(tag, config.translation.target_language) for tag in extracted_tags}
            new_value = sorted(list(translated_tags))
            if not config.processing.overwrite_existing and set(new_value) == set(metadata.tags or []):
                return None
        else:
            new_value = []

        payload[self.field_name] = new_value
        if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
            payload[self.field_name + 'Lock'] = False
        return f"- {self.field_name.title()}: Set to {new_value}" if self.operation == 'update' else f"- {self.field_name.title()}: Will be removed."

@dataclass
class AgeRatingHandler(FieldHandler):
    field_name = "age_rating"

    def _process_field(self, payload, series, best_match, config, translator, komga_client) -> Optional[str]:
        metadata = series.metadata

        if self.operation == 'update':
            if not best_match.isAdult:
                return None
            new_value = 18
            if not config.processing.overwrite_existing and metadata.age_rating == 18:
                return None
        else:
            new_value = None

        payload[self.field_name] = new_value
        if getattr(metadata, self.field_name + '_lock') and config.processing.force_unlock:
            payload[self.field_name + 'Lock'] = False
        return "- Age Rating: Set to 18 (Adult)" if self.operation == 'update' else "- Age Rating: Will be removed."

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
    StatusHandler("status", "update", "status"),
    StatusHandler("status", "remove", "status"),
    TagsHandler("tags", "update", "tags"),
    TagsHandler("tags", "remove", "tags"),
    AgeRatingHandler("age_rating", "update", "age_rating"),
    AgeRatingHandler("age_rating", "remove", "age_rating"),
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

            proposed_changes = process_single_series(series, config, komga_client, metadata_provider, translator)

    if metadata_provider:
        metadata_provider.save_cache()
        metadata_provider.log_cache_summary()

    if translator and hasattr(translator, 'log_cache_summary'):
        translator.log_cache_summary()
        
    return translator



def _remove_authors(books: List[KomgaBook], config: AppConfig, dry_run_changes: List[str], komga_client: KomgaClient) -> bool:
    """
    Remove authors from all books in the series if requested in config.

    Args:
        books: List of books in the series
        config: Application configuration
        dry_run_changes: List to collect change descriptions for dry run
        komga_client: Komga client instance

    Returns:
        True if changes were made or would be made, False otherwise
    """
    if not config.processing.remove_fields.authors:
        return False

    has_changes = False
    for book in books:
        metadata = book.metadata
        if should_remove_field(metadata.authors, metadata.authors_lock, config):
            if config.system.dry_run:
                dry_run_changes.append(f"- Book '{book.name}' Authors: Will be removed.")
            else:
                payload = {'authors': []}
                if metadata.authors_lock and config.processing.force_unlock:
                    payload['authorsLock'] = False

                success = komga_client.update_book_metadata(book.id, payload)
                if success:
                    logger.debug(f"Successfully removed authors from book '{book.name}'")
                else:
                    logger.error(f"Failed to remove authors from book '{book.name}'")
            has_changes = True

    return has_changes

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

def _update_authors(books: List[KomgaBook], best_match: AniListMedia, config: AppConfig, dry_run_changes: List[str], komga_client: KomgaClient) -> bool:
    """
    Update authors for all books in the series from AniList staff data.

    Args:
        books: List of books in the series
        best_match: AniList media match with staff information
        config: Application configuration
        dry_run_changes: List to collect change descriptions for dry run
        komga_client: Komga client instance

    Returns:
        True if changes were made or would be made, False otherwise
    """
    logger.debug(f"_update_authors: Starting author update processing for {len(books)} books")
    logger.debug(f"_update_authors: AniList media ID: {best_match.id}, title: {best_match.title.romaji or best_match.title.english}")
    logger.debug(f"_update_authors: config.processing.update_fields.authors = {config.processing.update_fields.authors}")

    if not config.processing.update_fields.authors:
        logger.debug("_update_authors: Authors updates disabled in config")
        return False

    if not best_match.staff or not best_match.staff.edges:
        logger.debug(f"_update_authors: No staff edges found for AniList media {best_match.id}")
        logger.debug(f"_update_authors: best_match.staff = {best_match.staff}")
        return False

    logger.debug(f"_update_authors: Found {len(best_match.staff.edges)} staff edges")

    # Extract authors with story writing roles from AniList staff
    story_art_authors = []
    for edge in best_match.staff.edges:
        logger.debug(f"_update_authors: Processing staff edge with role '{edge.role}' and name '{edge.node.name.full if edge.node.name else None}'")
        if is_story_writer_role(edge.role) and edge.node.name.full:
            story_art_authors.append(edge.node.name.full)
            logger.debug(f"_update_authors: Added author '{edge.node.name.full}' with role '{edge.role}'")

    # Sort authors alphabetically
    story_art_authors = sorted(story_art_authors)
    logger.debug(f"_update_authors: Extracted {len(story_art_authors)} story writers: {story_art_authors}")

    if not story_art_authors:
        logger.debug("_update_authors: No story writers found")
        return False

    # Create the authors list in Komga format
    komga_authors = [{"name": author, "role": "writer"} for author in story_art_authors]
    logger.debug(f"_update_authors: Prepared Komga authors format: {komga_authors}")

    has_changes = False
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
                has_changes = True
            else:
                logger.debug(f"_update_authors: No author changes needed for book '{book.name}'")
        else:
            logger.debug(f"_update_authors: Skipping author update for book '{book.name}' (locked or already set)")

    logger.debug(f"_update_authors: Finished processing, has_changes = {has_changes}")
    return has_changes

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
            if handler.config_attr == 'authors':
                books = komga_client.get_books_in_series(series.id, series.name)
                logger.debug(f"Retrieved {len(books)} books for series '{series.name}' for author removal")

            change = handler.process(payload, series, None, config, translator, komga_client)
            if change:
                change_descriptions.append(change)

            # Special handling for author removal
            if handler.config_attr == 'authors':
                if _remove_authors(books, config, change_descriptions, komga_client):
                    pass  # Changes are handled inside the function

    # Cover image remove (special case)
    if cover_remove_change := _remove_cover_image(series, config):
        change_descriptions.append(cover_remove_change)

    # 2. Search for a match to perform updates.
    candidates = provider.search(series.name)
    best_match = choose_best_match(series.name, candidates, config.provider.min_score)

    if best_match:
        logger.info(f"Found best match: '{best_match.title.english or best_match.title.romaji}' (ID: {best_match.id})")

        # Get books for author updates if not already retrieved
        if not books and config.processing.update_fields.authors:
            books = komga_client.get_books_in_series(series.id, series.name)
            logger.debug(f"Retrieved {len(books)} books for series '{series.name}' for author updates")

        # 3. Handle updates
        for handler in FIELD_HANDLERS:
            if handler.operation == 'update':
                # Skip if remove was requested for this field
                if getattr(config.processing.remove_fields, handler.config_attr, False):
                    continue

                change = handler.process(payload, series, best_match, config, translator, komga_client)
                if change:
                    change_descriptions.append(change)

                # Special handling for author updates
                if handler.config_attr == 'authors':
                    if _update_authors(books, best_match, config, change_descriptions, komga_client):
                        pass  # Changes are handled inside the function

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
