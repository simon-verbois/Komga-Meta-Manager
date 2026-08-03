from unittest.mock import Mock, patch

from modules.models import AniListMedia, KomgaLibrary
from modules.processor import ProcessingResult, process_libraries, process_single_series


def full_match() -> AniListMedia:
    return AniListMedia.model_validate(
        {
            "id": 42,
            "title": {"english": "Example Manga", "romaji": "Example Manga"},
            "description": "<b>A summary</b>",
            "status": "FINISHED",
            "genres": ["Drama"],
            "popularity": 1000,
            "averageScore": 90,
            "siteUrl": "https://anilist.co/manga/42",
            "coverImage": {"large": "https://images.test/42.jpg"},
        }
    )


def disable_authors(config) -> None:
    config.processing.update_fields.authors.writers = False
    config.processing.update_fields.authors.pencillers = False


def test_complete_dry_run_accumulates_metadata_without_mutation(series, app_config) -> None:
    disable_authors(app_config)
    provider = Mock()
    provider.search.return_value = [full_match()]
    komga = Mock()
    komga.update_series_poster.return_value = "would_upload"

    changes = process_single_series(series, app_config, komga, provider, None)

    assert any("Summary" in change for change in changes)
    assert any("Tags" in change for change in changes)
    assert any("Links" in change for change in changes)
    assert any("Cover Image" in change for change in changes)
    komga.update_series_metadata.assert_not_called()


def test_complete_write_run_updates_series_once(series, app_config) -> None:
    disable_authors(app_config)
    app_config.system.dry_run = False
    app_config.processing.overwrite_existing = True
    provider = Mock()
    provider.search.return_value = [full_match()]
    komga = Mock()
    komga.update_series_poster.return_value = "uploaded"
    komga.update_series_metadata.return_value = True

    process_single_series(series, app_config, komga, provider, None)

    payload = komga.update_series_metadata.call_args.args[1]
    assert payload["summary"] == "A summary"
    assert payload["genres"] == ["Drama"]
    assert payload["status"] == "ENDED"
    assert payload["tags"] == ["Favourite", "Score: 9.0"]
    assert payload["links"][-1]["url"] == "https://anilist.co/manga/42"


def test_no_match_does_not_mutate_series(series, app_config) -> None:
    disable_authors(app_config)
    provider = Mock()
    provider.search.return_value = []
    komga = Mock()
    assert process_single_series(series, app_config, komga, provider, None) is None
    komga.update_series_metadata.assert_not_called()


def test_process_libraries_reports_success_and_skips_exclusions(series, app_config) -> None:
    app_config.processing.exclude_series = ["Excluded"]
    excluded = series.model_copy(update={"id": "series-2", "name": "Excluded"})
    client = Mock()
    client.get_libraries.return_value = [KomgaLibrary(id="library-1", name="Manga")]
    client.get_series_in_library.return_value = [series, excluded]
    provider = Mock()

    with (
        patch("modules.processor.Path.mkdir"),
        patch("modules.processor.KomgaClient", return_value=client),
        patch("modules.processor.get_provider", return_value=provider),
        patch("modules.processor.process_single_series") as process,
    ):
        result = process_libraries(app_config)

    assert result == ProcessingResult(success=True, processed=1, skipped=1)
    process.assert_called_once()
    provider.save_cache.assert_called_once()


def test_process_libraries_reports_series_failure(series, app_config) -> None:
    client = Mock()
    client.get_libraries.return_value = [KomgaLibrary(id="library-1", name="Manga")]
    client.get_series_in_library.return_value = [series]
    provider = Mock()

    with (
        patch("modules.processor.Path.mkdir"),
        patch("modules.processor.KomgaClient", return_value=client),
        patch("modules.processor.get_provider", return_value=provider),
        patch("modules.processor.process_single_series", side_effect=RuntimeError("failed")),
    ):
        result = process_libraries(app_config)

    assert result.success is False
    assert result.failed == 1

