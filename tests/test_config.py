import pytest
import yaml
from pydantic import ValidationError

from modules.config import AppConfig, SchedulerConfig, load_config


def minimal_config() -> dict:
    return {
        "komga": {
            "url": "http://komga:25600",
            "api_key": "yaml-key",
            "libraries": ["Manga"],
        }
    }


def test_remove_defaults_are_all_disabled() -> None:
    config = AppConfig.model_validate(minimal_config())
    assert config.processing.remove_fields.model_dump() == {
        "summary": False,
        "publisher": False,
        "language": False,
        "reading_direction": False,
        "genres": False,
        "status": False,
        "authors": {"writers": False, "pencillers": False},
        "cover_image": False,
        "tags": {"score": False},
        "link": False,
    }


def test_partial_remove_config_remains_safe() -> None:
    data = minimal_config()
    data["processing"] = {"remove_fields": {"summary": True}}
    config = AppConfig.model_validate(data)
    assert config.processing.remove_fields.summary is True
    assert config.processing.remove_fields.language is False
    assert config.processing.remove_fields.reading_direction is False
    assert config.processing.remove_fields.genres is False
    assert config.processing.remove_fields.authors.writers is False
    assert config.processing.update_fields.summary is False


def test_publisher_removal_disables_publisher_update() -> None:
    data = minimal_config()
    data["processing"] = {"remove_fields": {"publisher": True}}

    config = AppConfig.model_validate(data)

    assert config.processing.remove_fields.publisher is True
    assert config.processing.update_fields.publisher is False


@pytest.mark.parametrize("run_at", ["24:00", "29:59", "9:00", "12:60", "invalid"])
def test_invalid_scheduler_times_are_rejected(run_at: str) -> None:
    with pytest.raises(ValidationError):
        SchedulerConfig(run_at=run_at)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("providers", 0, "min_score"), 101),
        (("providers", 0, "cache", "ttl_hours"), 0),
        (("system", "watcher", "polling_interval_minutes"), -1),
    ],
)
def test_numeric_bounds_are_enforced(path: tuple[str | int, ...], value: int) -> None:
    data = minimal_config()
    data["providers"] = [
        provider.model_dump() for provider in AppConfig.model_validate(data).providers
    ]
    cursor = data
    for part in path[:-1]:
        if isinstance(part, int):
            cursor = cursor[part]
        else:
            cursor = cursor.setdefault(part, {})
    cursor[path[-1]] = value
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_environment_secrets_override_yaml(tmp_path, monkeypatch) -> None:
    data = minimal_config()
    data["translation"] = {
        "enabled": True,
        "provider": "deepl",
        "target_language": "fr-fr",
        "deepl": {"api_key": "yaml-deepl"},
    }
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("KMM_KOMGA_API_KEY", "env-komga")
    monkeypatch.setenv("KMM_DEEPL_API_KEY", "env-deepl")

    config = load_config(str(path))

    assert config.komga.api_key == "env-komga"
    assert config.translation.deepl.api_key == "env-deepl"
    assert config.translation.target_language == "FR-FR"


def test_google_english_region_is_normalized() -> None:
    data = minimal_config()
    data["translation"] = {"provider": "google", "target_language": "EN-US"}
    assert AppConfig.model_validate(data).translation.target_language == "en"


@pytest.mark.parametrize("provider", ["anilist", "mangadex", "mangaupdates"])
def test_supported_metadata_providers(provider: str) -> None:
    data = minimal_config()
    data["providers"] = [
        {"name": name, "priority": priority, "preferred_language": "FR_fr"}
        for priority, name in enumerate(["anilist", "mangadex", "mangaupdates"], start=1)
    ]
    config = AppConfig.model_validate(data)
    selected = next(item for item in config.providers if item.name == provider)
    assert selected.preferred_language == "fr-fr"
    assert selected.allow_adult is False


def test_unknown_metadata_provider_is_rejected() -> None:
    data = minimal_config()
    data["providers"] = [
        {"name": "anilist", "priority": 1},
        {"name": "mangadex", "priority": 2},
        {"name": "unknown", "priority": 3},
    ]
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_all_providers_are_required_and_sorted_by_priority() -> None:
    data = minimal_config()
    data["providers"] = [
        {"name": "mangaupdates", "priority": 30},
        {"name": "anilist", "priority": 10},
        {"name": "mangadex", "priority": 20},
    ]
    config = AppConfig.model_validate(data)
    assert [provider.name for provider in config.providers] == ["anilist", "mangadex", "mangaupdates"]

    data["providers"].pop()
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)
