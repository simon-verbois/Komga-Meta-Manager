# -*- coding: utf-8 -*-
"""
Translator implementation using the googletrans library.
"""
import logging
import backoff
import yaml
import json
from pathlib import Path
from googletrans import Translator as GoogletransTranslator, LANGUAGES
from .base import Translator
from manga_manager.constants import (
    TRANSLATIONS_CONFIG_FILE,
    TRANSLATION_CACHE_PATH,
    CACHE_SAVE_INTERVAL
)

logger = logging.getLogger(__name__)

def load_manual_translations() -> dict:
    """
    Load manual translations from the YAML configuration file.

    Reads the translations.yml file in the config directory to provide
    user-defined translations that take precedence over automatic translation.

    Returns:
        A dictionary mapping language codes to translation mappings.
        Returns an empty dict if the file doesn't exist or fails to load.

    Examples:
        File content:
        fr:
          "Action": "Action"
          "Romance": "Romance"

        Returns: {'fr': {'Action': 'Action', 'Romance': 'Romance'}}
    """
    try:
        with open(TRANSLATIONS_CONFIG_FILE, "r", encoding="utf-8") as f:
            translations = yaml.safe_load(f)
            if isinstance(translations, dict):
                logger.info(f"Successfully loaded manual translations from {TRANSLATIONS_CONFIG_FILE}")
                return translations
            logger.warning("Manual translations file is not a valid dictionary. Ignoring.")
    except FileNotFoundError:
        logger.info(f"No manual translations file found at '{TRANSLATIONS_CONFIG_FILE}', skipping.")
    except Exception as e:
        logger.error(f"Failed to load or parse manual translations file: {e}")
    return {}

MANUAL_TRANSLATIONS = load_manual_translations()

def is_not_retryable(e):
    return False

