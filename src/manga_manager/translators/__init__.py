# Path: src/manga_manager/translators/__init__.py

# -*- coding: utf-8 -*-
"""
Translator module for handling metadata translation.
This module acts as a factory for creating translator instances.
"""
import logging
from typing import Optional
from .base import Translator
from .google_translator import GoogleTranslator

logger = logging.getLogger(__name__)

def get_translator(provider: str) -> Optional[Translator]:
    """
    Factory function to get a translator instance based on the provider name.

    Args:
        provider (str): The name of the translation provider (e.g., 'google').

    Returns:
        An instance of a Translator class, or None if the provider is unknown or fails to initialize.
    """
    provider_lower = provider.lower()
    if provider_lower == 'google':
        logger.info("Using Google Translate provider.")
        return GoogleTranslator()
    else:
        logger.warning(f"Unknown translation provider: '{provider}'. Translation will be disabled.")
        return None