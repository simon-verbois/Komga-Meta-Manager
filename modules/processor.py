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
from modules.models import KomgaSeries, AniListMedia
from modules.utils import clean_html
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
        logger.info(f"--- Processing library: '{lib_name}' (ID: {lib_id}) ---")
        series_list = komga_client.get_series_in_library(lib_id, lib_name)

        if not series_list:
            logger.info("No series found in this library.")
            continue

        for series in series_list:
            if series.name in config.processing.exclude_series:
                logger.info(f"Skipping series '{series.name}' as it is in the exclude list.")
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
        if new_summary and new_summary != metadata.summary:
            if translator and config.translation:
                new_summary = translator.translate(new_summary, config.translation.target_language)
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

def _update_authors(payload: Dict, series: KomgaSeries, best_match: AniListMedia, config: AppConfig):
    """Update the authors field in Komga from AniList staff data."""
    logger.debug(f"Checking authors update for '{series.name}' - Config enabled: {config.processing.update_fields.authors}")

    if not config.processing.update_fields.authors:
        logger.debug("Authors update disabled in configuration")
        return None

    metadata = series.metadata
    current_authors = metadata.authors or []
    logger.debug(f"Current authors in Komga: {current_authors}")

    if not best_match.staff:
        logger.debug("No staff data found in AniList response")
        return None

    logger.debug(f"Found {len(best_match.staff)} staff entries in AniList")

    # Extract author names from staff data (prioritize Story, Art roles)
    authors = []
    for staff_edge in best_match.staff:
        logger.debug(f"Processing staff: {staff_edge}")
        if staff_edge.node.name and staff_edge.node.name.full:
            name = staff_edge.node.name.full
            role = staff_edge.role.lower()
            logger.debug(f"Staff member: '{name}' with role '{staff_edge.role}'")

            # Include Story/Art roles or any primary creator roles
            if any(keyword in role for keyword in ['story', 'art', 'author', 'creator', 'writer', 'artist']):
                authors.append(name)
                logger.debug(f"Included '{name}' as author")
            else:
                logger.debug(f"Skipped '{name}' - role '{staff_edge.role}' not considered author role")
        else:
            logger.debug(f"Skipped staff entry - missing name data: {staff_edge}")

    # Remove duplicates while preserving order
    authors = list(dict.fromkeys(authors))
    logger.debug(f"Deduplicated authors list: {authors}")

    authors_lock = metadata.authors_lock
    can_update = should_update_field(current_authors, authors_lock, config)
    logger.debug(f"Can update authors? {can_update} (current: {current_authors}, new: {authors}, locked: {authors_lock})")

    if authors and can_update and set(authors) != set(current_authors):
        payload['authors'] = authors
        if authors_lock and config.processing.force_unlock:
            payload['authorsLock'] = False
        logger.info(f"Will update authors to: {authors}")
        return f"- Authors: Set to {authors}"
    else:
        logger.debug(f"No authors update needed - authors: {authors}, can_update: {can_update}")

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
    logger.info(f"--- Processing Series: {series.name} ---")

    candidates = provider.search(series.name, config)
    best_match = choose_best_match(series.name, candidates, config.provider.min_score)

    if not best_match:
        logger.warning(f"No suitable match found for '{series.name}' on {type(provider).__name__}.")
        return None

    logger.info(f"Found best match: '{best_match.title.english or best_match.title.romaji}' (ID: {best_match.id})")

    payload = {}
    change_descriptions: List[str] = []

    update_fns = [
        lambda: _update_summary(payload, series, best_match, config, translator),
        lambda: _update_genres(payload, series, best_match, config, translator),
        lambda: _update_status(payload, series, best_match, config),
        lambda: _update_tags(payload, series, best_match, config, translator),
        lambda: _update_age_rating(payload, series, best_match, config),
        lambda: _update_authors(payload, series, best_match, config),
    ]

    for fn in update_fns:
        if change := fn():
            change_descriptions.append(change)

    # Handle cover image separately as it's not part of the metadata payload
    if cover_change := _update_cover_image(series, best_match, config, komga_client):
        change_descriptions.append(cover_change)

    if not payload and not config.processing.update_fields.cover_image:
        logger.info("No metadata changes required for this series.")
        return None
        
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