class GoogleTranslator(Translator):
    """
    A translator using the unofficial Google Translate API with smart caching.

    This translator implements a two-tier caching strategy:
    1. Manual overrides from translations.yml (highest priority)
    2. Automatic translations from Google Translate (with persistent disk cache)

    The disk cache is automatically saved periodically to prevent data loss,
    and provides significant API call savings for repeated translations.

    Attributes:
        translator: The Google Translate client instance
        cache: In-memory translation cache mapping text -> translated_text
        cache_hits: Number of cache hits in this session
        cache_misses: Number of cache misses in this session
        unsaved_changes: Counter of cache changes since last save
    """

    def __init__(self):
        try:
            self.translator = GoogletransTranslator()
            self.cache = self._load_cache_from_disk()
            self.cache_hits = 0
            self.cache_misses = 0
            self.unsaved_changes = 0
            logger.info("Google Translator initialized successfully with persistent cache.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Translator: {e}")
            self.translator = None
            self.cache = {}
            self.unsaved_changes = 0

    def _load_cache_from_disk(self) -> dict:
        """
        Load the translation cache from a JSON file.

        Returns:
            Dictionary containing previously cached translations.
            Returns empty dict if file doesn't exist or is corrupted.
        """
        try:
            with open(TRANSLATION_CACHE_PATH, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                logger.info(f"Loaded {len(cache_data)} translations from persistent cache.")
                return cache_data
        except FileNotFoundError:
            logger.info("Persistent translation cache not found. A new one will be created.")
            return {}
        except json.JSONDecodeError:
            logger.warning("Could not decode persistent cache file. Starting with an empty cache.")
            return {}

    def save_cache_to_disk(self):
        """
        Save the in-memory translation cache to a JSON file.

        This method provides atomic writes by writing to a temporary file
        first, then renaming it to avoid corruption if the process is interrupted.

        Note:
            Resets the unsaved_changes counter to 0 after successful save.
        """
        if not self.cache:
            logger.info("Translation cache is empty. Nothing to save.")
            return
        
        try:
            # Ensure cache directory exists
            TRANSLATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

            # Write to temporary file first for atomic writes
            temp_path = TRANSLATION_CACHE_PATH.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=4, ensure_ascii=False, sort_keys=True)

            # Atomic rename
            temp_path.replace(TRANSLATION_CACHE_PATH)

            logger.info(f"Successfully saved {len(self.cache)} translations to persistent cache.")
            self.unsaved_changes = 0

        except IOError as e:
            logger.error(f"Could not write to persistent cache file at {TRANSLATION_CACHE_PATH}: {e}")
            # Don't reset unsaved_changes on failure so we try again later

    def _should_save_cache(self) -> bool:
        """Check if the cache should be saved based on the number of unsaved changes."""
        return self.unsaved_changes >= CACHE_SAVE_INTERVAL

    def _autosave_cache(self):
        """Automatically save cache if enough changes have accumulated."""
        if self._should_save_cache():
            logger.debug(f"Auto-saving cache after {self.unsaved_changes} changes")
            self.save_cache_to_disk()

    def log_cache_summary(self):
        """
        Log comprehensive cache usage statistics for the current session.

        Provides insights into cache effectiveness including hit ratio,
        total translations performed, and API calls avoided.
        """
        total_lookups = self.cache_hits + self.cache_misses
        if total_lookups > 0:
            hit_ratio = (self.cache_hits / total_lookups) * 100
            logger.info(
                f"Translation Cache Summary (this session): "
                f"{self.cache_hits} hits, {self.cache_misses} misses "
                f"({hit_ratio:.2f}% hit ratio). "
                f"Avoided {self.cache_hits} API calls. "
                f"Total cache size: {len(self.cache)} entries. "
                f"Unsaved changes: {self.unsaved_changes}."
            )
        else:
            logger.info("No translation lookups performed in this session.")

    def translate(self, text: str, target_language: str) -> str:
        """
        Translate text using multi-layered caching strategy.

        Translation priority:
        1. Manual overrides from translations.yml (if available)
        2. Persistent cache from disk (if previously translated)
        3. Google Translate API (with automatic caching)

        Args:
            text: The text to translate
            target_language: Target language code (e.g., 'fr', 'en')

        Returns:
            Translated text, or original text if translation fails or is not needed

        Examples:
            >>> translator.translate("Hello", "fr")
            "Bonjour"

            >>> translator.translate("Hello", "fr")  # Subsequent call
            "Bonjour"  # Served from cache
        """
        if not self.translator or not text:
            return text

        # Check manual translations first (highest priority)
        if target_language in MANUAL_TRANSLATIONS and text in MANUAL_TRANSLATIONS[target_language]:
            manual_translation = MANUAL_TRANSLATIONS[target_language][text]
            logger.debug(f"Using manual translation for '{text}' -> '{manual_translation}'")
            return manual_translation

        # Validate language support
        if target_language not in LANGUAGES:
            logger.warning(f"Language '{target_language}' is not supported by Google Translate. Returning original text.")
            return text
            
        # Check persistent cache
        if text in self.cache:
            self.cache_hits += 1
            logger.debug(f"Cache hit for '{text}' -> '{self.cache[text]}'")
            return self.cache[text]

        # Cache miss - call API
        self.cache_misses += 1
        logger.debug(f"Cache miss for '{text}'. Calling translation API.")
        
        try:
            translated_text = self._translate_with_retry(text, target_language)
            self.cache[text] = translated_text
            self.unsaved_changes += 1
            self._autosave_cache()  # Periodic save
            return translated_text
        except Exception as e:
            logger.error(f"Translation failed permanently for '{text}' after multiple retries: {e}")
            return text

    @backoff.on_exception(backoff.expo,
                          Exception,
                          max_tries=3,
                          giveup=is_not_retryable,
                          logger=logger)
    def _translate_with_retry(self, text: str, target_language: str) -> str:
        """
        Protected method that performs the translation and is decorated for retries.
        """
        translated = self.translator.translate(text, dest=target_language)
        if translated is None or translated.text is None:
            raise TypeError("googletrans returned None object")
        return translated.text
