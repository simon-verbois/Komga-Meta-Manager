# -*- coding: utf-8 -*-
"""
Abstract base class for all translator implementations.
"""
from abc import ABC, abstractmethod


def base_language(language: str | None) -> str | None:
    """Normalize a language code to its lowercase base language."""
    if not language:
        return None
    normalized = language.strip().replace('_', '-').lower().split('-', 1)[0]
    return normalized or None


def languages_match(source_language: str | None, target_language: str) -> bool:
    """Return whether two language codes share the same base language."""
    source = base_language(source_language)
    target = base_language(target_language)
    return bool(source and source == target)


class Translator(ABC):
    """Abstract base class for a text translator."""

    @abstractmethod
    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        """
        Translates a given text to the target language.

        Args:
            text (str): The text to be translated.
            target_language (str): The ISO 639-1 code for the target language (e.g., 'fr').
            source_language (str | None): Known language supplied by the metadata provider.

        Returns:
            The translated text.
        """
        pass
