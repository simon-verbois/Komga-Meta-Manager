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

