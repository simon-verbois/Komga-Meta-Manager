# -*- coding: utf-8 -*-
"""
Translator implementation using the DeepL API.
"""
import logging
import json
import backoff
import deepl
import yaml
from .base import Translator
from ..config import DeepLConfig

logger = logging.getLogger(__name__)
TRANSLATIONS_CONFIG_PATH = "/config/translations.yml"
TRANSLATION_CACHE_PATH = "/config/cache/translation_cache.json"

def load_manual_translations() -> dict:
    """Loads the manual translations YAML file if it exists."""
    try:
        with open(TRANSLATIONS_CONFIG_PATH, "r", encoding="utf-8") as f:
            translations = yaml.safe_load(f)
            if isinstance(translations, dict):
                logger.info(f"Successfully loaded manual translations from {TRANSLATIONS_CONFIG_PATH}")
                return translations
            logger.warning("Manual translations file is not a valid dictionary. Ignoring.")
    except FileNotFoundError:
        logger.info(f"No manual translations file found at '{TRANSLATIONS_CONFIG_PATH}', skipping.")
    except Exception as e:
        logger.error(f"Failed to load or parse manual translations file: {e}")
    return {}

MANUAL_TRANSLATIONS = load_manual_translations()

class DeepLTranslator(Translator):
    """A translator using the official DeepL API."""

    def __init__(self, config: DeepLConfig):
        try:
            self.translator = deepl.Translator(config.api_key)
            self.cache = self._load_cache_from_disk()
            self.cache_hits = 0
            self.cache_misses = 0
            logger.info("DeepL Translator initialized successfully with persistent cache.")
        except Exception as e:
            logger.error(f"Failed to initialize DeepL Translator: {e}")
            self.translator = None
            self.cache = {}

    def _load_cache_from_disk(self) -> dict:
        """Loads the translation cache from a JSON file."""
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
        """Saves the in-memory translation cache to a JSON file."""
        if not self.cache:
            logger.info("Translation cache is empty. Nothing to save.")
            return
        
        try:
            with open(TRANSLATION_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=4, ensure_ascii=False, sort_keys=True)
                logger.info(f"Successfully saved {len(self.cache)} translations to persistent cache.")
        except IOError as e:
            logger.error(f"Could not write to persistent cache file: {e}")

    def log_cache_summary(self):
        """Logs the summary of cache usage for the current session."""
        total_lookups = self.cache_hits + self.cache_misses
        if total_lookups > 0:
            hit_ratio = (self.cache_hits / total_lookups) * 100
            logger.info(
                f"Translation Cache Summary (this session): "
                f"{self.cache_hits} hits, {self.cache_misses} misses "
                f"({hit_ratio:.2f}% hit ratio). "
                f"Avoided {self.cache_hits} API calls."
            )

    def translate(self, text: str, target_language: str) -> str:
        """
        Translates text, using a multi-layered cache approach.
        """
        if not self.translator or not text:
            return text

        # Layer 1: Manual Translations
        if target_language in MANUAL_TRANSLATIONS and text in MANUAL_TRANSLATIONS[target_language]:
            manual_translation = MANUAL_TRANSLATIONS[target_language][text]
            logger.debug(f"Using manual translation for '{text}' -> '{manual_translation}'")
            return manual_translation

        # Layer 2: Persistent Cache
        cache_key = f"{target_language}:{text}"
        if cache_key in self.cache:
            self.cache_hits += 1
            logger.debug(f"Cache hit for '{text}' -> '{self.cache[cache_key]}'")
            return self.cache[cache_key]

        # Layer 3: API Call
        self.cache_misses += 1
        logger.debug(f"Cache miss for '{text}'. Calling translation API.")
        try:
            translated_text = self._translate_with_retry(text, target_language)
            self.cache[cache_key] = translated_text
            return translated_text
        except Exception as e:
            logger.error(f"Translation failed permanently for '{text}' after multiple retries: {e}")
            return text

    @backoff.on_exception(backoff.expo, deepl.DeepLException, max_tries=3, logger=logger)
    def _translate_with_retry(self, text: str, target_language: str) -> str:
        """
        Protected method that performs the translation and is decorated for retries.
        """
        result = self.translator.translate_text(text, target_lang=target_language)
        return result.text
