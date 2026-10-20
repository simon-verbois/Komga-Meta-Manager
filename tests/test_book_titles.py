"""Displayed title planning, safe templates and targeted API writes."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from modules.book_titles import book_title
from modules.config import BookTitleConfig
from modules.processor import process_single_series
from tests.test_libraries import book


@pytest.mark.parametrize(
    ("mode", "number", "padding", "template", "expected"),
    [
        ("off", "1", 0, "{series}", None),
        ("volume", "001", 0, "{series}", "Volume 1"),
        ("volume", "1", 2, "{series}", "Volume 01"),
        ("chapter", "12.5", 3, "{series}", "Chapter 012.5"),
        ("chapter", "0", 3, "{series}", "Chapter 000"),
        ("volume", "Special", 2, "{series}", "Volume Special"),
        ("volume", " ", 0, "{series}", None),
        ("series", "", 0, "{number}", "Example Manga"),
        ("custom", "1", 2, "{series} - Volume {number}", "Example Manga - Volume 01"),
        ("custom", "1", 2, "Tome {number}", "Tome 01"),
        ("custom", "1", 3, "Chapitre {number}", "Chapitre 001"),
        ("custom", "", 2, "{series} {number}", None),
        ("custom", "1", 0, "{{Special}} {number}", "{Special} 1"),
    ],
)
def test_render_titles_from_explicit_metadata(series, mode, number, padding, template, expected):
    item = book("one")
    item.metadata.number = number
    settings = BookTitleConfig(mode=mode, padding=padding, template=template)
    assert book_title(item, series, settings) == expected


@pytest.mark.parametrize(
    "template",
    [
        "",
        " ",
        "{title}",
        "{series.__class__}",
        "{series[0]}",
        "{number:03}",
        "{number!r}",
        "{",
        "line\nbreak",
        "x" * 201,
    ],
)
def test_templates_reject_unsupported_or_unstable_expressions(template):
    with pytest.raises(ValidationError):
        BookTitleConfig(mode="custom", template=template)


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("force_unlock", [True, False])
def test_naming_obeys_locks_targeting_and_simulation(app_config, series, dry_run, force_unlock):
    app_config.system.dry_run = dry_run
    app_config.processing.force_unlock = force_unlock
    app_config.processing.book_titles = BookTitleConfig(mode="chapter", padding=3)
    app_config.processing.update_fields = type(app_config.processing.update_fields)(
        **{name: False for name in ("summary", "publisher", "genres", "status", "cover_image", "link")},
        authors={"writers": False, "pencillers": False},
    )
    first, locked, unchanged, missing, excluded, foreign = [
        book(name) for name in ("one", "locked", "unchanged", "missing", "excluded", "foreign")
    ]
    locked.metadata.title_lock = True
    unchanged.metadata.title = "Chapter 001"
    missing.metadata.number = ""
    foreign.series_id = "another-series"
    remote, provider = Mock(), Mock()
    remote.get_books_in_series.return_value = [first, locked, unchanged, missing, excluded, foreign]

    changes = process_single_series(
        series,
        app_config,
        remote,
        provider,
        None,
        book_ids=["one", "locked", "unchanged", "missing", "foreign"],
    )

    provider.search.assert_not_called()
    if dry_run:
        remote.update_book_metadata.assert_not_called()
        assert len(changes) == 1 + force_unlock
    else:
        assert remote.update_book_metadata.call_count == 1 + force_unlock
        assert remote.update_book_metadata.call_args_list[0].args == ("one", {"title": "Chapter 001"})
        assert all(call.args[0] in {"one", "locked"} for call in remote.update_book_metadata.call_args_list)
    remote.update_series_metadata.assert_not_called()


def test_missing_series_title_is_not_replaced_with_a_filename(series):
    series.metadata.title = ""
    assert book_title(book("one"), series, BookTitleConfig(mode="series")) is None
