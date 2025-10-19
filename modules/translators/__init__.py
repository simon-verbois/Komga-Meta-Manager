# -*- coding: utf-8 -*-
"""
Translator module for handling metadata translation.
This module acts as a factory for creating translator instances.
"""
import logging
from typing import Optional, Any
from .base import Translator
from .google import GoogleTranslator
from .deepl import DeepLTranslator
from modules.utils import log_frame

logger = logging.getLogger(__name__)

def get_translator(provider: str, **kwargs: Any) -> Optional[Translator]:
    """
    Factory function to get a translator instance based on the provider name.

    Args:
        provider (str): The name of the translation provider (e.g., 'google', 'deepl').
        **kwargs: Additional keyword arguments for the translator's constructor.

    Returns:
        An instance of a Translator class, or None if the provider is unknown or fails to initialize.
    """
    logging.info("|                                                                                                    |")
    logging.info("|====================================================================================================|")
    log_frame("Translation Configurations", 'center')
    logging.info("|====================================================================================================|")
    provider_lower = provider.lower()
    if provider_lower == 'google':
        logger.info("Using Google Translate provider.")
        return GoogleTranslator()
    elif provider_lower == 'deepl':
        logger.info("Using DeepL provider.")
        if 'config' not in kwargs:
            logger.error("DeepL config is required but was not provided.")
            return None
        return DeepLTranslator(config=kwargs['config'])
    else:
        logger.warning(f"Unknown translation provider: '{provider}'. Translation will be disabled.")
        return None
