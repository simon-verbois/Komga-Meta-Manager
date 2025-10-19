# -*- coding: utf-8 -*-
"""
A simple time-aware file-based cache.
"""
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Version key for cache versioning
VERSION_KEY = "__version__"

class Cache:
    """
    A simple file-based cache that stores key-value pairs with timestamps
    and supports a Time-To-Live (TTL) for cache entries.
    """
    def __init__(self, cache_filename: str, cache_dir: Path, ttl_hours: int):
        self.cache_path = cache_dir / cache_filename
        self.ttl_seconds = ttl_hours * 3600
        self.cache: Dict[str, Dict[str, Any]] = {}

        # Read current application version
        version_path = Path("/app/VERSION")
        try:
            self.current_version = version_path.read_text().strip()
            logger.debug(f"Application version read: {self.current_version}")
        except FileNotFoundError:
            logger.warning("Application version file not found at /app/VERSION. Assuming 'unknown' version.")
            self.current_version = "unknown"
        except Exception as e:
            logger.error(f"Error reading version file: {e}. Assuming 'unknown' version.")
            self.current_version = "unknown"

        self._load_from_disk()

    def _load_from_disk(self):
        """Loads the cache from a JSON file if it exists."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    loaded_cache = json.load(f)

                # Check cache version compatibility
                cached_version = loaded_cache.get(VERSION_KEY, "unknown")
                if cached_version != self.current_version:
                    logger.warning(
                        f"Cache version mismatch: cache has version '{cached_version}', "
                        f"but application is version '{self.current_version}'. "
                        f"Clearing cache to prevent stale data usage."
                    )
                    self.cache = {}
                else:
                    self.cache = loaded_cache
                    logger.info(f"Successfully loaded cache for '{self.cache_path.name}' with {len(self.cache)} entries.")

            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load cache file at {self.cache_path}. A new one will be created. Error: {e}")
                self.cache = {}
        else:
            logger.info(f"Cache file not found at {self.cache_path}. A new one will be created.")

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves an item from the cache if it exists and has not expired.
        """
        entry = self.cache.get(key)
        if entry:
            age = time.time() - entry.get('timestamp', 0)
            if age < self.ttl_seconds:
                logger.debug(f"Cache HIT for key: '{key}'")
                return entry['value']
            else:
                logger.debug(f"Cache STALE for key: '{key}'. Entry has expired.")
                # Entry is stale, so we'll remove it
                self.remove(key)
        
        logger.debug(f"Cache MISS for key: '{key}'")
        return None

    def set(self, key: str, value: Any):
        """
        Adds or updates an item in the cache with the current timestamp.
        """
        self.cache[key] = {
            'timestamp': time.time(),
            'value': value
        }
        logger.debug(f"Cached value for key: '{key}'")

    def remove(self, key: str):
        """Removes an item from the cache."""
        if key in self.cache:
            del self.cache[key]
            logger.debug(f"Removed expired entry for key: '{key}'")

    def save_to_disk(self):
        """Saves the current cache state to a JSON file."""
        try:
            # Include current version in the cache
            cache_to_save = self.cache.copy()
            cache_to_save[VERSION_KEY] = self.current_version

            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_to_save, f, indent=2, ensure_ascii=False)
            logger.info(f"Successfully saved cache to {self.cache_path}.")
        except IOError as e:
            logger.error(f"Failed to save cache to {self.cache_path}. Error: {e}")

    def log_cache_summary(self):
        """Logs a summary of the cache's state."""
        # Exclude version key from cache summaries
        active_entries = {k: v for k, v in self.cache.items() if k != VERSION_KEY}
        total_entries = len(active_entries)

        if total_entries == 0:
            logger.info("Cache is currently empty.")
            return

        expired_count = 0
        current_time = time.time()
        for key, entry in active_entries.items():
            age = current_time - entry.get('timestamp', 0)
            if age >= self.ttl_seconds:
                expired_count += 1

        valid_count = total_entries - expired_count
        logger.info(f"Cache Summary: Total Entries={total_entries}, Valid={valid_count}, Expired={expired_count}")
