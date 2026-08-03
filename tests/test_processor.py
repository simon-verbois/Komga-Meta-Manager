from modules.models import AniListMedia
from modules.processor import (
    CoverImageHandler,
    GenericFieldHandler,
    _process_links_update,
    _process_tags_update,
    choose_best_match,
)


def media(media_id: int, *, title: str, native: str | None = None, adult: bool = False) -> AniListMedia:
    return AniListMedia.model_validate(
        {
            "id": media_id,
            "title": {"romaji": title, "english": None, "native": native},
            "popularity": 100,
            "isAdult": adult,
            "siteUrl": f"https://anilist.co/manga/{media_id}",
            "averageScore": 85,
            "coverImage": {"large": "https://images.test/cover.jpg"},
        }
    )


def test_matching_uses_native_title_and_excludes_adult() -> None:
    adult = media(1, title="Example Manga", adult=True)
    native = media(2, title="Unrelated", native="Example Manga")
    assert choose_best_match("Example Manga", [adult, native], 80).id == 2


def test_score_tag_is_additive_and_idempotent(series, app_config) -> None:
    payload = {}
    match = media(1, title="Example Manga")
    assert _process_tags_update(payload, series, match, app_config)
    assert payload["tags"] == ["Favourite", "Score: 8.5"]

    series.metadata.tags = set(payload["tags"])
    assert _process_tags_update({}, series, match, app_config) is None


def test_anilist_link_preserves_third_party_links_and_is_idempotent(series, app_config) -> None:
    payload = {}
    match = media(7, title="Example Manga")
    assert _process_links_update(payload, series, match, app_config)
    assert payload["links"][0]["label"] == "Official"
    assert payload["links"][1] == {"label": "Anilist", "url": "https://anilist.co/manga/7"}

    series.metadata.links = payload["links"]
    assert _process_links_update({}, series, match, app_config) is None


def test_empty_removal_is_a_noop(series, app_config) -> None:
    app_config.processing.remove_fields.summary = True
    series.metadata.summary = ""
    handler = GenericFieldHandler("summary", "remove", "summary")
    payload = {}
    assert handler.process(payload, series, None, app_config, None) is None
    assert payload == {}


def test_cover_handler_delegates_safe_policy(series, app_config, komga_mock) -> None:
    komga_mock.update_series_poster.return_value = "would_upload"
    handler = CoverImageHandler()
    change = handler.process({}, series, media(1, title="Example Manga"), app_config, None, komga_mock)
    assert "Will be updated" in change
    komga_mock.update_series_poster.assert_called_once_with(
        series.id,
        "https://images.test/cover.jpg",
        overwrite_existing=False,
        dry_run=True,
    )
