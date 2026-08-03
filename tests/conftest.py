from unittest.mock import Mock

import pytest

from modules.config import AppConfig
from modules.models import KomgaSeries


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "komga": {
                "url": "http://komga:25600",
                "api_key": "secret",
                "libraries": ["Manga"],
            },
            "system": {"dry_run": True},
            "processing": {
                "update_fields": {
                    "summary": True,
                    "genres": True,
                    "status": True,
                    "authors": {"writers": True, "pencillers": True},
                    "cover_image": True,
                    "tags": {"score": True},
                    "link": True,
                },
            },
        }
    )


@pytest.fixture
def series() -> KomgaSeries:
    return KomgaSeries.model_validate(
        {
            "id": "series-1",
            "libraryId": "library-1",
            "name": "Example Manga",
            "booksCount": 1,
            "metadata": {
                "status": "ONGOING",
                "statusLock": False,
                "title": "Example Manga",
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
                "genres": ["Action"],
                "genresLock": False,
                "tags": ["Favourite"],
                "tagsLock": False,
                "links": [{"label": "Official", "url": "https://example.test"}],
                "linksLock": False,
                "totalBookCount": None,
                "totalBookCountLock": False,
            },
        }
    )


@pytest.fixture
def komga_mock() -> Mock:
    return Mock()

