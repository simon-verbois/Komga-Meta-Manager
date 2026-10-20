"""Explicit numbering plans, including volume zero and decimal chapters."""

import pytest

from modules.book_numbering import numbering_version, plan_book_order, plan_numbering
from modules.config import BookTitleConfig
from modules.manual_metadata import ManualEditError
from tests.test_libraries import book


def test_volume_zero_updates_numbers_sort_and_library_titles_without_mutation(series):
    books = [book("zero"), book("one")]
    books[1].metadata.number = "2"
    settings = BookTitleConfig(mode="custom", template="Tome {number}", padding=2)
    patches = plan_numbering(series, books, settings, {"zero": "0", "one": "1"})
    assert patches[0] == {"entity": "books", "id": "zero", "payload": {
        "number": "0", "numberLock": True, "numberSort": 0.0, "numberSortLock": True,
        "title": "Tome 00", "titleLock": True,
    }}
    assert patches[1]["payload"]["title"] == "Tome 01"
    assert books[0].metadata.number == "1" and books[0].metadata.title == "zero"


@pytest.mark.parametrize("number", ["-1", "", "NaN", "inf", "1e2", "2/3", "1000000", "999999.1", "1.1234", "Special"])
def test_invalid_number_rejects_entire_plan(series, number):
    with pytest.raises(ManualEditError, match="numbering.invalid"):
        plan_numbering(series, [book("a")], BookTitleConfig(), {"a": number})


def test_decimal_chapters_and_unchanged_specials(series):
    books = [book("chapter"), book("special")]
    books[1].metadata.number = "Special"
    settings = BookTitleConfig(mode="chapter")
    patches = plan_numbering(series, books, settings, {"chapter": "0.5", "special": "Special"})
    assert len(patches) == 1
    assert patches[0]["payload"]["numberSort"] == 0.5
    assert patches[0]["payload"]["title"] == "Chapter 0.5"
    assert plan_numbering(series, books, settings, {"chapter": "1", "special": "Special"}) == []


def test_disabled_naming_keeps_titles_and_membership_is_exact(series):
    assert "title" not in plan_numbering(series, [book("a")], BookTitleConfig(), {"a": "0"})[0]["payload"]
    for numbers in ({}, {"foreign": "0"}, {"a": "0", "foreign": "1"}):
        with pytest.raises(ManualEditError, match="numbering.conflict"):
            plan_numbering(series, [book("a")], BookTitleConfig(), numbers)


def test_version_changes_with_books_locks_and_rules(series):
    books = [book("a")]
    settings = BookTitleConfig(mode="volume")
    version = numbering_version(series, books, settings)
    books[0].metadata.number_lock = True
    assert numbering_version(series, books, settings) != version
    assert numbering_version(series, [], settings) != version
    assert numbering_version(series, [book("a")], BookTitleConfig()) != version


def test_drag_order_reuses_visible_number_slots_and_keeps_other_books(series):
    books = [book("a"), book("hidden"), book("b"), book("c")]
    for item, number in zip(books, ["0", "1", "2.5", "4"]):
        item.metadata.number = number
        item.metadata.number_sort = float(number)
    patches = plan_book_order(series, books, BookTitleConfig(mode="volume"), ["c", "a", "b"])
    assert {patch["id"]: patch["payload"]["number"] for patch in patches} == {"a": "2.5", "b": "4", "c": "0"}
    assert patches[-1]["payload"]["title"] == "Volume 0"
    assert all(patch["id"] != "hidden" for patch in patches)
    assert books[0].metadata.number == "0"


@pytest.mark.parametrize("numbers,order", [
    (["1", "01"], ["b", "a"]), (["Special", "2"], ["b", "a"]),
    (["1", "2"], ["a", "a"]), (["1", "2"], ["foreign", "b"]),
])
def test_drag_rejects_ambiguous_numbers_and_invalid_membership(series, numbers, order):
    books = [book("a"), book("b")]
    for item, number in zip(books, numbers):
        item.metadata.number = number
    with pytest.raises(ManualEditError):
        plan_book_order(series, books, BookTitleConfig(), order)
