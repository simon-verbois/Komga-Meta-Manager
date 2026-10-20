"""Book providers using public bibliographic APIs rather than HTML scraping."""

import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

import requests
from pydantic import BaseModel

from modules.constants import HTTP_TIMEOUTS
from modules.models import MetadataCreator, MetadataRecord
from modules.providers.base import MetadataProviderError
from modules.providers.http import HttpMetadataProvider

logger = logging.getLogger(__name__)


def normalize_isbn(value: str) -> str:
    """Normalize a valid ISBN, checking its checksum before using it as identity."""
    value = re.sub(r"[^0-9Xx]", "", value or "").upper()
    if len(value) == 13 and value.isdigit():
        return value if sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0 else ""
    if len(value) == 10 and value[:9].isdigit() and (value[-1].isdigit() or value[-1] == "X"):
        if sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(value)) % 11 == 0:
            core = "978" + value[:9]
            return core + str((-sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core))) % 10)
    return ""


def iso_language(value: str | None) -> str:
    """Normalize the common bibliographic language codes without guessing unknown ones."""
    value = (value or "").lower().split("-")[0]
    return {
        "eng": "en",
        "fre": "fr",
        "fra": "fr",
        "ger": "de",
        "deu": "de",
        "spa": "es",
        "ita": "it",
        "dut": "nl",
        "nld": "nl",
        "jpn": "ja",
        "kor": "ko",
        "por": "pt",
    }.get(value, value)


class BookQuery(BaseModel):
    """Identity hints for a single edition, also used to isolate cached searches."""

    title: str
    author: str = ""
    isbn: str = ""
    language: str = ""


class EbookProvider(HttpMetadataProvider):
    """Shared structured search entry point for bibliographic providers."""

    def __init__(self, cache_dir: Path, cache_ttl_hours: int, preferred_language: str = "en"):
        super().__init__(cache_dir, cache_ttl_hours)
        self.preferred_language = iso_language(preferred_language)

    def search_book(self, query: BookQuery) -> list:
        """Cache by all identity hints, rather than by title alone."""
        try:
            return self.search(query.model_dump_json())
        except (ValueError, KeyError, TypeError):
            raise MetadataProviderError("The ebook source returned invalid search data") from None

    def get_by_id(self, external_id: str) -> MetadataRecord:
        """Report malformed source records as recoverable provider errors."""
        try:
            return super().get_by_id(external_id)
        except (ValueError, KeyError, TypeError):
            raise MetadataProviderError("The ebook source returned invalid edition data") from None

    def query(self, search_term: str) -> BookQuery:
        """Accept structured worker searches and plain manual searches."""
        try:
            return BookQuery.model_validate(json.loads(search_term))
        except (ValueError, TypeError):
            return BookQuery(title=search_term)


class OpenlibraryProvider(EbookProvider):
    """Resolve Open Library editions, retaining edition ISBN, date and publisher."""

    _rate_lock = threading.Lock()
    _last_request = 0.0

    def _get(self, path: str, **kwargs) -> dict:
        with self._rate_lock:
            delay = 1.05 - (time.monotonic() - type(self)._last_request)
            if delay > 0:
                time.sleep(delay)
            type(self)._last_request = time.monotonic()
            return self._request_json("GET", "https://openlibrary.org" + path, **kwargs)

    def _perform_search(self, search_term: str) -> list[MetadataRecord]:
        query = self.query(search_term)
        isbn = normalize_isbn(query.isbn)
        if isbn:
            try:
                edition = self._get(f"/isbn/{isbn}.json")
            except MetadataProviderError as exc:
                if isinstance(exc.__cause__, requests.HTTPError) and exc.__cause__.response.status_code == 404:
                    return []
                raise
            return [self._edition(edition)]
        params = {
            "title": query.title,
            "limit": 10,
            "fields": "key,title,author_name,language,editions,editions.key,editions.title,editions.language,editions.isbn,editions.author_name,editions.publish_date,editions.publisher",
        }
        if query.author:
            params["author"] = query.author
        language = iso_language(query.language) or self.preferred_language
        if language:
            params["lang"] = language
        records = []
        for work in self._get("/search.json", params=params).get("docs", []):
            for edition in (work.get("editions") or {}).get("docs", []):
                record = MetadataRecord(
                    provider="openlibrary",
                    external_id=edition["key"].split("/")[-1],
                    titles=[edition.get("title") or work.get("title", "")],
                    author_names=edition.get("author_name") or work.get("author_name", []),
                    isbns=[isbn for value in edition.get("isbn", []) if (isbn := normalize_isbn(value))],
                    language=iso_language(next(iter(edition.get("language", [])), "")),
                    publication_date=next(iter(edition.get("publish_date", [])), None),
                    publisher=next(iter(edition.get("publisher", [])), None),
                    media_type="ebook",
                )
                records.append(record)
        return records

    def _edition(self, data: dict) -> MetadataRecord:
        description = data.get("description")
        if isinstance(description, dict):
            description = description.get("value")
        return MetadataRecord(
            provider="openlibrary",
            external_id=data["key"].split("/")[-1],
            titles=[data.get("title", "")],
            description=description,
            publisher=next(iter(data.get("publishers", [])), None),
            publication_date=data.get("publish_date"),
            isbns=list(
                dict.fromkeys(
                    isbn
                    for value in data.get("isbn_13", []) + data.get("isbn_10", [])
                    if (isbn := normalize_isbn(value))
                )
            ),
            language=iso_language(next(iter(data.get("languages", [])), {}).get("key", "").split("/")[-1]),
            site_url="https://openlibrary.org" + data["key"],
            media_type="ebook",
            cover_urls=[
                f"https://covers.openlibrary.org/b/id/{cover}-L.jpg" for cover in data.get("covers", []) if cover > 0
            ],
        )

    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        if not re.fullmatch(r"OL\d+M", external_id):
            raise MetadataProviderError("Invalid Open Library edition identifier")
        data = self._get(f"/books/{external_id}.json")
        record = self._edition(data)
        authors = data.get("authors", [])
        works = data.get("works", [])
        if works:
            work_key = works[0].get("key", "")
            if re.fullmatch(r"/works/OL\d+W", work_key):
                work = self._get(work_key + ".json")
                description = work.get("description")
                if isinstance(description, dict):
                    description = description.get("value")
                record.description = record.description or description
                authors = authors or [entry.get("author", {}) for entry in work.get("authors", [])]
        for author in authors[:8]:
            key = author.get("key", "")
            if re.fullmatch(r"/authors/OL\d+A", key):
                name = self._get(key + ".json").get("name")
                if name:
                    record.author_names.append(name)
                    record.creators.append(MetadataCreator(name=name, role="writer"))
        return record


