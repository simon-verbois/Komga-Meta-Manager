# -*- coding: utf-8 -*-
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from modules.cache import Cache
from modules.models import AniListMedia
from modules.config import AppConfig

logger = logging.getLogger(__name__)

class MetadataProvider(ABC):
    """Abstract base class for a metadata provider."""

    def __init__(self, cache_dir: Path, cache_ttl_hours: int):
        provider_name = self.__class__.__name__.lower().replace("provider", "")
        self.cache = Cache(provider_name, cache_dir, cache_ttl_hours)

    @abstractmethod
    def _perform_search(self, search_term: str) -> List[AniListMedia]:
        """
        Performs the actual search for media based on a search term.
        This method should be implemented by subclasses.
        """
        pass

    def has_required_fields(self, cached_data: dict, config: AppConfig) -> bool:
        """
        Check if cached data contains all required fields based on configuration.

        This method validates that cached data is fresh enough to contain all
        fields that are currently enabled in the configuration. If a field is
        enabled but not present in cached data, the cache is considered stale.

        Args:
            cached_data: The cached data dictionary for a single media item
            config: The application configuration

        Returns:
            True if the cached data has all required fields, False otherwise
        """
        # Check for authors/staff data if authors are enabled
        if config.processing.update_fields.authors:
            if 'staff' not in cached_data or cached_data['staff'] is None:
                logger.debug(f"Cache miss for field 'staff' - data contains: {list(cached_data.keys())}")
                return False

        # Future: Add checks for other optional fields as they are added
        # if config.processing.update_fields.some_new_field:
        #     if 'some_new_field' not in cached_data:
        #         return False

        return True

    def search(self, search_term: str, config: AppConfig) -> List[AniListMedia]:
        """
        Searches for media based on a search term, utilizing a cache with field validation.
        """
        cached_results = self.cache.get(search_term)

        # Validate cache freshness - check if all required fields are present
        if cached_results is not None:
            if not self.has_required_fields(cached_results[0] if cached_results else {}, config):
                logger.info(f"Cache stale for '{search_term}' - missing required fields, forcing fresh API call")
                cached_results = None

        if cached_results is not None:
            # Pydantic models need to be reconstructed from dict
            return [AniListMedia.model_validate(data) for data in cached_results]

        results = self._perform_search(search_term)

        if results:
            # Store as dicts to ensure JSON serializability
            self.cache.set(search_term, [media.model_dump(mode='json') for media in results])

        return results

    def save_cache(self):
        """Saves the cache to disk."""
        self.cache.save_to_disk()

    def log_cache_summary(self):
        """Logs a summary of the cache's state."""
        self.cache.log_cache_summary()
