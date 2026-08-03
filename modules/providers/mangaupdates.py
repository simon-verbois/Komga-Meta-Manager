"""MangaUpdates metadata provider."""
from pathlib import Path
from typing import List

from modules.constants import MANGAUPDATES_API_URL
from modules.models import MetadataCandidate, MetadataCreator, MetadataRecord
from .base import MetadataProviderError
from .http import HttpMetadataProvider

ADULT_GENRES = {"adult", "hentai", "smut", "lolicon", "shotacon"}


def _genre_names(item: dict) -> list[str]:
    return [entry["genre"] for entry in (item.get("genres") or []) if entry.get("genre")]


def _is_adult(item: dict) -> bool:
    return bool({genre.casefold() for genre in _genre_names(item)} & ADULT_GENRES)


def _status(item: dict) -> str | None:
    if item.get("completed") is True:
        return "ENDED"
    raw = (item.get("status") or "").casefold()
    if "hiatus" in raw:
        return "HIATUS"
    if any(word in raw for word in ("cancelled", "canceled", "discontinued", "dropped")):
        return "ABANDONED"
    if "ongoing" in raw:
        return "ONGOING"
    return None


def _publisher(item: dict) -> str | None:
    """Return the original publisher(s), excluding translated licensees."""
    names = [
        publisher.get("publisher_name")
        for publisher in (item.get("publishers") or [])
        if isinstance(publisher, dict)
        if (publisher.get("type") or "").strip().casefold() == "original"
    ]
    unique_names = list(dict.fromkeys(name.strip() for name in names if isinstance(name, str) and name.strip()))
    return ", ".join(unique_names) or None


class MangaupdatesProvider(HttpMetadataProvider):
    def __init__(self, cache_dir: Path, cache_ttl_hours: int, preferred_language: str = "en"):
        super().__init__(cache_dir, cache_ttl_hours)

    def _perform_search(self, search_term: str) -> List[MetadataCandidate]:
        payload = self._request_json(
            "POST",
            f"{MANGAUPDATES_API_URL}/series/search",
            json={"search": search_term, "stype": "title", "perpage": 25, "page": 1},
        )
        candidates = []
        for result in payload.get("results") or []:
            item = result.get("record") or {}
            identifier = item.get("series_id")
            titles = list(dict.fromkeys(filter(None, [item.get("title"), result.get("hit_title")])))
            if identifier is None or not titles:
                continue
            candidates.append(MetadataCandidate(
                provider="mangaupdates",
                external_id=str(identifier),
                titles=titles,
                adult=_is_adult(item),
                popularity=item.get("rating_votes") or 0,
                year=str(item.get("year") or "") or None,
                media_type=item.get("type"),
            ))
        return candidates

    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        payload = self._request_json("GET", f"{MANGAUPDATES_API_URL}/series/{external_id}")
        if payload.get("series_id") is None:
            raise MetadataProviderError(f"MangaUpdates series {external_id} was not found")
        titles = [payload.get("title")]
        titles.extend(entry.get("title") for entry in (payload.get("associated") or []))
        creators = []
        for author in payload.get("authors") or []:
            name = author.get("name")
            creator_type = (author.get("type") or "").casefold()
            if name and creator_type in {"author", "artist"}:
                creators.append(MetadataCreator(
                    name=name,
                    role="writer" if creator_type == "author" else "penciller",
                ))
        image = ((payload.get("image") or {}).get("url") or {})
        score = payload.get("bayesian_rating")
        genres = _genre_names(payload)
        return MetadataRecord(
            provider="mangaupdates",
            external_id=str(payload["series_id"]),
            titles=list(dict.fromkeys(value for value in titles if value)),
            adult=_is_adult(payload),
            popularity=payload.get("rating_votes") or 0,
            year=str(payload.get("year") or "") or None,
            media_type=payload.get("type"),
            description=payload.get("description"),
            description_language="en" if payload.get("description") else None,
            publisher=_publisher(payload),
            status=_status(payload),
            genres=genres,
            genre_languages={genre: "en" for genre in genres},
            creators=creators,
            score=(score * 10) if score is not None else None,
            site_url=payload.get("url"),
            cover_urls=[url for url in (image.get("original"), image.get("thumb")) if url],
        )
