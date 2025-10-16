# -*- coding: utf-8 -*-
"""
Translator module for handling metadata translation.
This module acts as a factory for creating translator instances.
"""
from typing import Optional, Any
from .base import Translator
from .google_translator import GoogleTranslator
from .deepl_translator import DeepLTranslator
from modules.output import get_output_manager

output_manager = get_output_manager()

def get_translator(provider: str, **kwargs: Any) -> Optional[Translator]:
    """
    Factory function to get a translator instance based on the provider name.

    Args:
        provider (str): The name of the translation provider (e.g., 'google', 'deepl').
        **kwargs: Additional keyword arguments for the translator's constructor.

    Returns:
        An instance of a Translator class, or None if the provider is unknown or fails to initialize.
    """
    provider_lower = provider.lower()
    if provider_lower == 'google':
        output_manager.info("Using Google Translate provider.")
        return GoogleTranslator()
    elif provider_lower == 'deepl':
        output_manager.info("Using DeepL provider.")
        if 'config' not in kwargs:
            output_manager.error("DeepL config is required but was not provided.")
            return None
        return DeepLTranslator(config=kwargs['config'])
    else:
        output_manager.warning(f"Unknown translation provider: '{provider}'. Translation will be disabled.")
        return None
