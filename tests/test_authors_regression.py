from unittest.mock import Mock

from modules.models import AniListMedia, KomgaBook
from modules.processor import _update_authors


def test_author_replacement_behavior_is_preserved(app_config) -> None:
    app_config.system.dry_run = False
    app_config.processing.overwrite_existing = True
    book = KomgaBook.model_validate(
        {
            "id": "book-1",
            "seriesId": "series-1",
            "name": "Volume 1",
            "number": "1",
            "metadata": {
                "title": "Volume 1",
                "titleLock": False,
                "summary": "",
                "summaryLock": False,
                "number": "1",
                "numberLock": False,
                "numberSort": 1.0,
                "numberSortLock": False,
                "releaseDate": None,
                "releaseDateLock": False,
                "authors": [{"name": "Existing Editor", "role": "editor"}],
                "authorsLock": False,
                "tags": [],
                "tagsLock": False,
            },
        }
    )
    match = AniListMedia.model_validate(
        {
            "id": 1,
            "title": {"romaji": "Example Manga"},
            "staff": {
                "edges": [
                    {
                        "role": "Story",
                        "node": {"name": {"full": "New Writer"}},
                    }
                ]
            },
        }
    )
    komga = Mock()
    komga.update_book_metadata.return_value = True

    _update_authors([book], match, app_config, [], komga)

    komga.update_book_metadata.assert_called_once_with(
        "book-1",
        {"authors": [{"name": "New Writer", "role": "writer"}]},
    )

