"""MangaDex metadata provider."""
from pathlib import Path
from typing import List

from modules.constants import MANGADEX_API_URL, MANGADEX_COVER_URL, METADATA_SEARCH_RESULTS
from modules.models import MetadataCandidate, MetadataCreator, MetadataRecord
from .base import MetadataProviderError
from .http import HttpMetadataProvider

STATUS_MAP = {
    "ongoing": "ONGOING",
    "completed": "ENDED",
    "cancelled": "ABANDONED",
    "hiatus": "HIATUS",
}


def _unique(values) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class MangadexProvider(HttpMetadataProvider):
    def __init__(self, cache_dir: Path, cache_ttl_hours: int, preferred_language: str = "en"):
        super().__init__(cache_dir, cache_ttl_hours)
        self.preferred_language = preferred_language

    @staticmethod
    def _titles(item: dict) -> list[str]:
        attributes = item.get("attributes") or {}
        values = list((attributes.get("title") or {}).values())
        for alternate in attributes.get("altTitles") or []:
            values.extend(alternate.values())
        return _unique(values)

    @staticmethod
    def _adult(item: dict) -> bool:
        return (item.get("attributes") or {}).get("contentRating") in {"erotica", "pornographic"}

    def _perform_search(self, search_term: str) -> List[MetadataCandidate]:
        params = [
            ("title", search_term),
            ("limit", str(METADATA_SEARCH_RESULTS)),
            ("order[relevance]", "desc"),
            ("includes[]", "author"),
            ("includes[]", "artist"),
            ("includes[]", "cover_art"),
        ]
        payload = self._request_json("GET", f"{MANGADEX_API_URL}/manga", params=params)
        items = payload.get("data") or []
        ids = [item.get("id") for item in items if item.get("id")]
        follows = {}
        if ids:
            stats_params = [("manga[]", identifier) for identifier in ids]
            stats = self._request_json("GET", f"{MANGADEX_API_URL}/statistics/manga", params=stats_params)
            follows = {
                key: (value or {}).get("follows", 0)
                for key, value in (stats.get("statistics") or {}).items()
            }
        candidates = []
        for item in items:
            titles = self._titles(item)
            if not titles:
                continue
            attributes = item.get("attributes") or {}
            candidates.append(MetadataCandidate(
                provider="mangadex",
                external_id=item["id"],
                titles=titles,
                adult=self._adult(item),
                popularity=follows.get(item["id"], 0),
                year=str(attributes.get("year") or "") or None,
                media_type=attributes.get("publicationDemographic") or "manga",
            ))
        return candidates

    def _localized_value(self, values: dict, *fallback_languages: str | None) -> tuple[str | None, str | None]:
        for language in fallback_languages:
            if language and values.get(language):
                return values[language], language
        return next(((value, language) for language, value in values.items() if value), (None, None))

    def _description(self, attributes: dict) -> tuple[str | None, str | None]:
        descriptions = attributes.get("description") or {}
        original = attributes.get("originalLanguage")
        preferred_base = self.preferred_language.split("-", 1)[0]
        return self._localized_value(descriptions, self.preferred_language, preferred_base, "en", original)

    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        params = [("includes[]", value) for value in ("author", "artist", "cover_art")]
        payload = self._request_json("GET", f"{MANGADEX_API_URL}/manga/{external_id}", params=params)
        item = payload.get("data")
        if not item:
            raise MetadataProviderError(f"MangaDex manga {external_id} was not found")
        attributes = item.get("attributes") or {}
        creators = []
        cover_urls = []
        for relation in item.get("relationships") or []:
            relation_type = relation.get("type")
            relation_attributes = relation.get("attributes") or {}
            if relation_type in {"author", "artist"} and relation_attributes.get("name"):
                creators.append(MetadataCreator(
                    name=relation_attributes["name"],
                    role="writer" if relation_type == "author" else "penciller",
                ))
            if relation_type == "cover_art" and relation_attributes.get("fileName"):
                cover_urls.append(
                    f"{MANGADEX_COVER_URL}/{external_id}/{relation_attributes['fileName']}.512.jpg"
                )
        stats_payload = self._request_json("GET", f"{MANGADEX_API_URL}/statistics/manga/{external_id}")
        statistics = (stats_payload.get("statistics") or {}).get(external_id) or {}
        rating = statistics.get("rating") or {}
        genres = []
        genre_languages = {}
        for tag in attributes.get("tags") or []:
            tag_attributes = tag.get("attributes") or {}
            if tag_attributes.get("group") != "genre":
                continue
            names = tag_attributes.get("name") or {}
            preferred_base = self.preferred_language.split("-", 1)[0]
            name, language = self._localized_value(names, self.preferred_language, preferred_base, "en")
            if name:
                genres.append(name)
                if language:
                    genre_languages[name] = language
        description, description_language = self._description(attributes)
        return MetadataRecord(
            provider="mangadex",
            external_id=external_id,
            titles=self._titles(item),
            adult=self._adult(item),
            popularity=statistics.get("follows") or 0,
            year=str(attributes.get("year") or "") or None,
            media_type=attributes.get("publicationDemographic") or "manga",
            description=description,
            description_language=description_language,
            status=STATUS_MAP.get(attributes.get("status")),
            genres=_unique(genres),
            genre_languages=genre_languages,
            creators=creators,
            score=(rating.get("bayesian") * 10) if rating.get("bayesian") is not None else None,
            site_url=f"https://mangadex.org/title/{external_id}",
            cover_urls=cover_urls,
        )
