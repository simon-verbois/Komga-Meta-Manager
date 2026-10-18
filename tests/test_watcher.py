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
    with patch("modules.main.KomgaClient") as client, patch("modules.main.get_providers") as providers:
        assert initialize_watcher(app_config).initialized is False
    client.assert_not_called()
    providers.assert_not_called()

