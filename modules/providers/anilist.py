# -*- coding: utf-8 -*-
"""AniList adapter for the provider-neutral metadata contract."""
import logging
from pathlib import Path
from typing import List

from gql import Client, gql
from gql.transport.exceptions import TransportQueryError
from gql.transport.requests import RequestsHTTPTransport

from modules.constants import (
    ANILIST_API_URL,
    ANILIST_SEARCH_RESULTS_PER_PAGE,
    HTTP_TIMEOUTS,
    MAX_RETRIES,
)
from modules.models import MetadataCandidate, MetadataCreator, MetadataRecord
from .base import MetadataProvider, MetadataProviderError

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "RELEASING": "ONGOING",
    "FINISHED": "ENDED",
    "CANCELLED": "ABANDONED",
    "HIATUS": "HIATUS",
}


def _unique_strings(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _titles(media: dict) -> list[str]:
    title = media.get("title") or {}
    return _unique_strings([
        title.get("english"),
        title.get("romaji"),
        title.get("native"),
        *(media.get("synonyms") or []),
    ])


class AnilistProvider(MetadataProvider):
    def __init__(self, cache_dir: Path, cache_ttl_hours: int, preferred_language: str = "en"):
        super().__init__(cache_dir, cache_ttl_hours)
        transport = RequestsHTTPTransport(
            url=ANILIST_API_URL,
            verify=True,
            retries=MAX_RETRIES,
            timeout=HTTP_TIMEOUTS[1],
        )
        self.client = Client(transport=transport, fetch_schema_from_transport=False)

    def _execute(self, query_text: str, params: dict) -> dict:
        try:
            return self.client.execute(gql(query_text), variable_values=params)
        except TransportQueryError as exc:
            raise MetadataProviderError(f"AniList GraphQL query failed: {exc}") from exc
        except Exception as exc:
            raise MetadataProviderError(f"AniList request failed: {exc}") from exc

    def _perform_search(self, search_term: str) -> List[MetadataCandidate]:
        result = self._execute(
            """
            query ($search: String, $perPage: Int) {
              Page(perPage: $perPage) {
                media(search: $search, type: MANGA, sort: [SEARCH_MATCH]) {
                  id title { romaji english native } synonyms isAdult popularity
                  startDate { year } format
                }
              }
            }
            """,
            {"search": search_term, "perPage": ANILIST_SEARCH_RESULTS_PER_PAGE},
        )
        items = ((result.get("Page") or {}).get("media") or [])
        candidates = []
        for item in items:
            titles = _titles(item)
            if not titles:
                continue
            candidates.append(MetadataCandidate(
                provider="anilist",
                external_id=str(item["id"]),
                titles=titles,
                adult=bool(item.get("isAdult")),
                popularity=item.get("popularity") or 0,
                year=str((item.get("startDate") or {}).get("year") or "") or None,
                media_type=item.get("format"),
            ))
        return candidates

    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        try:
            media_id = int(external_id)
        except ValueError as exc:
            raise MetadataProviderError(f"Invalid AniList ID: {external_id}") from exc
        result = self._execute(
            """
            query ($id: Int) {
              Media(id: $id, type: MANGA) {
                id title { romaji english native } synonyms description(asHtml: false)
                status genres popularity averageScore siteUrl isAdult format startDate { year }
                staff { edges { role node { name { full } } } }
                coverImage { extraLarge large medium }
              }
            }
            """,
            {"id": media_id},
        )
        item = result.get("Media")
        if not item:
            raise MetadataProviderError(f"AniList manga {external_id} was not found")
        creators = []
        for edge in ((item.get("staff") or {}).get("edges") or []):
            role = (edge.get("role") or "").lower()
            name = (((edge.get("node") or {}).get("name") or {}).get("full"))
            if not name:
                continue
            if "story" in role:
                creators.append(MetadataCreator(name=name, role="writer"))
            if "art" in role and "touch-up art" not in role:
                creators.append(MetadataCreator(name=name, role="penciller"))
        cover = item.get("coverImage") or {}
        genres = item.get("genres") or []
        return MetadataRecord(
            provider="anilist",
            external_id=str(item["id"]),
            titles=_titles(item),
            adult=bool(item.get("isAdult")),
            popularity=item.get("popularity") or 0,
            year=str((item.get("startDate") or {}).get("year") or "") or None,
            media_type=item.get("format"),
            description=item.get("description"),
            description_language="en" if item.get("description") else None,
            status=STATUS_MAP.get(item.get("status")),
            genres=genres,
            genre_languages={genre: "en" for genre in genres},
            creators=creators,
            score=item.get("averageScore"),
            site_url=item.get("siteUrl"),
            cover_urls=_unique_strings([cover.get("extraLarge"), cover.get("large"), cover.get("medium")]),
        )
