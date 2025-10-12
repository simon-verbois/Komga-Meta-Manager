# Path: src/manga_manager/providers/__init__.py

# -*- coding: utf-8 -*-
"""
Provider module for handling metadata fetching.
This module acts as a factory for creating provider instances.
"""
import logging
from typing import Optional
from .base import MetadataProvider
from .anilist_provider import AnilistProvider

logger = logging.getLogger(__name__)

def get_provider(name: str) -> Optional[MetadataProvider]:
    """
    Factory function to get a provider instance based on its name.

    Args:
        name (str): The name of the provider (e.g., 'anilist').

    Returns:
        An instance of a MetadataProvider, or None if the provider is unknown.
    """
    provider_lower = name.lower()
    if provider_lower == 'anilist':
        logger.info("Using AniList metadata provider.")
        return AnilistProvider()
    else:
        logger.warning(f"Unknown metadata provider: '{name}'.")
        return None