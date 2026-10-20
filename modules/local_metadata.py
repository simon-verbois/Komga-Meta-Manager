"""Persistent local catalogue and pending writes, isolated by Komga server URL."""

import base64
import json
import threading
from contextlib import contextmanager

from modules.models import KomgaBook, KomgaSeries, KomgaLibrary
from modules.series_warnings import numbering_warnings
from modules.webui.db import get_db

# Serialize editor read/plan/save with catalogue refreshes in the web process.
EDIT_LOCK = threading.RLock()


class LocalCatalogue:
    """Store complete local objects, explicit manual overrides and pending patches."""

    def __init__(self, server: str, preview: bool = False):
        self.preview = preview
        self.preview_rows = {}
        self.server = str(server).rstrip("/")
        with get_db() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS local_metadata (
                server TEXT NOT NULL, entity TEXT NOT NULL, id TEXT NOT NULL,
                library_id TEXT NOT NULL, series_id TEXT NOT NULL,
                data TEXT NOT NULL, pending TEXT NOT NULL DEFAULT '{}',
                manual TEXT NOT NULL DEFAULT '[]', cover TEXT,
                PRIMARY KEY (server, entity, id))""")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(local_metadata)")}
            if "cover_pending" not in columns:
                conn.execute("ALTER TABLE local_metadata ADD COLUMN cover_pending INTEGER NOT NULL DEFAULT 0")
            if "remote" not in columns:
                # Komga metadata as last seen, so Review can show before/after values.
                conn.execute("ALTER TABLE local_metadata ADD COLUMN remote TEXT")
            if "missing" not in columns:
                conn.execute("ALTER TABLE local_metadata ADD COLUMN missing INTEGER NOT NULL DEFAULT 0")
            conn.execute("""CREATE TABLE IF NOT EXISTS local_catalogue_scopes (
                server TEXT NOT NULL, entity TEXT NOT NULL, scope_id TEXT NOT NULL,
                PRIMARY KEY (server, entity, scope_id))""")

    def has_local_scope(self, entity: str, scope_id: str) -> bool:
        """Keep a deliberately emptied catalogue local until an explicit refresh."""
        with get_db() as conn:
            return conn.execute(
                "SELECT 1 FROM local_catalogue_scopes WHERE server=? AND entity=? AND scope_id=?",
                (self.server, entity, scope_id),
            ).fetchone() is not None

    def remove_item(self, library_id: str, entity: str, identifier: str) -> bool:
        """Delete only local metadata; series removal also deletes its local books."""
        if entity not in ("series", "books") or self.preview:
            return False
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT series_id FROM local_metadata WHERE server=? AND library_id=? AND entity=? AND id=?",
                (self.server, library_id, entity, identifier),
            ).fetchone()
            if row is None:
                return False
            if entity == "series":
                conn.execute(
                    "DELETE FROM local_metadata WHERE server=? AND library_id=? AND series_id=?",
                    (self.server, library_id, identifier),
                )
            else:
                conn.execute(
                    "DELETE FROM local_metadata WHERE server=? AND library_id=? AND entity=? AND id=?",
                    (self.server, library_id, entity, identifier),
                )
            scope_id = library_id if entity == "series" else row["series_id"]
            conn.execute(
                "INSERT OR IGNORE INTO local_catalogue_scopes VALUES (?, ?, ?)",
                (self.server, entity, scope_id),
            )
        return True

    def reconcile_series(self, library_id: str, present_ids: set[str]) -> None:
        """Mark absent series and their books after a complete successful remote listing."""
        if self.preview:
            return
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT DISTINCT series_id FROM local_metadata WHERE server=? AND library_id=?",
                (self.server, library_id),
            ).fetchall()
            conn.executemany(
                "UPDATE local_metadata SET missing=? WHERE server=? AND library_id=? AND series_id=?",
                [(int(row["series_id"] not in present_ids), self.server, library_id, row["series_id"]) for row in rows],
            )

    def missing_series_ids(self, library_id: str) -> set[str]:
        """Return locally retained series absent from the last successful Komga listing."""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT series_id FROM local_metadata WHERE server=? AND library_id=? AND missing=1",
                (self.server, library_id),
            ).fetchall()
        return {row["series_id"] for row in rows}

    def remove_missing_series(self, library_id: str, series_id: str) -> bool:
        """Remove a confirmed absent local series, its books, covers and pending edits."""
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT missing FROM local_metadata WHERE server=? AND library_id=? AND entity='series' AND id=?",
                (self.server, library_id, series_id),
            ).fetchone()
            if not row or not row["missing"]:
                return False
            conn.execute(
                "DELETE FROM local_metadata WHERE server=? AND library_id=? AND series_id=?",
                (self.server, library_id, series_id),
            )
        return True

    def get(self, entity: str, identifier: str) -> dict | None:
        if (entity, identifier) in self.preview_rows:
            return dict(self.preview_rows[(entity, identifier)])
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM local_metadata WHERE server=? AND entity=? AND id=?",
                (self.server, entity, identifier),
            ).fetchone()
        return dict(row) if row else None

    def pending_ids(self, library_id: str) -> set[tuple[str, str]]:
        """Identify pending catalogue items without loading cover image data."""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT entity, id, series_id FROM local_metadata WHERE server=? AND library_id=? AND (pending != '{}' OR cover_pending=1)",
                (self.server, library_id),
            ).fetchall()
        return {(row["entity"], row["id"]) for row in rows} | {
            ("book_series", row["series_id"]) for row in rows if row["entity"] == "books"
        }

    def items(self, entity: str, library_id: str, series_id: str | None = None) -> list:
        query = "SELECT data FROM local_metadata WHERE server=? AND entity=? AND library_id=?"
        params = [self.server, entity, library_id]
        if series_id is not None:
            query += " AND series_id=?"
            params.append(series_id)
        with get_db() as conn:
            rows = conn.execute(query + " ORDER BY id", params).fetchall()
        model = KomgaBook if entity == "books" else KomgaSeries
        return [model.model_validate_json(row["data"]) for row in rows]

    def import_item(self, entity: str, item, library_id: str, series_id: str, replace: bool = False):
        """Refresh remote values while retaining pending edits and manual overrides."""
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.get(entity, item.id)
            data = item.model_dump(mode="json", by_alias=True)
            remote = json.dumps(data["metadata"])
            pending = json.loads(row["pending"]) if row else {}
            manual = json.loads(row["manual"]) if row else []
            cover = row["cover"] if row else None
            cover_pending = row["cover_pending"] if row else 0
            if replace:
                for key in manual:
                    pending.pop(key, None)
                    pending.pop(f"{key}Lock", None)
                if "cover" in manual:
                    cover = None
                    cover_pending = 0
                manual = []
            if row:
                previous = json.loads(row["data"])["metadata"]
                for key in manual:
                    if key != "cover":
                        data["metadata"][key] = previous[key]
                        if f"{key}Lock" in previous:
                            data["metadata"][f"{key}Lock"] = previous[f"{key}Lock"]
            data["metadata"].update(pending)
            if self.preview:
                self.preview_rows[(entity, item.id)] = {
                    "server": self.server,
                    "entity": entity,
                    "id": item.id,
                    "library_id": library_id,
                    "series_id": series_id,
                    "data": json.dumps(data),
                    "pending": json.dumps(pending),
                    "manual": json.dumps(manual),
                    "cover": cover,
                    "cover_pending": cover_pending,
                    "remote": remote,
                }
                return type(item).model_validate(data)
            conn.execute(
                """INSERT OR REPLACE INTO local_metadata
                (server, entity, id, library_id, series_id, data, pending, manual, cover, cover_pending, remote)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.server,
                    entity,
                    item.id,
                    library_id,
                    series_id,
                    json.dumps(data),
                    json.dumps(pending),
                    json.dumps(manual),
                    cover,
                    cover_pending,
                    remote,
                ),
            )
        return type(item).model_validate(data)

    def patch(self, entity: str, identifier: str, payload: dict, manual: bool = False) -> bool:
        """Atomically merge edits; provider writes cannot replace protected fields."""
        return self.patch_many([{"entity": entity, "id": identifier, "payload": payload}], manual=manual)

    def patch_many(self, patches: list[dict], manual: bool = False) -> bool:
        """Save a batch of distinct metadata edits in one database transaction."""
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for patch in patches:
                entity, identifier, payload = patch["entity"], patch["id"], patch["payload"]
                row = self.get(entity, identifier)
                if row is None:
                    raise ValueError("Import this item before editing it")
                protected = set(json.loads(row["manual"]))
                accepted = {
                    key: value for key, value in payload.items() if manual or key.removesuffix("Lock") not in protected
                }
                data, pending = json.loads(row["data"]), json.loads(row["pending"])
                data["metadata"].update(accepted)
                pending.update(accepted)
                if manual:
                    protected.update(key for key in accepted if not key.endswith("Lock"))
                if self.preview:
                    row.update(data=json.dumps(data), pending=json.dumps(pending), manual=json.dumps(sorted(protected)))
                    self.preview_rows[(entity, identifier)] = row
                    continue
                conn.execute(
                    "UPDATE local_metadata SET data=?, pending=?, manual=? WHERE server=? AND entity=? AND id=?",
                    (json.dumps(data), json.dumps(pending), json.dumps(sorted(protected)), self.server, entity, identifier),
                )
        return True

    def save_cover(self, entity: str, identifier: str, content: bytes | None, manual: bool = False) -> None:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.get(entity, identifier)
            if row is None:
                raise ValueError("Import this item before editing its cover")
            protected = set(json.loads(row["manual"]))
            if "cover" in protected and not manual:
                return
            if manual:
                protected.add("cover")
            encoded = base64.b64encode(content).decode() if content is not None else "remove"
            if self.preview:
                row.update(cover=encoded, manual=json.dumps(sorted(protected)), cover_pending=1)
                self.preview_rows[(entity, identifier)] = row
                return
            conn.execute(
                "UPDATE local_metadata SET cover=?, manual=?, cover_pending=1 WHERE server=? AND entity=? AND id=?",
                (encoded, json.dumps(sorted(protected)), self.server, entity, identifier),
            )


    def pending_counts(self) -> dict[str, int]:
        """Count series with unpublished changes per library (book changes count for their series)."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT library_id, COUNT(DISTINCT series_id) AS n FROM local_metadata
                WHERE server=? AND (pending != '{}' OR cover_pending=1) GROUP BY library_id""",
                (self.server,),
            ).fetchall()
        return {row["library_id"]: row["n"] for row in rows}

    def series_counts(self) -> dict[str, int]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT library_id, COUNT(*) AS n FROM local_metadata WHERE server=? AND entity='series' GROUP BY library_id",
                (self.server,),
            ).fetchall()
        return {row["library_id"]: row["n"] for row in rows}

    def pending_changes(self, library_id: str | None = None) -> list[dict]:
        """Describe unpublished changes as field-level before/after values, grouped by series."""
        query = """SELECT entity, id, library_id, series_id, data, pending, manual, cover, cover_pending, remote
            FROM local_metadata WHERE server=? AND (pending != '{}' OR cover_pending=1)"""
        params = [self.server]
        if library_id:
            query += " AND library_id=?"
            params.append(library_id)
        with get_db() as conn:
            rows = conn.execute(query + " ORDER BY library_id, series_id, entity DESC, id", params).fetchall()
            series_ids = {row["series_id"] for row in rows}
            titles = {
                row["id"]: json.loads(row["data"])
                for row in conn.execute(
                    f"SELECT id, data FROM local_metadata WHERE server=? AND entity='series' AND id IN ({','.join('?' * len(series_ids))})",
                    (self.server, *series_ids),
                )
            } if series_ids else {}
            books_by_series = {series_id: [] for series_id in series_ids}
            if series_ids:
                for row in conn.execute(
                    f"SELECT id, series_id, remote FROM local_metadata WHERE server=? AND entity='books' AND series_id IN ({','.join('?' * len(series_ids))}) ORDER BY id",
                    (self.server, *series_ids),
                ):
                    if row["remote"]:
                        books_by_series[row["series_id"]].append({
                            "id": row["id"], "metadata": json.loads(row["remote"]),
                        })
        groups: dict[str, dict] = {}
        for row in rows:
            data = json.loads(row["data"])
            series = titles.get(row["series_id"], data if row["entity"] == "series" else {})
            group = groups.setdefault(row["series_id"], {
                "series_id": row["series_id"],
                "library_id": row["library_id"],
                "title": (series.get("metadata") or {}).get("title") or series.get("name") or row["series_id"],
                "items": [],
            })
            remote = json.loads(row["remote"]) if row["remote"] else None
            pending, manual = json.loads(row["pending"]), set(json.loads(row["manual"]))
            changes = [
                {
                    "field": key,
                    "before": remote.get(key) if remote is not None else None,
                    "before_known": remote is not None,
                    "after": value,
                    "lock": bool(pending.get(f"{key}Lock")),
                    "manual": key in manual,
                }
                for key, value in pending.items()
                if not key.endswith("Lock") and (remote is None or remote.get(key) != value)
            ]
            # A lock-only change still needs publishing.
            changes += [
                {"field": key.removesuffix("Lock"), "before": None, "before_known": False, "after": None,
                 "lock": bool(value), "manual": key.removesuffix("Lock") in manual, "lock_only": True}
                for key, value in pending.items()
                if key.endswith("Lock") and key.removesuffix("Lock") not in pending
                and (remote is None or remote.get(key) != value)
            ]
            if row["cover_pending"]:
                changes.append({"field": "cover", "after": "remove" if row["cover"] == "remove" else "upload",
                                "before": None, "before_known": False, "lock": False, "manual": "cover" in manual})
            if changes:
                group["items"].append({
                    "entity": row["entity"],
                    "id": row["id"],
                    "title": data["metadata"].get("title") or data.get("name"),
                    "current_title": remote.get("title") if remote is not None else None,
                    "number": data["metadata"].get("number"),
                    "number_sort": data["metadata"].get("numberSort"),
                    "changes": changes,
                })
        result = [group for group in groups.values() if group["items"]]
        for group in result:
            group["warnings"] = numbering_warnings(books_by_series[group["series_id"]])
        return result

    def discard(self, series_id: str, entity: str | None = None, identifier: str | None = None,
                field: str | None = None) -> int:
        """Drop unpublished changes for a series, one item or one field, restoring the Komga values."""
        query = "SELECT * FROM local_metadata WHERE server=? AND series_id=?"
        params = [self.server, series_id]
        if entity and identifier:
            query += " AND entity=? AND id=?"
            params += [entity, identifier]
        changed = 0
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for row in conn.execute(query, params).fetchall():
                data, pending = json.loads(row["data"]), json.loads(row["pending"])
                manual = set(json.loads(row["manual"]))
                remote = json.loads(row["remote"]) if row["remote"] else {}
                fields = [field] if field else [*{key.removesuffix("Lock") for key in pending}, "cover"]
                cover, cover_pending = row["cover"], row["cover_pending"]
                for name in fields:
                    if name == "cover":
                        if cover_pending:
                            cover, cover_pending = None, 0
                            manual.discard("cover")
                            changed += 1
                        continue
                    for key in (name, f"{name}Lock"):
                        if key in pending:
                            pending.pop(key)
                            if key in remote:
                                data["metadata"][key] = remote[key]
                            changed += 1
                    manual.discard(name)
                conn.execute(
                    "UPDATE local_metadata SET data=?, pending=?, manual=?, cover=?, cover_pending=? WHERE server=? AND entity=? AND id=?",
                    (json.dumps(data), json.dumps(pending), json.dumps(sorted(manual)), cover, cover_pending,
                     self.server, row["entity"], row["id"]),
                )
        return changed


