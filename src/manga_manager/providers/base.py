# Path: src/manga_manager/providers/base.py

# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod
from typing import List

from manga_manager.models import AniListMedia

class MetadataProvider(ABC):
    """Abstract base class for a metadata provider."""

    @abstractmethod
    def search(self, search_term: str) -> List[AniListMedia]:
        """
        Searches for media based on a search term.

        Args:
            search_term (str): The title to search for.

        Returns:
            A list of potential media matches.
        """
        pass