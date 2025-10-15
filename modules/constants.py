# -*- coding: utf-8 -*-
"""
Centralized constants for the Manga Manager application.
"""
from pathlib import Path

# API and Network Configuration
HTTP_CONNECT_TIMEOUT = 5  # seconds
HTTP_READ_TIMEOUT = 30  # seconds
HTTP_TIMEOUTS = (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)

# Retry Configuration
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2  # Exponential backoff: 1s, 2s, 4s

# AniList API
ANILIST_API_URL = "https://graphql.anilist.co"
ANILIST_SEARCH_RESULTS_PER_PAGE = 5
ANILIST_MIN_SCORE_DEFAULT = 80

# Komga API
KOMGA_API_V1_PATH = "/api/v1"
KOMGA_SERIES_PAGE_SIZE = 100

# Cache Configuration
CACHE_TTL_HOURS_DEFAULT = 168  # 7 days
CACHE_SAVE_INTERVAL = 50  # Save cache every N additions
TRANSLATION_CACHE_FILENAME = "translation_cache.json"
METADATA_CACHE_FILENAME = "metadata_cache.json"

# File Paths
CONFIG_DIR = Path("/config")
CACHE_DIR = CONFIG_DIR / "cache"
CONFIG_FILE = CONFIG_DIR / "config.yml"
TRANSLATIONS_CONFIG_FILE = CONFIG_DIR / "translations.yml"
TRANSLATION_CACHE_PATH = CACHE_DIR / TRANSLATION_CACHE_FILENAME

# AniList Status Mapping
ANILIST_STATUS_TO_KOMGA = {
    'RELEASING': 'ONGOING',
    'FINISHED': 'ENDED',
    'CANCELLED': 'ABANDONED',
    'HIATUS': 'HIATUS'
}

# Logging Configuration
LOG_FORMAT = '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Circuit Breaker Defaults - Technical resilience settings
# These are internal technical parameters, not user configuration
CIRCUIT_BREAKER_DEFAULTS = {
    'komga': {
        'failure_threshold': 5,
        'recovery_timeout': 60,
        'success_threshold': 3
    },
    'anilist': {
        'failure_threshold': 5,
        'recovery_timeout': 60,
        'success_threshold': 3
    },
    'translation': {
        'failure_threshold': 3,  # More aggressive - translations are often rate-limited
        'recovery_timeout': 30,  # Shorter recovery - translation services recover faster
        'success_threshold': 2
    }
}