class GooglebooksProvider(EbookProvider):
    """Google Books volumes, with a server-side key and sanitized failures."""

    def __init__(self, *args, api_key: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key
        self._retry_at = 0.0
        self._unavailable_status = None

    def _get(self, path: str = "", **params) -> dict:
        if not self.api_key:
            raise MetadataProviderError("Google Books needs an API key in Settings → External services")
        if time.monotonic() < self._retry_at:
            raise MetadataProviderError(
                "Google Books is temporarily paused after a service failure; other enabled sources are still tried",
                status_code=self._unavailable_status,
                reason="service_cooldown",
            )
        # Send credentials in a header so exception URLs and logs cannot expose them.
        try:
            return self._request_json(
                "GET",
                "https://www.googleapis.com/books/v1/volumes" + path,
                params=params,
                headers={"X-Goog-Api-Key": self.api_key},
            )
        except MetadataProviderError as exc:
            status = exc.status_code
            reason = exc.reason
            if status is not None and status >= 500:
                message = f"Google Books is temporarily unavailable (HTTP {status}); retry later"
                self._unavailable_status = status
                self._retry_at = time.monotonic() + 60
                logger.warning(
                    "Google Books is paused for 60 seconds after HTTP %s; cached results and other enabled sources remain available.",
                    status,
                )
            elif status == 429 or reason in {
                "dailyLimitExceeded",
                "quotaExceeded",
                "rateLimitExceeded",
                "userRateLimitExceeded",
                "RESOURCE_EXHAUSTED",
            }:
                message = (
                    f"Google Books quota or rate limit reached (HTTP {status}); check project quotas and retry later"
                )
            elif status == 401 or reason in {"keyInvalid", "API_KEY_INVALID", "API_KEY_EXPIRED"}:
                message = "Google Books rejected the API key; check the saved key in Settings → External services"
            elif status == 403:
                message = "Google Books denied access (HTTP 403); check Books API enablement and API-key restrictions in Settings → External services"
            elif status == 404:
                message = "This Google Books edition was not found (HTTP 404); choose another edition"
            elif status is not None:
                message = f"Google Books rejected the request (HTTP {status}); check source settings and retry"
            elif reason == "timeout":
                message = "Google Books request timed out; retry later"
            elif reason == "invalid_response":
                message = "Google Books returned an unreadable response; retry later"
            else:
                message = "Could not connect to Google Books; check the connection and retry"
            raise MetadataProviderError(message, status_code=status, reason=reason) from None

    @staticmethod
    def _record(data: dict) -> MetadataRecord:
        info = data.get("volumeInfo", {})
        title = info.get("title", "")
        images = info.get("imageLinks", {})
        authors = info.get("authors", [])
        return MetadataRecord(
            provider="googlebooks",
            adult=info.get("maturityRating") == "MATURE",
            external_id=data["id"],
            titles=[title],
            author_names=authors,
            creators=[MetadataCreator(name=name, role="writer") for name in authors],
            description=info.get("description"),
            description_language=iso_language(info.get("language")) or None,
            publisher=info.get("publisher"),
            language=iso_language(info.get("language")),
            publication_date=info.get("publishedDate"),
            year=(info.get("publishedDate") or "")[:4] or None,
            genres=info.get("categories", []),
            isbns=list(
                dict.fromkeys(
                    isbn
                    for item in info.get("industryIdentifiers", [])
                    if (isbn := normalize_isbn(item.get("identifier", "")))
                )
            ),
            cover_urls=[
                url.replace("http://", "https://", 1)
                for key in ("large", "medium", "thumbnail")
                if (url := images.get(key))
            ],
            site_url=f"https://books.google.com/books?id={quote(data['id'], safe='')}",
            media_type="ebook",
        )

    def _perform_search(self, search_term: str) -> list[MetadataRecord]:
        query = self.query(search_term)
        isbn = normalize_isbn(query.isbn)
        title = query.title.replace('"', " ")
        author = query.author.replace('"', " ")
        search = f"isbn:{isbn}" if isbn else f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else "")
        params = {"q": search, "maxResults": 10, "printType": "books"}
        if query.language and not isbn:
            params["langRestrict"] = iso_language(query.language)
        return [self._record(item) for item in self._get(**params).get("items", [])]

    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", external_id):
            raise MetadataProviderError("Invalid Google Books identifier")
        return self._record(self._get("/" + external_id))


