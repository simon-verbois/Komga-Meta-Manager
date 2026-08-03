# -*- coding: utf-8 -*-
"""
Provider module for handling metadata fetching.
This module acts as a factory for creating provider instances.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from modules.config import ProviderConfig
from .base import MetadataProvider
from .anilist import AnilistProvider
from .mangadex import MangadexProvider
from .mangaupdates import MangaupdatesProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfiguredProvider:
    """A provider instance coupled to its matching configuration."""
    config: ProviderConfig
    provider: MetadataProvider


class ProviderChain:
    """Ordered collection of active metadata providers."""

    def __init__(self, entries: Iterable[ConfiguredProvider]):
        self.entries = list(entries)

    def save_cache(self) -> None:
        for entry in self.entries:
            entry.provider.save_cache()

    def log_cache_summary(self) -> None:
        for entry in self.entries:
            entry.provider.log_cache_summary()

def get_provider(config: ProviderConfig, cache_dir: Path) -> Optional[MetadataProvider]:
    """
    Factory function to get a provider instance based on its name.
    """
    provider_lower = config.name.lower()
    kwargs = {
        "cache_dir": cache_dir,
        "cache_ttl_hours": config.cache.ttl_hours,
        "preferred_language": config.preferred_language,
    }
    if provider_lower == 'anilist':
        logger.info("Using AniList metadata provider.")
        return AnilistProvider(**kwargs)
    if provider_lower == 'mangadex':
        logger.info("Using MangaDex metadata provider.")
        return MangadexProvider(**kwargs)
    if provider_lower == 'mangaupdates':
        logger.info("Using MangaUpdates metadata provider.")
        return MangaupdatesProvider(**kwargs)
    logger.warning(f"Unknown metadata provider: '{config.name}'.")
    return None


def get_providers(configs: Iterable[ProviderConfig], cache_dir: Path) -> Optional[ProviderChain]:
    """Initialize every configured provider in priority order."""
    entries = []
    for config in sorted(configs, key=lambda item: item.priority):
        provider = get_provider(config, cache_dir)
        if provider is None:
            return None
        entries.append(ConfiguredProvider(config=config, provider=provider))
    return ProviderChain(entries)
