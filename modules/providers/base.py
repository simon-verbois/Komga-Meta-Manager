# -*- coding: utf-8 -*-
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from modules.cache import Cache
from modules.cache_naming import get_metadata_cache_filename
from modules.models import MetadataCandidate, MetadataRecord

logger = logging.getLogger(__name__)


class MetadataProviderError(RuntimeError):
    """Raised when a provider search fails rather than returning no matches."""

class MetadataProvider(ABC):
    """Abstract base class for a metadata provider."""

    def __init__(self, cache_dir: Path, cache_ttl_hours: int):
        provider_name = self.__class__.__name__.lower().replace("provider", "")
        cache_filename = get_metadata_cache_filename(provider_name)
        self.cache = Cache(cache_filename, cache_dir, cache_ttl_hours)

    @abstractmethod
    def _perform_search(self, search_term: str) -> List[MetadataCandidate]:
        """
        Performs the actual search for media based on a search term.
        This method should be implemented by subclasses.
        """
        pass

    @abstractmethod
    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        """Fetch and normalize a complete metadata record by provider ID."""
        pass

    def search(self, search_term: str) -> List[MetadataCandidate]:
        """
        Searches for media based on a search term, utilizing a cache.
        """
        # v3 invalidates candidates cached before providers included alternative
        # titles. Those entries cannot be repaired locally because only the
        # normalized candidate (and not the provider response) is cached.
        cache_key = f"search:v3:{search_term}"
        cached_results = self.cache.get(cache_key)
        if cached_results is not None:
            return [MetadataCandidate.model_validate(data) for data in cached_results]

        results = self._perform_search(search_term)

        # Successful empty searches are cached too, preventing repeated API calls.
        self.cache.set(cache_key, [media.model_dump(mode='json') for media in results])

        return results

    def get_by_id(self, external_id: str) -> MetadataRecord:
        """Fetch a complete record by provider ID, using the detail cache."""
        # v5 includes the provider-link collection. Changing the version
        # prevents older detail records from hiding newly supported fields.
        cache_key = f"detail:v5:{external_id}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return MetadataRecord.model_validate(cached_result)

        result = self._perform_get_metadata(str(external_id))
        self.cache.set(cache_key, result.model_dump(mode='json'))
        return result

    def get_metadata(self, candidate: MetadataCandidate) -> MetadataRecord:
        return self.get_by_id(candidate.external_id)

    def save_cache(self):
        """Saves the cache to disk."""
        self.cache.save_to_disk()

    def log_cache_summary(self):
        """Logs a summary of the cache's state."""
        self.cache.log_cache_summary()
