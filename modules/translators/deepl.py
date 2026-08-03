# -*- coding: utf-8 -*-
"""
Translator implementation using the DeepL API.
"""
import logging
import json
import backoff
from pathlib import Path
import deepl
from .base import Translator, base_language, languages_match
from ..config import DeepLConfig
from modules.constants import CACHE_SAVE_INTERVAL
from modules.cache_naming import get_translation_cache_filename

logger = logging.getLogger(__name__)

class DeepLTranslator(Translator):
    """A translator using the official DeepL API."""

    def __init__(self, config: DeepLConfig):
        try:
            self.translator = deepl.Translator(config.api_key)
            self.cache_path = Path("/config/cache") / get_translation_cache_filename("deepl")
            self.cache = self._load_cache_from_disk()
            self.cache_hits = 0
            self.cache_misses = 0
            self.unsaved_changes = 0
            logger.info("DeepL Translator initialized successfully with persistent cache.")
        except Exception as e:
            logger.error(f"Failed to initialize DeepL Translator: {e}")
            self.translator = None
            self.cache_path = Path("/config/cache") / get_translation_cache_filename("deepl")
            self.cache = {}
            self.unsaved_changes = 0

    def _load_cache_from_disk(self) -> dict:
        """Loads the translation cache from a JSON file."""
        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                logger.info(f"Loaded {len(cache_data)} translations from persistent cache.")
                return cache_data
        except FileNotFoundError:
            logger.info("Persistent translation cache not found. A new one will be created.")
            return {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load persistent cache file. Starting with an empty cache: {e}")
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
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to temporary file first for atomic writes
            temp_path = self.cache_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=4, ensure_ascii=False, sort_keys=True)

            # Atomic rename
            temp_path.replace(self.cache_path)

            logger.info(f"Successfully saved {len(self.cache)} translations to persistent cache.")
            self.unsaved_changes = 0

        except IOError as e:
            logger.error(f"Could not write to persistent cache file at {self.cache_path}: {e}")
            # Don't reset unsaved_changes on failure so we try again later

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

    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        """
        Translates text, using a multi-layered cache approach.
        """
        if not self.translator or not text:
            return text

        if languages_match(source_language, target_language):
            logger.debug(
                "Skipping translation because source language '%s' already matches target language '%s'.",
                source_language,
                target_language,
            )
            return text

        # Layer 1: Persistent Cache
        source = base_language(source_language) or "auto"
        cache_key = f"v2:{source}:{target_language}:{text}"
        if cache_key in self.cache:
            self.cache_hits += 1
            logger.debug(f"Cache hit for '{text}' -> '{self.cache[cache_key]}'")
            return self.cache[cache_key]

        # Layer 2: API Call
        self.cache_misses += 1
        logger.debug(f"Cache miss for '{text}'. Calling translation API.")
        try:
            translated_text = self._translate_with_retry(text, target_language, source_language)
            self.cache[cache_key] = translated_text
            self.unsaved_changes += 1
            self._autosave_cache()  # Periodic save
            return translated_text
        except Exception as e:
            logger.error(f"Translation failed permanently for '{text}' after multiple retries: {e}")
            return text

    def _should_save_cache(self) -> bool:
        """Check if the cache should be saved based on the number of unsaved changes."""
        return self.unsaved_changes >= CACHE_SAVE_INTERVAL

    def _autosave_cache(self):
        """Automatically save cache if enough changes have accumulated."""
        if self._should_save_cache():
            logger.debug(f"Auto-saving cache after {self.unsaved_changes} changes")
            self.save_cache_to_disk()

    def is_not_retryable(e):
        return False

    @backoff.on_exception(backoff.expo,
                          deepl.DeepLException,
                          max_tries=3,
                          giveup=is_not_retryable,
                          logger=logger)
    def _translate_with_retry(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        """
        Protected method that performs the translation and is decorated for retries.
        """
        kwargs = {"target_lang": target_language}
        if source := base_language(source_language):
            kwargs["source_lang"] = source.upper()
        result = self.translator.translate_text(text, **kwargs)
        return result.text
