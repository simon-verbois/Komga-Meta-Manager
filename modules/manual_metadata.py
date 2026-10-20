"""Plan explicit manual edits separately from provider enrichment and UI rendering."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from modules.komga_client import KomgaClient
from modules.models import KomgaBook, KomgaSeries

SERIES_FIELDS = ("title", "summary", "publisher", "status", "genres", "tags", "links", "language", "reading_direction")
BOOK_FIELDS = ("title", "summary", "tags")
AUTHOR_ROLES = {"writers": "writer", "pencillers": "penciller"}


class ManualEditError(ValueError):
    """An actionable validation or concurrency failure, represented by an i18n key."""

    def __init__(self, key: str, status: int = 422):
        super().__init__(key)
        self.key = key
        self.status = status


@dataclass
class EditTarget:
    """Fresh Komga objects belonging to one verified library and series."""

    series: KomgaSeries
    books: list[KomgaBook]
    book: KomgaBook | None = None

    @property
    def entity(self) -> str:
        return "books" if self.book else "series"

    @property
    def identifier(self) -> str:
        return self.book.id if self.book else self.series.id


def load_target(client: KomgaClient, library_id: str, series_id: str, book_id: str | None) -> EditTarget:
    """Validate membership before reading or writing any selected metadata."""
    libraries = client.get_libraries()
    library = next((lib for lib in libraries if lib.id == library_id), None)
    if not library:
        raise ManualEditError("manual.missing", 404)
    series = next(
        (
            s
            for s in client.get_series_in_library(library.id, library.name)
            if s.id == series_id and s.library_id == library_id
        ),
        None,
    )
    if not series:
        raise ManualEditError("manual.missing", 404)
    books = client.get_books_in_series(series.id, series.name)
    books = [book for book in books if book.series_id == series.id]
    if book_id:
        book = next((book for book in books if book.id == book_id), None)
        if not book:
            raise ManualEditError("manual.missing", 404)
        return EditTarget(series, [book], book)
    return EditTarget(series, books)


def editor_values(target: EditTarget) -> dict:
    """Expose supported fields and lock state without leaking unrelated settings."""
    metadata = target.book.metadata if target.book else target.series.metadata
    fields = BOOK_FIELDS if target.book else SERIES_FIELDS
    values = {}
    locks = {}
    for field in fields:
        value = getattr(metadata, field)
        values[field] = sorted(value) if isinstance(value, set) else value
        locks[field] = getattr(metadata, f"{field}_lock", False)
    mixed = {}
    for field, role in AUTHOR_ROLES.items():
        per_book = [
            sorted({a.get("name", "") for a in book.metadata.authors if a.get("role") == role}) for book in target.books
        ]
        mixed[field] = bool(per_book and any(names != per_book[0] for names in per_book[1:]))
        values[field] = None if mixed[field] else (per_book[0] if per_book else [])
        locks[field] = any(book.metadata.authors_lock for book in target.books)
    return {
        "entity": target.entity,
        "id": target.identifier,
        "title": metadata.title or (target.book.name if target.book else target.series.name),
        "values": values,
        "locks": locks,
        "mixed": mixed,
        "book_count": len(target.books),
        "author_versions": {
            book.id: {"authors": book.metadata.authors, "lock": book.metadata.authors_lock} for book in target.books
        },
    }


def _normalize_changes(changes: dict, allowed: set[str]) -> dict:
    if not isinstance(changes, dict) or not set(changes) <= allowed:
        raise ManualEditError("manual.invalid_fields")
    normalized = {}
    for field, value in changes.items():
        if field == "reading_direction":
            if value not in {None, "LEFT_TO_RIGHT", "RIGHT_TO_LEFT", "VERTICAL", "WEBTOON"}:
                raise ManualEditError("manual.invalid_fields")
            normalized[field] = value
        elif field in {"genres", "tags", *AUTHOR_ROLES}:
            if not isinstance(value, list) or len(value) > 1000 or any(not isinstance(v, str) for v in value):
                raise ManualEditError("manual.invalid_fields")
            normalized[field] = sorted({v.strip() for v in value if v.strip()})
        elif field == "links":
            if not isinstance(value, list) or len(value) > 100:
                raise ManualEditError("manual.invalid_links")
            links = []
            for link in value:
                if (
                    not isinstance(link, dict)
                    or not isinstance(link.get("label"), str)
                    or not isinstance(link.get("url"), str)
                ):
                    raise ManualEditError("manual.invalid_links")
                label, url = link["label"].strip(), link["url"].strip()
                parsed = urlsplit(url)
                if not label or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ManualEditError("manual.invalid_links")
                links.append({"label": label, "url": url})
            normalized[field] = links
        else:
            if not isinstance(value, str) or len(value) > 100_000:
                raise ManualEditError("manual.invalid_fields")
            normalized[field] = value if field == "summary" else value.strip()
            if field == "title" and not normalized[field]:
                raise ManualEditError("manual.title_required")
            if field == "status" and value not in {"ONGOING", "ENDED", "ABANDONED", "HIATUS"}:
                raise ManualEditError("manual.invalid_status")
    return normalized


def plan_edits(target: EditTarget, changes: dict, baseline: dict, lock_fields: bool) -> tuple[list[dict], list[dict]]:
    """Build minimal patches; reject edits based on values changed since opening."""
    current = editor_values(target)
    if not isinstance(baseline, dict) or not isinstance(baseline.get("values"), dict):
        raise ManualEditError("manual.reload", 409)
    changes = _normalize_changes(changes, set(current["values"]))
    for field in changes:
        if field in AUTHOR_ROLES:
            if baseline.get("author_versions") != current["author_versions"]:
                raise ManualEditError("manual.conflict", 409)
        elif (
            baseline["values"].get(field) != current["values"][field]
            or baseline.get("locks", {}).get(field) != current["locks"][field]
        ):
            raise ManualEditError("manual.conflict", 409)
    patches, differences = [], []
    payload = {}
    for field, value in changes.items():
        if field in AUTHOR_ROLES or value == current["values"][field]:
            continue
        key = "readingDirection" if field == "reading_direction" else field
        payload[key] = value
        payload[f"{key}Lock"] = lock_fields
        differences.append({"field": field, "before": current["values"][field], "after": value})
    if payload:
        patches.append({"entity": target.entity, "id": target.identifier, "payload": payload})
    author_fields = set(changes) & set(AUTHOR_ROLES)
    if author_fields:
        for book in target.books:
            retained = [
                author
                for author in book.metadata.authors
                if author.get("role") not in {AUTHOR_ROLES[field] for field in author_fields}
            ]
            updated = retained + [
                {"name": name, "role": AUTHOR_ROLES[field]}
                for field in sorted(author_fields)
                for name in changes[field]
            ]
            if sorted(updated, key=lambda a: (a.get("role", ""), a.get("name", ""))) != sorted(
                book.metadata.authors, key=lambda a: (a.get("role", ""), a.get("name", ""))
            ):
                patches.append(
                    {"entity": "books", "id": book.id, "payload": {"authors": updated, "authorsLock": lock_fields}}
                )
        if any("authors" in patch["payload"] for patch in patches):
            differences.extend(
                {"field": field, "before": current["values"][field], "after": changes[field]}
                for field in sorted(author_fields)
            )
    return patches, differences


def apply_edits(
    client: KomgaClient, target: EditTarget, patches: list[dict], cover: bytes | None,
    cover_all_books: bool = False, replace_series_cover: bool = True,
) -> dict[str, Any]:
    """Attempt each scoped write, reporting partial outcomes without claiming rollback."""
    applied, failed = [], []
    for patch in patches:
        try:
            update = client.update_book_metadata if patch["entity"] == "books" else client.update_series_metadata
            if not update(patch["id"], patch["payload"]):
                raise RuntimeError("Komga rejected the update")
            applied.append(
                {
                    "entity": patch["entity"],
                    "id": patch["id"],
                    "fields": [key for key in patch["payload"] if not key.endswith("Lock")],
                }
            )
        except Exception:
            failed.append({"entity": patch["entity"], "id": patch["id"]})
    cover_applied = False
    if cover:
        targets = [(target.entity, target.identifier)] if replace_series_cover else []
        if cover_all_books and not target.book:
            targets.extend(("books", book.id) for book in target.books)
        cover_applied = bool(targets)
        for entity, identifier in targets:
            try:
                client.upload_custom_cover(entity, identifier, cover)
                applied.append({"entity": entity, "id": identifier, "fields": ["cover"]})
            except Exception:
                cover_applied = False
                failed.append({"entity": entity, "id": identifier, "cover": True})
    return {"applied": applied, "failed": failed, "cover_applied": cover_applied}
