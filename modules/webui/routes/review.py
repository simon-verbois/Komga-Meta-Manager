"""Review unpublished KMM changes, discard them, or publish them to Komga."""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from modules.book_numbering import numbering_version, plan_book_order, plan_numbering
from modules.config import config_for_library
from modules.local_metadata import local_edit_lock
from modules.manual_metadata import ManualEditError
from modules.models import KomgaSeries
from modules.webui.config_store import get_config
from modules.webui.db import add_audit_entry
from modules.webui.i18n import t
from modules.webui.routes.dashboard import back, catalogue_for, enqueue_job, known_libraries
from modules.webui.routes.guards import get_current_user


def setup_routes(templates) -> APIRouter:
    router = APIRouter(prefix="/review")

    @router.get("", response_class=HTMLResponse)
    async def page(request: Request, library: str | None = None):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        try:
            libraries = await run_in_threadpool(known_libraries, cfg)
        except Exception:
            libraries = []
        names = {lib.id: lib.name for lib in libraries}
        store = catalogue_for(cfg)
        counts = store.pending_counts()
        groups = store.pending_changes(library or None)
        for group in groups:
            group["library"] = names.get(group["library_id"], group["library_id"])
            group["series_items"] = [item for item in group["items"] if item["entity"] == "series"]
            group["books"] = sorted(
                (item for item in group["items"] if item["entity"] == "books"),
                key=lambda item: (item["number_sort"] is None, item["number_sort"] or 0, item["id"]),
            )
            group["change_count"] = sum(len(item["changes"]) for item in group["items"])
            series_row = store.get("series", group["series_id"])
            group["order_version"] = ""
            if series_row and group["books"]:
                series = KomgaSeries.model_validate_json(series_row["data"])
                books = sorted(store.items("books", series.library_id, series.id),
                               key=lambda book: (book.metadata.number_sort, book.id))
                settings = config_for_library(cfg, series.library_id).processing.book_titles
                group["order_version"] = numbering_version(series, books, settings)
        return templates.TemplateResponse(
            request=request,
            name="review.html",
            context={
                "username": username,
                "groups": groups,
                "filters": [
                    {"id": lib_id, "name": names.get(lib_id, lib_id), "count": count}
                    for lib_id, count in sorted(counts.items(), key=lambda item: names.get(item[0], item[0]).casefold())
                ],
                "library": library,
                "change_count": sum(len(item["changes"]) for group in groups for item in group["items"]),
                "queue": request.app.state.job_queue.snapshot(),
                "queued": request.query_params.get("queued"),
                "message": request.query_params.get("message"),
                "discarded": request.query_params.get("discarded"),
                "numbering_saved": request.query_params.get("numbering_saved"),
            },
        )

    @router.post("/reorder/{series_id}")
    async def reorder(request: Request, series_id: str, library: str | None = None):
        username = get_current_user(request)
        if not username:
            return JSONResponse({"error": t("manual.session")}, status_code=401)
        cfg = get_config()
        if cfg is None:
            return JSONResponse({"error": t("manual.connection")}, status_code=409)
        try:
            payload = await request.json()
            if (not isinstance(payload, dict) or not isinstance(payload.get("order"), list)
                    or any(not isinstance(identifier, str) for identifier in payload["order"])):
                raise ManualEditError("manual.invalid_fields")

            def run():
                with local_edit_lock():
                    store = catalogue_for(cfg)
                    row = store.get("series", series_id)
                    if row is None or (library and row["library_id"] != library):
                        raise ManualEditError("manual.missing", 404)
                    series = KomgaSeries.model_validate_json(row["data"])
                    books = sorted(store.items("books", series.library_id, series.id),
                                   key=lambda book: (book.metadata.number_sort, book.id))
                    settings = config_for_library(cfg, series.library_id).processing.book_titles
                    visible = {
                        item["id"] for group in store.pending_changes(series.library_id)
                        if group["series_id"] == series_id for item in group["items"] if item["entity"] == "books"
                    }
                    if (payload.get("version") != numbering_version(series, books, settings)
                            or set(payload["order"]) != visible):
                        raise ManualEditError("numbering.conflict", 409)
                    patches = plan_book_order(series, books, settings, payload["order"])
                    store.patch_many(patches, manual=True)
                    if patches:
                        add_audit_entry("MANUAL_EDIT", json.dumps({
                            "user": username, "library_id": series.library_id, "series_id": series.id,
                            "applied": [{"entity": "books", "id": patch["id"],
                                         "fields": [key for key in patch["payload"] if not key.endswith("Lock")]}
                                        for patch in patches], "failed": [],
                        }))

            await run_in_threadpool(run)
        except ManualEditError as exc:
            key = "numbering.order_conflict" if exc.key == "numbering.conflict" else exc.key
            return JSONResponse({"error": t(key)}, status_code=exc.status)
        except (ValueError, TypeError):
            return JSONResponse({"error": t("manual.invalid_fields")}, status_code=422)
        return await page(request, library)

    @router.api_route("/numbering/{series_id}", methods=["GET", "POST"], response_class=HTMLResponse)
    async def numbering(request: Request, series_id: str, library: str | None = None):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        form = await request.form() if request.method == "POST" else None

        def run():
            with local_edit_lock():
                store = catalogue_for(cfg)
                row = store.get("series", series_id)
                if row is None or (library and row["library_id"] != library):
                    raise HTTPException(status_code=404)
                series = KomgaSeries.model_validate_json(row["data"])
                books = sorted(store.items("books", series.library_id, series.id),
                               key=lambda book: (book.metadata.number_sort, book.id))
                settings = config_for_library(cfg, series.library_id).processing.book_titles
                version = numbering_version(series, books, settings)
                numbers = {book.id: str(book.metadata.number) for book in books}
                display_books = books
                error, status = None, 200
                if form is not None:
                    identifiers, values = form.getlist("book_id"), form.getlist("number")
                    submitted = dict(zip(identifiers, values))
                    numbers.update({key: value for key, value in submitted.items() if key in numbers})
                    # Keep the user's reordered list when validation or a stale
                    # baseline requires another save; append newly fetched books.
                    positions = {identifier: index for index, identifier in enumerate(identifiers)}
                    display_books = sorted(books, key=lambda book: positions.get(book.id, len(positions)))
                    try:
                        if (form.get("version") != version or len(identifiers) != len(set(identifiers))
                                or len(identifiers) != len(values)):
                            raise ManualEditError("numbering.conflict", 409)
                        patches = plan_numbering(series, books, settings, submitted)
                        store.patch_many(patches, manual=True)
                        if patches:
                            add_audit_entry("MANUAL_EDIT", json.dumps({
                                "user": username, "library_id": series.library_id, "series_id": series.id,
                                "applied": [{"entity": "books", "id": patch["id"],
                                             "fields": [key for key in patch["payload"] if not key.endswith("Lock")]}
                                            for patch in patches], "failed": [],
                            }))
                        return None
                    except ManualEditError as exc:
                        error, status = exc.key, exc.status
                rows = []
                for book in display_books:
                    baseline = store.get("books", book.id)
                    remote = json.loads(baseline["remote"]) if baseline["remote"] else {}
                    rows.append({"id": book.id, "title": remote.get("title") or book.name,
                                 "local_title": book.metadata.title, "number": numbers[book.id]})
                return {"series": series, "rows": rows, "version": version, "error": error, "status": status,
                        "naming_active": settings.mode != "off"}

        result = await run_in_threadpool(run)
        if result is None:
            return back("/review" + (f"?library={library}" if library else ""), numbering_saved=1)
        return templates.TemplateResponse(
            request=request, name="numbering.html", status_code=result.pop("status"),
            context={"username": username, "library": library, **result},
        )

    @router.post("/discard")
    async def discard(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        form = await request.form()
        series_id = form.get("series_id", "")
        target = "/review" + (f"?library={form.get('library')}" if form.get("library") else "")

        def run():
            with local_edit_lock():
                return catalogue_for(cfg).discard(
                    series_id, form.get("entity") or None, form.get("item_id") or None, form.get("field") or None
                )

        count = await run_in_threadpool(run)
        if count:
            add_audit_entry(
                "CHANGES_DISCARDED",
                f"{username} discarded {count} unpublished change(s) for series {form.get('title') or series_id}.",
            )
        return back(target, discarded=count)

    @router.post("/publish")
    async def publish(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        form = await request.form()
        library = form.get("library") or None
        target = "/review" + (f"?library={library}" if library else "")
        selected = set(form.getlist("series_id"))
        groups = catalogue_for(cfg).pending_changes(library)
        if selected:
            groups = [group for group in groups if group["series_id"] in selected]
        if not groups:
            return back(target, message="review.nothing")
        try:
            libraries = await run_in_threadpool(known_libraries, cfg)
        except Exception:
            return back(target, message="libraries.connection_error")
        names = {lib.id: lib.name for lib in libraries}
        library_names = sorted({names[g["library_id"]] for g in groups if g["library_id"] in names})
        series_ids = sorted({group["series_id"] for group in groups}) if selected or library else None
        job_id, error = enqueue_job(
            request, cfg, "publish", library_names, username, series_ids,
            detail=f" ({len(groups)} series)",
        )
        return back(target, queued=job_id, message=error)

    return router