class BnfProvider(EbookProvider):
    """BnF SRU Dublin Core records with ISBN and bibliographic identity."""

    def _records(self, query: str) -> list[MetadataRecord]:
        try:
            response = self.session.get(
                "https://catalogue.bnf.fr/api/SRU",
                params={
                    "version": "1.2",
                    "operation": "searchRetrieve",
                    "query": query,
                    "recordSchema": "dublincore",
                    "maximumRecords": 10,
                },
                timeout=HTTP_TIMEOUTS,
            )
            response.raise_for_status()
            # ElementTree does not resolve external entities; reject DTDs explicitly.
            if b"<!DOCTYPE" in response.content.upper():
                raise ValueError("Unexpected XML document type")
            root = ElementTree.fromstring(response.content)
            if root.findall(".//{http://www.loc.gov/zing/srw/diagnostic/}diagnostic"):
                raise ValueError("SRU diagnostic")
        except (requests.RequestException, ElementTree.ParseError, ValueError):
            raise MetadataProviderError("BnF search failed; check the connection and retry") from None
        result = []
        for data in root.findall(".//{http://www.loc.gov/zing/srw/}recordData"):

            def values(name):
                return [
                    "".join(node.itertext()).strip()
                    for node in data.findall(f".//{{http://purl.org/dc/elements/1.1/}}{name}")
                    if "".join(node.itertext()).strip()
                ]

            identifiers = values("identifier")
            url = next((value for value in identifiers if re.search(r"ark:/12148/cb\w+", value)), "")
            match = re.search(r"ark:/12148/(cb\w+)", url)
            if not match:
                continue
            authors = [
                re.sub(r"\s*\([^)]*\)", "", value).split(". Auteur")[0].strip()
                for value in values("creator")
                if "Illustrateur" not in value
            ]
            dates = values("date")
            languages = values("language")
            result.append(
                MetadataRecord(
                    provider="bnf",
                    external_id=match[1],
                    titles=[value.split(" / ")[0].strip() for value in values("title")],
                    author_names=authors,
                    creators=[MetadataCreator(name=name, role="writer") for name in authors],
                    isbns=list(
                        dict.fromkeys(
                            isbn
                            for value in identifiers
                            if (isbn := normalize_isbn(value.removeprefix("urn:ISBN:").removeprefix("ISBN ")))
                        )
                    ),
                    description="\n".join(
                        value
                        for value in values("description")
                        if not value.startswith(("Collection", "Code à barres", "Note", "Comprend", "Titre"))
                    )
                    or None,
                    publisher=next(iter(values("publisher")), None),
                    language=iso_language(languages[0]) if languages else None,
                    publication_date=dates[0] if dates else None,
                    site_url="https://catalogue.bnf.fr/ark:/12148/" + match[1],
                    media_type="ebook",
                )
            )
        return result

    def _perform_search(self, search_term: str) -> list[MetadataRecord]:
        query = self.query(search_term)
        isbn = normalize_isbn(query.isbn)
        # Escape CQL literals; never let a title become a query operator.
        title = query.title.replace("\\", " ").replace('"', " ")
        author = query.author.replace("\\", " ").replace('"', " ")
        expression = (
            f'bib.fuzzyISBN all "{isbn}"'
            if isbn
            else f'bib.title all "{title}"' + (f' and bib.author all "{author}"' if author else "")
        )
        return self._records(expression + ' and bib.doctype any "a"')

    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        if not re.fullmatch(r"cb\w+", external_id):
            raise MetadataProviderError("Invalid BnF identifier")
        records = self._records(f'bib.persistentid all "ark:/12148/{external_id}"')
        if not records:
            raise MetadataProviderError("BnF record was not found")
        return records[0]
