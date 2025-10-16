# -*- coding: utf-8 -*-
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from modules.cache import Cache
from modules.models import AniListMedia
from modules.utils import load_app_version

logger = logging.getLogger(__name__)

class MetadataProvider(ABC):
    """Abstract base class for a metadata provider."""

    def __init__(self, cache_dir: Path, cache_ttl_hours: int):
        provider_name = self.__class__.__name__.lower().replace("provider", "")
        current_version = load_app_version()
        self.cache = Cache(provider_name, cache_dir, cache_ttl_hours, is_provider_cache=True, current_version=current_version)

    @abstractmethod
    def _perform_search(self, search_term: str) -> List[AniListMedia]:
        """
        Performs the actual search for media based on a search term.
        This method should be implemented by subclasses.
        """
        pass

    def search(self, search_term: str) -> List[AniListMedia]:
        """
        Searches for media based on a search term, utilizing a cache.
        """
        cached_results = self.cache.get(search_term)
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
