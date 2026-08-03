from unittest.mock import Mock

import pytest

from modules.komga_client import KomgaAPIError
from tests.test_komga_client import client, thumbnail


def test_library_and_paginated_series_mapping() -> None:
    instance = client()
    instance._make_request = Mock(
        side_effect=[
            [{"id": "library-1", "name": "Manga"}],
            {
                "content": [series_payload("series-1")],
                "last": False,
            },
            {
                "content": [series_payload("series-2")],
                "last": True,
            },
        ]
    )
    assert instance.get_libraries()[0].name == "Manga"
    assert [item.id for item in instance.get_series_in_library("library-1", "Manga")] == [
        "series-1",
        "series-2",
    ]


def series_payload(identifier: str) -> dict:
    return {
        "id": identifier,
        "libraryId": "library-1",
        "name": "Series",
        "booksCount": 0,
        "metadata": {
            "status": "ONGOING",
            "statusLock": False,
            "title": "Series",
            "titleLock": False,
            "summary": "",
            "summaryLock": False,
            "readingDirectionLock": False,
            "publisher": "",
            "publisherLock": False,
            "ageRatingLock": False,
            "language": "en",
            "languageLock": False,
            "genresLock": False,
            "tagsLock": False,
            "linksLock": False,
            "totalBookCountLock": False,
        },
    }


def book_payload() -> dict:
    return {
        "id": "book-1",
        "seriesId": "series-1",
        "name": "Book",
        "number": "1",
        "metadata": {
            "title": "Book",
            "titleLock": False,
            "summary": "",
            "summaryLock": False,
            "number": "1",
            "numberLock": False,
            "numberSort": 1.0,
            "numberSortLock": False,
            "releaseDateLock": False,
            "authorsLock": False,
            "tagsLock": False,
        },
    }


def test_books_updates_thumbnails_and_deletion() -> None:
    instance = client()
    instance._make_request = Mock(
        side_effect=[
            {"content": [book_payload()], "last": True},
            {},
            {},
            [thumbnail("one").model_dump(by_alias=True)],
            {},
        ]
    )
    assert instance.get_books_in_series("series-1", "Series")[0].id == "book-1"
    assert instance.update_series_metadata("series-1", {"summary": "x"}) is True
    assert instance.update_book_metadata("book-1", {"authors": []}) is True
    assert instance.get_series_thumbnails("series-1")[0].id == "one"
    assert instance.delete_series_thumbnail("series-1", "one") is True


@pytest.mark.parametrize(
    "method,args",
    [
        ("get_libraries", ()),
        ("get_series_thumbnails", ("series-1",)),
        ("update_series_metadata", ("series-1", {})),
        ("update_book_metadata", ("book-1", {})),
        ("delete_series_thumbnail", ("series-1", "thumb-1")),
    ],
)
def test_invalid_responses_raise(method: str, args: tuple) -> None:
    instance = client()
    instance._make_request = Mock(return_value=None)
    with pytest.raises(KomgaAPIError):
        getattr(instance, method)(*args)


def test_duplicate_thumbnail_cleanup_keeps_lowest_id() -> None:
    instance = client()
    instance.get_series_thumbnails = Mock(
        return_value=[thumbnail("b"), thumbnail("a"), thumbnail("unique", size=11)]
    )
    instance.delete_series_thumbnail = Mock(return_value=True)
    assert instance.clean_duplicate_thumbnails("series-1") == 1
    instance.delete_series_thumbnail.assert_called_once_with("series-1", "b")

