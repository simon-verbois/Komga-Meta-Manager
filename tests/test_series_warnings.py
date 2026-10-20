"""Conservative numbering checks across content types."""

from copy import deepcopy

import pytest

from modules.series_warnings import numbering_warnings


def item(identifier, title, number):
    return {"id": identifier, "metadata": {"title": title, "number": number}}


def test_repeated_tomes_and_title_number_conflicts_do_not_mutate_inputs():
    books = [item("a", "Dr Stone T01", "1"), item("b", "Dr Stone T01", "2")]
    original = deepcopy(books)
    warnings = numbering_warnings(books)
    assert [warning["code"] for warning in warnings] == ["duplicate_title_number", "title_number_mismatch"]
    assert [book["id"] for book in warnings[0]["books"]] == ["a", "b"]
    assert [book["id"] for book in warnings[1]["books"]] == ["b"]
    assert books == original


@pytest.mark.parametrize("title", ["Tome 02", "Volume 2", "Vol. 002", "Chapter 2", "Ch. 2", "Chapitre 02"])
def test_explicit_title_numbers_support_volume_and_chapter_labels(title):
    assert numbering_warnings([item("a", title, "1")])[0]["code"] == "title_number_mismatch"


def test_equivalent_numeric_values_are_duplicates_without_title_conflicts():
    warnings = numbering_warnings([item("a", "Volume 10", "010"), item("b", "Volume 010.0", "10.0")])
    assert [warning["code"] for warning in warnings] == ["duplicate_number", "duplicate_title_number"]
    assert all(warning["number"] == "10" for warning in warnings)


@pytest.mark.parametrize("title,number", [
    ("1984", "1"), ("Series 2026", "2"), ("Special", "Special"),
    ("Volumes 1–2", "1"), ("Vol. 1-2", "1"), ("Omnibus", ""),
    ("Volume 01", "1.0"), ("Chapter 12.5", "12.50"), ("Volume 0", "0"),
])
def test_arbitrary_digits_ranges_specials_and_matching_numbers_are_not_conflicts(title, number):
    assert numbering_warnings([item("a", title, number)]) == []


def test_plain_repeated_titles_missing_numbers_and_numbering_gaps_are_allowed():
    assert numbering_warnings([
        item("a", "Collected essays", ""), item("b", "Collected essays", ""),
        item("c", "Chapter 1", "1"), item("d", "Chapter 5", "5"),
    ]) == []


def test_volume_zero_followed_by_release_tags_is_a_number_conflict():
    books = [item("zero", "Jujutsu Kaisen T00 (Akutami) (2020) [Manga FR]", "1")]
    assert numbering_warnings(books)[0]["code"] == "title_number_mismatch"
    assert numbering_warnings([item("zero", books[0]["metadata"]["title"], "0")]) == []
