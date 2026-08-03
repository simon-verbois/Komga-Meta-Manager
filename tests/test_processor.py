from unittest.mock import Mock, call

from modules.config import TranslationConfig
from modules.models import MetadataRecord
from modules.processor import (
    CoverImageHandler,
    GenericFieldHandler,
    _process_links_update,
    _process_links_remove,
    _process_tags_update,
    choose_best_match,
)


def media(media_id: int, *, title: str, native: str | None = None, adult: bool = False) -> MetadataRecord:
    return MetadataRecord.model_validate(
        {
            "provider": "anilist",
            "external_id": str(media_id),
            "titles": [value for value in (title, native) if value],
            "popularity": 100,
            "adult": adult,
            "site_url": f"https://anilist.co/manga/{media_id}",
            "score": 85,
            "cover_urls": ["https://images.test/cover.jpg"],
        }
    )


def test_matching_uses_native_title_and_excludes_adult() -> None:
    adult = media(1, title="Example Manga", adult=True)
    native = media(2, title="Unrelated", native="Example Manga")
    assert choose_best_match("Example Manga", [adult, native], 80).external_id == "2"


def test_matching_can_allow_adult_and_uses_popularity_as_tie_breaker() -> None:
    less_popular = media(1, title="Example Manga", adult=True)
    less_popular.popularity = 10
    popular = media(2, title="Example Manga", adult=True)
    popular.popularity = 1000
    assert choose_best_match(
        "Example Manga", [less_popular, popular], 80, allow_adult=True
    ).external_id == "2"


def test_matching_does_not_treat_short_title_as_long_title_substring() -> None:
    wrong_match = media(
        1,
        title="Boushoku no Berserk: Ore dake Level to Iu Gainen o Toppa Suru",
    )

    assert choose_best_match("Berserk", [wrong_match], 80) is None


def test_matching_logs_when_an_exact_adult_match_is_excluded(caplog) -> None:
    exact_adult = media(1, title="Berserk", adult=True)
    wrong_match = media(2, title="Berserk II", adult=False)

    with caplog.at_level("WARNING"):
        match = choose_best_match("Berserk", [exact_adult, wrong_match], 80)

    assert match is None
    assert "Excluded exact adult title match(es) 'Berserk'" in caplog.text
    assert "Fuzzy alternatives will not be used" in caplog.text


def test_matching_remains_fuzzy_for_typographical_errors() -> None:
    candidate = media(1, title="Berserk")

    assert choose_best_match("Berzerk", [candidate], 80).external_id == "1"


def test_matching_tolerates_reordered_title_words() -> None:
    candidate = media(1, title="Apothecary Diaries The")

    assert choose_best_match("The Apothecary Diaries", [candidate], 80).external_id == "1"


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
    assert payload["links"][1] == {"label": "AniList", "url": "https://anilist.co/manga/7"}

    series.metadata.links = payload["links"]
    assert _process_links_update({}, series, match, app_config) is None


def test_all_matched_provider_links_are_synchronized(series, app_config) -> None:
    match = media(7, title="Example Manga").model_copy(update={
        "provider_links": {
            "anilist": "https://anilist.co/manga/7",
            "mangadex": "https://mangadex.org/title/md-7",
            "mangaupdates": "https://www.mangaupdates.com/series/mu-7",
        },
    })
    payload = {}

    change = _process_links_update(payload, series, match, app_config)

    assert change == "- Links: synchronized AniList, MangaDex, MangaUpdates"
    assert payload["links"] == [
        {"label": "Official", "url": "https://example.test"},
        {"label": "AniList", "url": "https://anilist.co/manga/7"},
        {"label": "MangaDex", "url": "https://mangadex.org/title/md-7"},
        {
            "label": "MangaUpdates",
            "url": "https://www.mangaupdates.com/series/mu-7",
        },
    ]


