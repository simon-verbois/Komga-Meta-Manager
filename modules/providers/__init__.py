# -*- coding: utf-8 -*-
"""
Provider module for handling metadata fetching.
This module acts as a factory for creating provider instances.
"""
import logging
from pathlib import Path
from typing import Optional

from modules.config import ProviderConfig
from .base import MetadataProvider
from .anilist_provider import AnilistProvider

logger = logging.getLogger(__name__)

def get_provider(config: ProviderConfig, cache_dir: Path) -> Optional[MetadataProvider]:
    """
    Factory function to get a provider instance based on its name.
    """
    provider_lower = config.name.lower()
    if provider_lower == 'anilist':
        logger.info("Using AniList metadata provider.")
        return AnilistProvider(cache_dir=cache_dir, cache_ttl_hours=config.cache.ttl_hours)
    else:
        logger.warning(f"Unknown metadata provider: '{config.name}'.")
        return None
