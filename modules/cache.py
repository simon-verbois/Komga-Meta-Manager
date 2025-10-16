# -*- coding: utf-8 -*-
"""
A simple time-aware file-based cache.
"""
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional
from modules.output import get_output_manager

output_manager = get_output_manager()

class Cache:
    """
    A simple file-based cache that stores key-value pairs with timestamps
    and supports a Time-To-Live (TTL) for cache entries.
    For providers, it also supports version checking to invalidate cache
    on version upgrades.
    """
    def __init__(self, cache_name: str, cache_dir: Path, ttl_hours: int, is_provider_cache: bool = False, current_version: str = None):
        # Configure cache filename based on type
        if is_provider_cache:
            self.cache_path = cache_dir / f"metadata_provider_{cache_name}_cache.json"
        else:
            self.cache_path = cache_dir / f"{cache_name}_cache.json"

        self.ttl_seconds = ttl_hours * 3600
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.is_provider_cache = is_provider_cache
        self.current_version = current_version
        self._load_from_disk()

    def _load_from_disk(self):
        """Loads the cache from a JSON file if it exists."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Check version compatibility for provider caches
                if self.is_provider_cache and self.current_version:
                    metadata = data.get('_metadata', {})
                    cached_version = metadata.get('version')

                    if cached_version != self.current_version:
                        output_manager.warning(f"Cache version mismatch: cached={cached_version}, current={self.current_version}")
                        output_manager.warning(f"Cache at {self.cache_path} will be invalidated due to version upgrade.")
                        # Remove the old cache file
                        self.cache_path.unlink(missing_ok=True)
                        self.cache = {}
                        return
                    else:
                        output_manager.info(f"Cache version check passed: {cached_version}")

                    # Remove metadata from cache data to get pure cache entries
                    data.pop('_metadata', None)

                self.cache = data
                output_manager.info(f"Successfully loaded cache for '{self.cache_path.name}' with {len(self.cache)} entries.")
            except (json.JSONDecodeError, IOError) as e:
                output_manager.error(f"Failed to load cache file at {self.cache_path}. A new one will be created. Error: {e}")
                self.cache = {}
        else:
            output_manager.info(f"Cache file not found at {self.cache_path}. A new one will be created.")

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves an item from the cache if it exists and has not expired.
        """
        entry = self.cache.get(key)
        if entry:
            age = time.time() - entry.get('timestamp', 0)
            if age < self.ttl_seconds:
                output_manager.debug(f"Cache HIT for key: '{key}'")
                return entry['value']
            else:
                output_manager.debug(f"Cache STALE for key: '{key}'. Entry has expired.")
                # Entry is stale, so we'll remove it
                self.remove(key)

        output_manager.debug(f"Cache MISS for key: '{key}'")
        return None

    def set(self, key: str, value: Any):
        """
        Adds or updates an item in the cache with the current timestamp.
        """
        self.cache[key] = {
            'timestamp': time.time(),
            'value': value
        }
        output_manager.debug(f"Cached value for key: '{key}'")

    def remove(self, key: str):
        """Removes an item from the cache."""
        if key in self.cache:
            del self.cache[key]
            output_manager.debug(f"Removed expired entry for key: '{key}'")

    def save_to_disk(self):
        """Saves the current cache state to a JSON file."""
        try:
            # Prepare data to save
            data_to_save = self.cache.copy()

            # Add metadata for provider caches
            if self.is_provider_cache and self.current_version:
                data_to_save['_metadata'] = {
                    'version': self.current_version,
                    'created_at': time.time()
                }

            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            output_manager.info(f"Successfully saved cache to {self.cache_path}.")
        except IOError as e:
            output_manager.error(f"Failed to save cache to {self.cache_path}. Error: {e}")

    def log_cache_summary(self):
        """Logs a summary of the cache's state."""
        total_entries = len(self.cache)
        if total_entries == 0:
            output_manager.info("Cache is currently empty.")
            return

        expired_count = 0
        current_time = time.time()
        for key, entry in self.cache.items():
            age = current_time - entry.get('timestamp', 0)
            if age >= self.ttl_seconds:
                expired_count += 1

        valid_count = total_entries - expired_count
        output_manager.info(f"Cache Summary: Total Entries={total_entries}, Valid={valid_count}, Expired={expired_count}")
