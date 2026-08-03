from unittest.mock import Mock

from modules.providers.anilist import AnilistProvider
from modules.providers.mangadex import MangadexProvider
from modules.providers.mangaupdates import MangaupdatesProvider
from modules.processor import choose_best_match


def test_anilist_search_and_detail_are_normalized(tmp_path) -> None:
    provider = AnilistProvider(tmp_path, 1)
    provider._execute = Mock(side_effect=[
        {"Page": {"media": [{
            "id": 7,
            "title": {"english": "Example Manga", "romaji": "Example"},
            "synonyms": ["Example Alias"],
            "isAdult": False,
            "popularity": 123,
            "startDate": {"year": 2020},
            "format": "MANGA",
        }]}},
        {"Media": {
            "id": 7,
            "title": {"english": "Example Manga", "romaji": "Example"},
            "synonyms": ["Example Alias"],
            "description": "Summary",
            "status": "FINISHED",
            "genres": ["Drama"],
            "popularity": 123,
            "averageScore": 88,
            "siteUrl": "https://anilist.co/manga/7",
            "isAdult": False,
            "format": "MANGA",
            "startDate": {"year": 2020},
            "staff": {"edges": [
                {"role": "Story", "node": {"name": {"full": "Writer"}}},
                {"role": "Art", "node": {"name": {"full": "Artist"}}},
            ]},
            "coverImage": {"large": "https://images.test/7.jpg"},
        }},
    ])

    candidate = provider.search("Example Alias")[0]
    record = provider.get_metadata(candidate)

    assert candidate.external_id == "7"
    assert candidate.titles == ["Example Manga", "Example", "Example Alias"]
    assert record.status == "ENDED"
    assert record.score == 88
    assert [creator.role for creator in record.creators] == ["writer", "penciller"]


def mangadex_item() -> dict:
    return {
        "id": "md-1",
        "attributes": {
            "title": {"en": "Example Manga"},
            "altTitles": [{"ja-ro": "Example Alias"}],
            "description": {"fr": "Résumé français", "en": "English summary"},
            "originalLanguage": "ja",
            "contentRating": "safe",
            "publicationDemographic": "seinen",
            "status": "completed",
            "year": 2020,
            "tags": [
                {"attributes": {"group": "genre", "name": {"en": "Drama"}}},
                {"attributes": {"group": "theme", "name": {"en": "School"}}},
            ],
        },
        "relationships": [
            {"type": "author", "attributes": {"name": "Writer"}},
            {"type": "artist", "attributes": {"name": "Artist"}},
            {"type": "cover_art", "attributes": {"fileName": "cover.jpg"}},
        ],
    }


def test_mangadex_search_and_detail_are_normalized(tmp_path) -> None:
    provider = MangadexProvider(tmp_path, 1, preferred_language="fr")
    provider._request_json = Mock(side_effect=[
        {"data": [mangadex_item()]},
        {"statistics": {"md-1": {"follows": 321}}},
        {"data": mangadex_item()},
        {"statistics": {"md-1": {"follows": 321, "rating": {"bayesian": 8.25}}}},
    ])

    candidate = provider.search("Example Manga")[0]
    record = provider.get_metadata(candidate)

    assert candidate.titles == ["Example Manga", "Example Alias"]
    assert candidate.popularity == 321
    assert record.description == "Résumé français"
    assert record.description_language == "fr"
    assert record.status == "ENDED"
    assert record.genres == ["Drama"]
    assert record.genre_languages == {"Drama": "en"}
    assert record.score == 82.5
    assert {(creator.name, creator.role) for creator in record.creators} == {
        ("Writer", "writer"),
        ("Artist", "penciller"),
    }
    assert record.cover_urls == ["https://uploads.mangadex.org/covers/md-1/cover.jpg.512.jpg"]


def test_mangadex_search_matches_an_alternative_title(tmp_path) -> None:
    item = mangadex_item()
    item["attributes"]["title"] = {"ja-ro": "Tongari Boushi no Atelier"}
    item["attributes"]["altTitles"] = [
        {"fr": "L'Atelier des Sorciers"},
        {"en": "Witch Hat Atelier"},
    ]
    provider = MangadexProvider(tmp_path, 1, preferred_language="fr")
    provider._request_json = Mock(side_effect=[
        {"data": [item]},
        {"statistics": {"md-1": {"follows": 321}}},
    ])

    candidates = provider.search("L'Atelier des Sorciers")
    match = choose_best_match("L'Atelier des Sorciers", candidates)

    assert match is not None
    assert match.external_id == "md-1"
    assert "L'Atelier des Sorciers" in match.titles


def test_mangadex_adult_ratings_are_filtered_flags(tmp_path) -> None:
    item = mangadex_item()
    item["attributes"]["contentRating"] = "pornographic"
    provider = MangadexProvider(tmp_path, 1)
    provider._request_json = Mock(side_effect=[
        {"data": [item]},
        {"statistics": {"md-1": {"follows": 1}}},
    ])
    assert provider.search("Example")[0].adult is True


def test_mangaupdates_search_and_detail_are_normalized(tmp_path) -> None:
    search_record = {
        "series_id": 42,
        "title": "Example Manga",
        "genres": [{"genre": "Drama"}],
        "rating_votes": 99,
        "year": "2020",
        "type": "Manga",
    }
    detail = {
        **search_record,
        "associated": [{"title": "Example Alias"}],
        "description": "A **summary** with [source](https://example.test).",
        "bayesian_rating": 8.1,
        "status": "12 Volumes (Ongoing)",
        "completed": False,
        "url": "https://www.mangaupdates.com/series/example",
        "authors": [
            {"name": "Writer", "type": "Author"},
            {"name": "Artist", "type": "Artist"},
        ],
        "publishers": [
            {"publisher_name": "English Licensee", "type": "English"},
            {"publisher_name": "Original Publisher", "type": "Original"},
            {"publisher_name": "Original Publisher", "type": "original"},
        ],
        "image": {"url": {"original": "https://images.test/cover.jpg"}},
    }
    provider = MangaupdatesProvider(tmp_path, 1)
    provider._request_json = Mock(side_effect=[
        {"results": [{"record": search_record, "hit_title": "Example Alias"}]},
        detail,
    ])

    candidate = provider.search("Example Alias")[0]
    record = provider.get_metadata(candidate)

    assert candidate.titles == ["Example Manga", "Example Alias"]
    assert record.status == "ONGOING"
    assert record.score == 81
    assert record.titles == ["Example Manga", "Example Alias"]
    assert record.publisher == "Original Publisher"
    assert record.cover_urls == ["https://images.test/cover.jpg"]
    assert [creator.role for creator in record.creators] == ["writer", "penciller"]


def test_mangaupdates_ignores_translated_publishers_when_original_is_missing(tmp_path) -> None:
    provider = MangaupdatesProvider(tmp_path, 1)
    provider._request_json = Mock(return_value={
        "series_id": 42,
        "title": "Example Manga",
        "publishers": [{"publisher_name": "English Licensee", "type": "English"}],
    })

    assert provider.get_by_id("42").publisher is None


def test_mangaupdates_adult_genres_are_detected(tmp_path) -> None:
    provider = MangaupdatesProvider(tmp_path, 1)
    provider._request_json = Mock(return_value={
        "results": [{
            "record": {"series_id": 1, "title": "Explicit", "genres": [{"genre": "Smut"}]},
            "hit_title": "Explicit",
        }]
    })
    assert provider.search("Explicit")[0].adult is True
