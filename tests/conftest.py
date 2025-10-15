# -*- coding: utf-8 -*-
"""
Pytest configuration and shared fixtures.
"""
import pytest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import json
import os

@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)

@pytest.fixture
def mock_komga_config():
    """Mock KomgaConfig for testing."""
    config = Mock()
    config.url = "https://komga.example.com"
    config.api_key = "test-api-key"
    config.libraries = ["Manga", "Comics"]
    config.verify_ssl = True
    return config

@pytest.fixture
def mock_anilist_response():
    """Sample AniList GraphQL response for testing."""
    return {
        "Page": {
            "media": [
                {
                    "id": 12345,
                    "title": {
                        "romaji": "Test Manga",
                        "english": "Test Manga English",
                        "native": "テストマンガ"
                    },
                    "description": "A test manga description",
                    "status": "FINISHED",
                    "genres": ["Action", "Adventure"],
                    "tags": [{"name": "Shounen", "rank": 95}],
                    "popularity": 1000,
                    "isAdult": False,
                    "coverImage": {
                        "extraLarge": "https://example.com/cover-xl.jpg",
                        "large": "https://example.com/cover-l.jpg",
                        "medium": "https://example.com/cover-m.jpg"
                    }
                }
            ]
        }
    }

@pytest.fixture
def mock_komga_api_response():
    """Mock Komga API response."""
    return [
        {
            "id": "lib1",
            "name": "Manga Library"
        },
        {
            "id": "lib2",
            "name": "Comics Library"
        }
    ]

@pytest.fixture
def mock_series_response():
    """Mock Komga series response."""
    return {
        "content": [
            {
                "id": "series1",
                "libraryId": "lib1",
                "name": "Test Series",
                "booksCount": 10,
                "metadata": {
                    "status": "",
                    "statusLock": False,
                    "title": "Test Series",
                    "titleLock": False,
                    "summary": "",
                    "summaryLock": False,
                    "readingDirection": None,
                    "readingDirectionLock": False,
                    "publisher": "",
                    "publisherLock": False,
                    "ageRating": None,
                    "ageRatingLock": False,
                    "language": "en",
                    "languageLock": False,
                    "genres": [],
                    "genresLock": False,
                    "tags": [],
                    "tagsLock": False,
                    "totalBookCount": None,
                    "totalBookCountLock": False
                }
            }
        ],
        "last": True
    }

@pytest.fixture
def mock_translation_cache(temp_dir):
    """Create a mock translation cache file."""
    cache_file = temp_dir / "translation_cache.json"
    cache_data = {
        "Hello": "Bonjour",
        "World": "Monde"
    }
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f)
    return cache_file

@pytest.fixture
def mock_translations_yml(temp_dir):
    """Create a mock translations.yml file."""
    translations_file = temp_dir / "translations.yml"
    translations_data = {
        "fr": {
            "Action": "Action",
            "Romance": "Romance"
        }
    }
    with open(translations_file, 'w', encoding='utf-8') as f:
        json.dump(translations_data, f)
    return translations_file

class MockResponse:
    """Mock requests.Response for testing."""

    def __init__(self, json_data=None, status_code=200, raise_for_status=None):
        self.json_data = json_data
        self.status_code = status_code
        self._raise_for_status = raise_for_status
        self.content = b"" if json_data is None else json.dumps(json_data).encode('utf-8')
        self.headers = {'Content-Type': 'application/json'}

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self._raise_for_status:
            raise self._raise_for_status

@pytest.fixture
def mock_requests_session():
    """Mock requests.Session for testing."""
    with patch('requests.Session') as mock_session:
        yield mock_session

@pytest.fixture
def mock_googletrans_translator():
    """Mock googletrans Translator."""
    with patch('googletrans.Translator') as mock_translator:
        mock_instance = Mock()
        mock_instance.translate.return_value = Mock(text="Traduction")
        mock_translator.return_value = mock_instance
        yield mock_instance
