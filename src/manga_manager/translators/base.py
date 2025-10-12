# Path: src/manga_manager/translators/base.py

# -*- coding: utf-8 -*-
"""
Abstract base class for all translator implementations.
"""
from abc import ABC, abstractmethod

class Translator(ABC):
    """Abstract base class for a text translator."""

    @abstractmethod
    def translate(self, text: str, target_language: str) -> str:
        """
        Translates a given text to the target language.

        Args:
            text (str): The text to be translated.
            target_language (str): The ISO 639-1 code for the target language (e.g., 'fr').

        Returns:
            The translated text.
        """
        pass