class LocalKomgaClient:
    """Reuse enrichment and edit planners while directing all writes to KMM."""

    metadata_destination = "KMM"

    def __init__(
        self,
        remote,
        *,
        manual: bool = False,
        replace: bool = False,
        refresh: bool = True,
        preview: bool = False,
        series_ids=None,
        book_ids=None,
        store=None,
        exclude_series=None,
    ):
        self.remote = remote
        self.store = store or LocalCatalogue(remote.base_url, preview)
        self.manual = manual
        self.replace = replace
        self.exclude_series = set(exclude_series or [])
        self.selected_series_ids = series_ids
        self.selected_book_ids = book_ids
        self.refresh = refresh
        self.series_libraries = {}
        with get_db() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS local_libraries (server TEXT, id TEXT, name TEXT, PRIMARY KEY(server, id))"
            )

    def get_libraries(self):
        if not self.refresh:
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT id, name FROM local_libraries WHERE server=?", (self.store.server,)
                ).fetchall()
            if rows:
                return [KomgaLibrary(**dict(row)) for row in rows]
        libraries = self.remote.get_libraries()
        if not self.store.preview:
            with get_db() as conn:
                for library in libraries:
                    conn.execute(
                        "INSERT OR REPLACE INTO local_libraries VALUES (?, ?, ?)",
                        (self.store.server, library.id, library.name),
                    )
        return libraries

    def __getattr__(self, name):
        return getattr(self.remote, name)

    def get_series_in_library(self, library_id, library_name):
        cached = self.store.items("series", library_id)
        if not self.refresh and (cached or self.store.has_local_scope("series", library_id)):
            items = cached
        else:
            remote_items = self.remote.get_series_in_library(library_id, library_name)
            items = [
                self.store.import_item(
                    "series",
                    item,
                    library_id,
                    item.id,
                    self.replace
                    and item.name not in self.exclude_series
                    and (self.selected_series_ids is None or item.id in self.selected_series_ids),
                )
                for item in remote_items
                if item.library_id == library_id
            ]
            self.store.reconcile_series(library_id, {item.id for item in items})
        self.series_libraries.update({item.id: library_id for item in items})
        return items

    def get_books_in_series(self, series_id, series_name):
        library_id = self.series_libraries[series_id]
        cached = self.store.items("books", library_id, series_id)
        if not self.refresh and (cached or self.store.has_local_scope("books", series_id)):
            return cached
        return [
            self.store.import_item(
                "books",
                item,
                library_id,
                series_id,
                self.replace
                and (self.selected_series_ids is None or series_id in self.selected_series_ids)
                and (self.selected_book_ids is None or item.id in self.selected_book_ids),
            )
            for item in self.remote.get_books_in_series(series_id, series_name)
            if item.series_id == series_id
        ]

    def update_series_metadata(self, identifier, payload):
        return self.store.patch("series", identifier, payload, self.manual)

    def update_book_metadata(self, identifier, payload):
        return self.store.patch("books", identifier, payload, self.manual)

    def upload_custom_cover(self, entity, identifier, content):
        self.store.save_cover(entity, identifier, content, self.manual)

    def get_current_series_cover(self, identifier: str) -> bytes:
        """Read the local cover first, otherwise the saved Komga server's thumbnail."""
        row = self.store.get("series", identifier)
        if row and row["cover"] not in (None, "remove"):
            content = base64.b64decode(row["cover"])
        else:
            from modules.constants import MAX_COVER_IMAGE_BYTES
            from modules.komga_client import CoverImageError

            response = self.remote.session.get(
                f"{self.remote.base_url}/api/v1/series/{identifier}/thumbnail",
                headers={**self.remote.headers, "Accept": "image/*"},
                verify=self.remote.verify_ssl, timeout=(5, 20), stream=True,
            )
            try:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > MAX_COVER_IMAGE_BYTES:
                        raise CoverImageError("Cover exceeds the size limit")
                content = bytes(content)
            finally:
                response.close()
        self.remote.validate_cover_upload(content)
        return content

    def update_book_poster(self, identifier, image_url, overwrite_existing=False, dry_run=False):
        """Stage a book cover locally while preserving manual choices and custom covers."""
        row = self.store.get("books", identifier)
        if "cover" in json.loads(row["manual"]) or (row["cover"] and not overwrite_existing):
            return "preserved"
        thumbnails = self.remote.get_book_thumbnails(identifier)
        if not overwrite_existing and any(item.get("type", "").upper() == "USER_UPLOADED" for item in thumbnails):
            return "preserved"
        content, _, _ = self.remote._download_cover_image(image_url)
        if dry_run:
            return "would_upload"
        self.store.save_cover("books", identifier, content)
        return "uploaded"

    def remove_uploaded_book_posters(self, identifier, dry_run=False):
        """Stage removal of custom book covers without changing Komga during fetch."""
        row = self.store.get("books", identifier)
        if "cover" in json.loads(row["manual"]):
            return 0
        count = sum(item.get("type", "").upper() == "USER_UPLOADED" for item in self.remote.get_book_thumbnails(identifier))
        if not dry_run and (count or row["cover"]):
            self.store.save_cover("books", identifier, None)
        return count

    def update_series_poster(self, identifier, image_url, overwrite_existing=False, dry_run=False):
        row = self.store.get("series", identifier)
        if "cover" in json.loads(row["manual"]):
            return "preserved"
        thumbnails = self.remote.get_series_thumbnails(identifier)
        if not overwrite_existing and any(t.type.upper() == "USER_UPLOADED" for t in thumbnails):
            return "preserved"
        content, _, _ = self.remote._download_cover_image(image_url)
        if dry_run:
            return "would_upload"
        self.store.save_cover("series", identifier, content)
        return "uploaded"

    def remove_uploaded_series_posters(self, identifier, dry_run=False):
        row = self.store.get("series", identifier)
        if "cover" in json.loads(row["manual"]):
            return 0
        count = sum(t.type.upper() == "USER_UPLOADED" for t in self.remote.get_series_thumbnails(identifier))
        if not dry_run:
            self.store.save_cover("series", identifier, None)
        return count


@contextmanager
def local_edit_lock():
    """Keep the editor's comparison and local save in the same SQLite transaction."""
    # Workers and editor requests share this lock across processes.
    import fcntl
    from modules.webui import db

    with EDIT_LOCK, open(str(db.DB_PATH) + ".metadata.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
