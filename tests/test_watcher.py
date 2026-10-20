from unittest.mock import Mock

from modules.processor import watch_for_new_series


def test_excluded_series_is_marked_known(series, app_config) -> None:
    app_config.processing.exclude_series = [series.name]
    komga = Mock()
    komga.get_series_in_library.return_value = [series]
    provider = Mock()
    known = {"library-1": set()}

    result = watch_for_new_series(
        app_config,
        komga,
        {"Manga": "library-1"},
        known,
        provider,
        None,
    )

    assert result.found == 1
    assert result.processed == 0
    assert series.id in known["library-1"]
    provider.search.assert_not_called()


def test_watcher_ignores_disabled_library_in_old_targets(app_config) -> None:
    komga = Mock()
    komga.get_series_in_library.return_value = []
    known = {"library-1": set(), "library-2": set()}
    result = watch_for_new_series(
        app_config, komga, {"Manga": "library-1", "Comics": "library-2"}, known, Mock(), None,
    )
    assert result.processed == 0
    komga.get_series_in_library.assert_called_once_with("library-1", "Manga")


def test_watcher_does_not_initialize_when_all_libraries_disabled(app_config) -> None:
    from unittest.mock import patch
    from modules.main import initialize_watcher

    app_config.system.watcher.enabled = True
    app_config.komga.libraries = []
    with patch("modules.main.KomgaClient") as client, patch("modules.processor.get_providers") as providers:
        assert initialize_watcher(app_config).initialized is False
    client.assert_not_called()
    providers.assert_not_called()


def test_watcher_queues_only_new_eligible_series_and_does_not_write(series, app_config):
    from unittest.mock import patch

    known_series = series.model_copy(update={"id": "known"})
    excluded = series.model_copy(update={"id": "excluded", "name": "Excluded"})
    app_config.processing.exclude_series = ["Excluded"]
    komga = Mock()
    komga.get_series_in_library.return_value = [series, known_series, excluded]
    enqueue = Mock()
    known = {"library-1": {"known"}}
    provider = Mock()
    with patch("modules.processor.process_single_series") as process:
        result = watch_for_new_series(
            app_config, komga, {"Manga": "library-1"}, known, provider, None, enqueue_series=enqueue,
        )
    assert result.found == 2
    enqueue.assert_called_once_with([series.id])
    assert known["library-1"] == {"known", "excluded", series.id}
    process.assert_not_called()
    provider.save_cache.assert_not_called()


def test_watcher_keeps_new_series_unknown_when_enqueue_fails(series, app_config):
    import pytest

    komga = Mock()
    komga.get_series_in_library.return_value = [series]
    known = {"library-1": set()}
    with pytest.raises(ValueError, match="full"):
        watch_for_new_series(
            app_config, komga, {"Manga": "library-1"}, known, Mock(), None,
            enqueue_series=Mock(side_effect=ValueError("full")),
        )
    assert known["library-1"] == set()
