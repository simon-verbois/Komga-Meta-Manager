"""
Core processing logic for the Manga Manager.
"""
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict

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

def _print_dry_run_report(processed_count: int, updated_series_report: Dict[str, List[str]]):
    """Formats and prints a summary report for a dry run."""
    updated_count = len(updated_series_report)
    
    report_lines = [
        "\n",
        "================================================================",
        "                    --- Dry Run Report ---                      ",
        "================================================================",
        f"\nSeries Processed: {processed_count}",
        f"Series to be Updated: {updated_count}\n"
    ]

    if not updated_series_report:
        report_lines.append("No changes to be made.")
    else:
        for series_name, changes in sorted(updated_series_report.items()):
            report_lines.append(f"Changes for '{series_name}':")
            for change in changes:
                report_lines.append(f"  {change}")
            report_lines.append("")

    report_lines.append("================================================================")
    
    for line in report_lines:
        logger.info(line)

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

    processed_count = 0
    updated_series_report: Dict[str, List[str]] = {}

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
            
            processed_count += 1
            proposed_changes = process_single_series(series, config, komga_client, metadata_provider, translator)
            if config.system.dry_run and proposed_changes:
                updated_series_report[series.name] = proposed_changes

    if config.system.dry_run:
        _print_dry_run_report(processed_count, updated_series_report)

    if metadata_provider:
        metadata_provider.save_cache()
        metadata_provider.log_cache_summary()

    if translator and hasattr(translator, 'log_cache_summary'):
        translator.log_cache_summary()
        
    return translator


def _update_summary(payload: Dict, series: KomgaSeries, best_match: AniListMedia, config: AppConfig, translator: Optional[Translator]):
    if not config.processing.update_fields.summary:
        return None
    metadata = series.metadata
    if should_update_field(metadata.summary, metadata.summary_lock, config):
        new_summary = clean_html(best_match.description)
        if new_summary:
            if translator and config.translation:
                new_summary = translator.translate(new_summary, config.translation.target_language)
            if config.processing.overwrite_existing or new_summary != metadata.summary:
                payload['summary'] = new_summary
                if metadata.summary_lock and config.processing.force_unlock:
                    payload['summaryLock'] = False
                return "- Summary: Will be updated."
    return None

def _update_genres(payload: Dict, series: KomgaSeries, best_match: AniListMedia, config: AppConfig, translator: Optional[Translator]):
    if not config.processing.update_fields.genres:
        return None
    metadata = series.metadata
    if best_match.genres and should_update_field(metadata.genres, metadata.genres_lock, config):
        translated_genres = set(best_match.genres)
        if translator and config.translation:
            translated_genres = {translator.translate(genre, config.translation.target_language) for genre in best_match.genres}
        if translated_genres != metadata.genres:
            sorted_genres = sorted(list(translated_genres))
            payload['genres'] = sorted_genres
            if metadata.genres_lock and config.processing.force_unlock:
                payload['genresLock'] = False
            return f"- Genres: Set to {sorted_genres}"
    return None

def _update_status(payload: Dict, series: KomgaSeries, best_match: AniListMedia, config: AppConfig):
    if not config.processing.update_fields.status:
        return None
    metadata = series.metadata
    if best_match.status and should_update_field(metadata.status, metadata.status_lock, config):
        new_status = ANILIST_STATUS_TO_KOMGA.get(best_match.status.upper())
        if new_status and new_status != metadata.status:
            payload['status'] = new_status
            if metadata.status_lock and config.processing.force_unlock:
                payload['statusLock'] = False
            return f"- Status: Set to '{new_status}'"
    return None

def _update_tags(payload: Dict, series: KomgaSeries, best_match: AniListMedia, config: AppConfig, translator: Optional[Translator]):
    if not config.processing.update_fields.tags:
        return None
    metadata = series.metadata
    if best_match.tags and should_update_field(metadata.tags, metadata.tags_lock, config):
        extracted_tags = {tag['name'] for tag in best_match.tags if 'name' in tag}
        translated_tags = extracted_tags
        if translator and config.translation:
            translated_tags = {translator.translate(tag, config.translation.target_language) for tag in extracted_tags}
        if translated_tags != metadata.tags:
            sorted_tags = sorted(list(translated_tags))
            payload['tags'] = sorted_tags
            if metadata.tags_lock and config.processing.force_unlock:
                payload['tagsLock'] = False
            return f"- Tags: Set to {sorted_tags}"
    return None

def _update_age_rating(payload: Dict, series: KomgaSeries, best_match: AniListMedia, config: AppConfig):
    if not config.processing.update_fields.age_rating:
        return None
    metadata = series.metadata
    if best_match.isAdult and should_update_field(metadata.age_rating, metadata.age_rating_lock, config):
        if metadata.age_rating != 18:
            payload['ageRating'] = 18
            if metadata.age_rating_lock and config.processing.force_unlock:
                payload['ageRatingLock'] = False
            return "- Age Rating: Set to 18 (Adult)"
    return None