def test_link_removal_removes_all_managed_providers_and_preserves_third_party(
    series, app_config
) -> None:
    app_config.processing.remove_fields.link = True
    series.metadata.links = [
        {"label": "Official", "url": "https://example.test"},
        {"label": "Anilist", "url": "https://anilist.co/manga/1"},
        {"label": "MangaDex", "url": "https://mangadex.org/title/2"},
        {"label": "MANGAUPDATES", "url": "https://mangaupdates.com/series/3"},
    ]
    payload = {}

    change = _process_links_remove(payload, series, None, app_config)

    assert payload["links"] == [{"label": "Official", "url": "https://example.test"}]
    assert change == "- Links: removed 3 provider link(s)."


def test_empty_removal_is_a_noop(series, app_config) -> None:
    app_config.processing.remove_fields.summary = True
    series.metadata.summary = ""
    handler = GenericFieldHandler("summary", "remove", "summary")
    payload = {}
    assert handler.process(payload, series, None, app_config, None) is None
    assert payload == {}


def test_language_removal_honors_lock_policy(series, app_config) -> None:
    app_config.processing.remove_fields.language = True
    handler = GenericFieldHandler("language", "remove", "language")

    series.metadata.language_lock = True
    assert handler.process({}, series, None, app_config, None) is None

    app_config.processing.force_unlock = True
    payload = {}
    change = handler.process(payload, series, None, app_config, None)

    assert payload == {"language": "", "languageLock": False}
    assert change == "- Language: Will be removed."


def test_reading_direction_removal_uses_komga_field_names(series, app_config) -> None:
    app_config.processing.remove_fields.reading_direction = True
    app_config.processing.force_unlock = True
    series.metadata.reading_direction = "RIGHT_TO_LEFT"
    series.metadata.reading_direction_lock = True
    handler = GenericFieldHandler("reading_direction", "remove", "reading_direction")
    payload = {}

    change = handler.process(payload, series, None, app_config, None)

    assert payload == {"readingDirection": None, "readingDirectionLock": False}
    assert change == "- Reading Direction: Will be removed."


def test_publisher_update_and_removal_honor_scalar_field_policy(series, app_config) -> None:
    match = media(1, title="Example Manga").model_copy(update={"publisher": "Shueisha"})
    update_handler = GenericFieldHandler("publisher", "update", "publisher")

    payload = {}
    assert update_handler.process(payload, series, match, app_config, None)
    assert payload == {"publisher": "Shueisha"}

    series.metadata.publisher = "Existing Publisher"
    assert update_handler.process({}, series, match, app_config, None) is None

    app_config.processing.remove_fields.publisher = True
    remove_handler = GenericFieldHandler("publisher", "remove", "publisher")
    payload = {}
    assert remove_handler.process(payload, series, None, app_config, None)
    assert payload == {"publisher": ""}


def test_publisher_lock_requires_force_unlock(series, app_config) -> None:
    series.metadata.publisher_lock = True
    match = media(1, title="Example Manga").model_copy(update={"publisher": "Shueisha"})
    handler = GenericFieldHandler("publisher", "update", "publisher")

    assert handler.process({}, series, match, app_config, None) is None

    app_config.processing.force_unlock = True
    payload = {}
    assert handler.process(payload, series, match, app_config, None)
    assert payload == {"publisher": "Shueisha", "publisherLock": False}


def test_processor_passes_known_metadata_languages_to_translator(series, app_config) -> None:
    app_config.translation = TranslationConfig(provider="google", target_language="fr")
    app_config.processing.overwrite_existing = True
    match = media(1, title="Example Manga").model_copy(update={
        "description": "Résumé français",
        "description_language": "fr-FR",
        "genres": ["Drame", "Fantasy"],
        "genre_languages": {"Drame": "fr", "Fantasy": "en"},
    })
    translator = Mock()
    translator.translate.side_effect = lambda text, target, source_language=None: text

    GenericFieldHandler("summary", "update", "summary").process(
        {}, series, match, app_config, translator
    )
    GenericFieldHandler("genres", "update", "genres").process(
        {}, series, match, app_config, translator
    )

    assert translator.translate.call_args_list == [
        call("Résumé français", "fr", source_language="fr-FR"),
        call("Drame", "fr", source_language="fr"),
        call("Fantasy", "fr", source_language="en"),
    ]


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
