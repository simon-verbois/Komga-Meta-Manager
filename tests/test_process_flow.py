from unittest.mock import Mock, patch

from modules.models import MetadataRecord, KomgaLibrary
from modules.processor import ProcessingResult, _merge_missing_metadata, process_libraries, process_single_series
from modules.providers import ConfiguredProvider, ProviderChain


def full_match() -> MetadataRecord:
    return MetadataRecord.model_validate(
        {
            "provider": "anilist",
            "external_id": "42",
            "titles": ["Example Manga"],
            "description": "<b>A summary</b>",
            "status": "ENDED",
            "genres": ["Drama"],
            "popularity": 1000,
            "score": 90,
            "site_url": "https://anilist.co/manga/42",
            "cover_urls": ["https://images.test/42.jpg"],
        }
    )


def disable_authors(config) -> None:
    config.processing.update_fields.authors.writers = False
    config.processing.update_fields.authors.pencillers = False


def test_metadata_fallback_preserves_field_languages() -> None:
    primary = MetadataRecord(
        provider="anilist",
        external_id="1",
        titles=["Example"],
        site_url="https://anilist.co/manga/1",
    )
    fallback = MetadataRecord(
        provider="mangadex",
        external_id="2",
        titles=["Example"],
        description="Résumé",
        description_language="fr",
        genres=["Drame"],
        genre_languages={"Drame": "fr"},
        site_url="https://mangadex.org/title/2",
    )

    merged = _merge_missing_metadata(primary, fallback)

    assert merged.description_language == "fr"
    assert merged.genre_languages == {"Drame": "fr"}
    assert merged.provider_links == {
        "anilist": "https://anilist.co/manga/1",
        "mangadex": "https://mangadex.org/title/2",
    }


def test_complete_dry_run_accumulates_metadata_without_mutation(series, app_config) -> None:
    disable_authors(app_config)
    provider = Mock()
    provider.search.return_value = [full_match().model_copy(update={"publisher": "Shueisha"})]
    provider.get_metadata.side_effect = lambda candidate: candidate
    komga = Mock()
    komga.update_series_poster.return_value = "would_upload"

    changes = process_single_series(series, app_config, komga, provider, None)

    assert "- Summary: Will be updated." in changes
    assert "- Publisher: Set to Shueisha" in changes
    assert all("Summary: Set to" not in change for change in changes)
    assert any("Tags" in change for change in changes)
    assert any("Links" in change for change in changes)
    assert any("Cover Image" in change for change in changes)
    komga.update_series_metadata.assert_not_called()


def test_complete_write_run_updates_series_once(series, app_config) -> None:
    disable_authors(app_config)
    app_config.system.dry_run = False
    app_config.processing.overwrite_existing = True
    provider = Mock()
    provider.search.return_value = [full_match().model_copy(update={"publisher": "Shueisha"})]
    provider.get_metadata.side_effect = lambda candidate: candidate
    komga = Mock()
    komga.update_series_poster.return_value = "uploaded"
    komga.update_series_metadata.return_value = True

    process_single_series(series, app_config, komga, provider, None)

    payload = komga.update_series_metadata.call_args.args[1]
    assert payload["summary"] == "A summary"
    assert payload["publisher"] == "Shueisha"
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


def test_metadata_title_is_used_for_search(series, app_config) -> None:
    disable_authors(app_config)
    series.metadata.title = "Edited Title"
    provider = Mock()
    provider.search.return_value = []

    process_single_series(series, app_config, Mock(), provider, None)

    provider.search.assert_called_once_with("Edited Title")


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
        patch("modules.processor.get_providers", return_value=provider),
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
        patch("modules.processor.get_providers", return_value=provider),
        patch("modules.processor.process_single_series", side_effect=RuntimeError("failed")),
    ):
        result = process_libraries(app_config)

    assert result.success is False
    assert result.failed == 1


def test_lower_priority_provider_fills_only_missing_metadata(series, app_config) -> None:
    disable_authors(app_config)
    app_config.system.dry_run = False
    app_config.processing.overwrite_existing = True

    primary_record = MetadataRecord(
        provider="anilist",
        external_id="1",
        titles=["Example Manga"],
        description="Primary summary",
        site_url="https://anilist.co/manga/1",
    )
    fallback_record = full_match().model_copy(update={
        "provider": "mangadex",
        "external_id": "md-1",
        "description": "Fallback summary",
        "site_url": "https://mangadex.org/title/md-1",
    })
    primary = Mock()
    primary.search.return_value = [primary_record]
    primary.get_metadata.return_value = primary_record
    fallback = Mock()
    fallback.search.return_value = [fallback_record]
    fallback.get_metadata.return_value = fallback_record
    publisher_record = MetadataRecord(
        provider="mangaupdates",
        external_id="mu-1",
        titles=["Example Manga"],
        publisher="Original Publisher",
        site_url="https://www.mangaupdates.com/series/mu-1",
    )
    publisher_provider = Mock()
    publisher_provider.search.return_value = [publisher_record]
    publisher_provider.get_metadata.return_value = publisher_record
    chain = ProviderChain([
        ConfiguredProvider(app_config.providers[0], primary),
        ConfiguredProvider(app_config.providers[1], fallback),
        ConfiguredProvider(app_config.providers[2], publisher_provider),
    ])
    komga = Mock()
    komga.update_series_poster.return_value = "uploaded"
    komga.update_series_metadata.return_value = True

    process_single_series(series, app_config, komga, chain, None)

    payload = komga.update_series_metadata.call_args.args[1]
    assert payload["summary"] == "Primary summary"
    assert payload["publisher"] == "Original Publisher"
    assert payload["genres"] == ["Drama"]
    assert payload["links"] == [
        {"label": "Official", "url": "https://example.test"},
        {"label": "AniList", "url": "https://anilist.co/manga/1"},
        {"label": "MangaDex", "url": "https://mangadex.org/title/md-1"},
        {
            "label": "MangaUpdates",
            "url": "https://www.mangaupdates.com/series/mu-1",
        },
    ]
    publisher_provider.search.assert_called_once_with("Example Manga")