def _update_cover_image(series: KomgaSeries, best_match: AniListMedia, config: AppConfig, komga_client: KomgaClient) -> Optional[str]:
    if not config.processing.update_fields.cover_image:
        return None

    if best_match.coverImage:
        image_url = best_match.coverImage.extraLarge or best_match.coverImage.large or best_match.coverImage.medium
        if not image_url:
            return None

        if config.system.dry_run:
            return f"- Cover Image: Will be updated from {image_url}"
        else:
            if komga_client.upload_series_poster(series.id, image_url):
                return f"- Cover Image: Successfully updated from {image_url}"
            else:
                return f"- Cover Image: Failed to update."
    return None

def _remove_summary(payload: Dict, series: KomgaSeries, config: AppConfig):
    if not config.processing.remove_fields.summary:
        return None
    metadata = series.metadata
    if should_remove_field(metadata.summary, metadata.summary_lock, config):
        payload['summary'] = ""
        if metadata.summary_lock and config.processing.force_unlock:
            payload['summaryLock'] = False
        return "- Summary: Will be removed."
    return None

def _remove_genres(payload: Dict, series: KomgaSeries, config: AppConfig):
    if not config.processing.remove_fields.genres:
        return None
    metadata = series.metadata
    if should_remove_field(metadata.genres, metadata.genres_lock, config):
        payload['genres'] = []
        if metadata.genres_lock and config.processing.force_unlock:
            payload['genresLock'] = False
        return "- Genres: Will be removed."
    return None

def _remove_status(payload: Dict, series: KomgaSeries, config: AppConfig):
    if not config.processing.remove_fields.status:
        return None
    metadata = series.metadata
    if should_remove_field(metadata.status, metadata.status_lock, config):
        payload['status'] = None
        if metadata.status_lock and config.processing.force_unlock:
            payload['statusLock'] = False
        return "- Status: Will be removed."
    return None

def _remove_tags(payload: Dict, series: KomgaSeries, config: AppConfig):
    if not config.processing.remove_fields.tags:
        return None
    metadata = series.metadata
    if should_remove_field(metadata.tags, metadata.tags_lock, config):
        payload['tags'] = []
        if metadata.tags_lock and config.processing.force_unlock:
            payload['tagsLock'] = False
        return "- Tags: Will be removed."
    return None

def _remove_age_rating(payload: Dict, series: KomgaSeries, config: AppConfig):
    if not config.processing.remove_fields.age_rating:
        return None
    metadata = series.metadata
    if should_remove_field(metadata.age_rating, metadata.age_rating_lock, config):
        payload['ageRating'] = None
        if metadata.age_rating_lock and config.processing.force_unlock:
            payload['ageRatingLock'] = False
        return "- Age Rating: Will be removed."
    return None

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

    # 1. Handle removals first, as they have priority and are independent of finding a match.
    # Get books in series for author removals that need to be done per book
    books = []
    if config.processing.remove_fields.authors:
        books = komga_client.get_books_in_series(series.id, series.name)
        logger.debug(f"Retrieved {len(books)} books for series '{series.name}' for author removal")

    remove_fns = [
        (_remove_summary, series, config),
        (_remove_genres, series, config),
        (_remove_status, series, config),
        (_remove_tags, series, config),
        (_remove_age_rating, series, config),
    ]
    for remove_fn, *args in remove_fns:
        if change := remove_fn(payload, *args):
            change_descriptions.append(change)

    if cover_remove_change := _remove_cover_image(series, config):
        change_descriptions.append(cover_remove_change)

    if _remove_authors(books, config, change_descriptions, komga_client):
        pass  # Changes are handled inside the function

    # 2. Search for a match to perform updates.
    candidates = provider.search(series.name)
    best_match = choose_best_match(series.name, candidates, config.provider.min_score)

    if best_match:
        logger.info(f"Found best match: '{best_match.title.english or best_match.title.romaji}' (ID: {best_match.id})")

        # Get books for author updates if not already retrieved
        if not books and config.processing.update_fields.authors:
            books = komga_client.get_books_in_series(series.id, series.name)
            logger.debug(f"Retrieved {len(books)} books for series '{series.name}' for author updates")

        # 3. Handle updates only if a match was found and removal wasn't requested for the field.
        update_actions = [
            (not config.processing.remove_fields.summary, lambda: _update_summary(payload, series, best_match, config, translator)),
            (not config.processing.remove_fields.genres, lambda: _update_genres(payload, series, best_match, config, translator)),
            (not config.processing.remove_fields.status, lambda: _update_status(payload, series, best_match, config)),
            (not config.processing.remove_fields.tags, lambda: _update_tags(payload, series, best_match, config, translator)),
            (not config.processing.remove_fields.age_rating, lambda: _update_age_rating(payload, series, best_match, config)),
        ]

        for condition, update_fn in update_actions:
            if condition:
                if change := update_fn():
                    change_descriptions.append(change)

        if not config.processing.remove_fields.cover_image:
            if cover_change := _update_cover_image(series, best_match, config, komga_client):
                change_descriptions.append(cover_change)

        # Handle author updates for books
        if not config.processing.remove_fields.authors:
            if _update_authors(books, best_match, config, change_descriptions, komga_client):
                pass  # Changes are handled inside the function
    else:
        logger.warning(f"No suitable match found for '{series.name}' on {type(provider).__name__}. Skipping metadata updates.")

    # 4. Finalize based on accumulated changes.
    if not change_descriptions:
        logger.info("No metadata changes required for this series.")
        return None

    if config.system.dry_run:
        logger.warning(f"[DRY-RUN] Series '{series.name}' has pending changes.")
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
