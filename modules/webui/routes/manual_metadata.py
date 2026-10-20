"""Authenticated manual metadata editing, previews and custom image uploads."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from modules.local_metadata import LocalKomgaClient, local_edit_lock
from modules.constants import MAX_COVER_IMAGE_BYTES
from modules.komga_client import CoverImageError, KomgaClient
from modules.manual_metadata import ManualEditError, apply_edits, editor_values, load_target, plan_edits
from modules.webui.config_store import get_config
from modules.webui.db import add_audit_entry
from modules.webui.routes.guards import get_current_user

logger = logging.getLogger(__name__)


def setup_routes() -> APIRouter:
    """Keep multipart transport and authorization outside metadata planning."""
    router = APIRouter(prefix="/libraries")

    def error(key: str, status: int) -> JSONResponse:
        return JSONResponse({"error": key}, status_code=status)

    def execute(library_id: str, series_id: str, book_id: str | None, operation):
        config = get_config()
        if config is None:
            raise ManualEditError("manual.connection", 409)
        remote = KomgaClient(config.komga)
        client = LocalKomgaClient(remote, manual=True, refresh=False)
        try:
            with local_edit_lock():
                target = load_target(client, library_id, series_id, book_id)
                return operation(client, target)
        finally:
            client.session.close()

    @router.get("/{library_id}/manual")
    async def get_editor(request: Request, library_id: str, series_id: str, book_id: str | None = None):
        if not get_current_user(request):
            return error("manual.session", 401)
        try:
            result = await run_in_threadpool(
                execute, library_id, series_id, book_id, lambda client, target: editor_values(target)
            )
            return result
        except ManualEditError as exc:
            return error(exc.key, exc.status)
        except Exception:
            logger.warning("Could not read manual metadata from Komga.")
            return error("manual.connection", 502)

    @router.post("/{library_id}/manual")
    async def save_editor(request: Request, library_id: str):
        username = get_current_user(request)
        if not username:
            return error("manual.session", 401)
        cover = None
        try:
            async with request.form(max_files=1, max_fields=10) as form:
                if len(str(form.get("edit", ""))) > 2_000_000:
                    raise ManualEditError("manual.invalid_fields")
                payload = json.loads(form.get("edit", "{}"))
                if not isinstance(payload, dict):
                    raise ManualEditError("manual.invalid_fields")
                series_id, book_id = payload.get("series_id"), payload.get("book_id") or None
                if not isinstance(series_id, str) or (book_id is not None and not isinstance(book_id, str)):
                    raise ManualEditError("manual.invalid_fields")
                mode = payload.get("mode", "preview")
                cover_all_books = payload.get("cover_all_books", False)
                if not isinstance(cover_all_books, bool) or (cover_all_books and book_id):
                    raise ManualEditError("manual.invalid_fields")
                if mode not in {"preview", "apply"} or not isinstance(payload.get("lock_fields", True), bool):
                    raise ManualEditError("manual.invalid_fields")
                upload = form.get("cover")
                if upload is not None:
                    if not hasattr(upload, "read"):
                        raise ManualEditError("manual.cover_invalid")
                    cover = await upload.read(MAX_COVER_IMAGE_BYTES + 1)
                    await run_in_threadpool(KomgaClient.validate_cover_upload, cover)

            def process(client, target):
                patches, differences = plan_edits(
                    target, payload.get("changes", {}), payload.get("baseline", {}), payload.get("lock_fields", True)
                )
                if cover_all_books and not target.books:
                    raise ManualEditError("manual.cover_no_books")
                selected_cover = cover
                if cover_all_books and not selected_cover:
                    try:
                        selected_cover = client.get_current_series_cover(target.series.id)
                    except Exception as exc:
                        raise ManualEditError("manual.cover_unavailable") from exc
                if mode == "preview":
                    return {
                        "mode": "preview",
                        "differences": differences,
                        "cover": bool(selected_cover),
                        "cover_book_count": len(target.books) if cover_all_books else 0,
                        "writes": len(patches),
                        "book_count": len(target.books),
                    }
                result = apply_edits(
                    client, target, patches, selected_cover, cover_all_books, replace_series_cover=bool(cover)
                )
                result["mode"] = "apply"
                add_audit_entry(
                    "MANUAL_EDIT_PARTIAL" if result["failed"] else "MANUAL_EDIT",
                    json.dumps(
                        {
                            "user": username,
                            "library_id": library_id,
                            "series_id": series_id,
                            "book_id": book_id,
                            "applied": result["applied"],
                            "failed": result["failed"],
                        }
                    ),
                )
                try:
                    result["current"] = editor_values(load_target(client, library_id, series_id, book_id))
                except Exception:
                    result["refresh_failed"] = True
                return result

            return await run_in_threadpool(execute, library_id, series_id, book_id, process)
        except ManualEditError as exc:
            return error(exc.key, exc.status)
        except CoverImageError:
            return error("manual.cover_invalid", 422)
        except (ValueError, TypeError, AttributeError):
            return error("manual.invalid_fields", 422)
        except Exception:
            logger.warning("Could not complete manual metadata editing.")
            return error("manual.connection", 502)

    return router
