"""Library browsing, per-library settings inheriting the defaults, and targeted fetches."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from modules.config import BookTitleConfig, LibraryConfig, ProcessingConfig, ProviderConfig, config_for_library
from modules.local_metadata import LocalCatalogue, LocalKomgaClient, local_edit_lock
from modules.komga_client import KomgaClient
from modules.webui.config_store import get_config, save_config_to_db
from modules.webui.db import add_audit_entry
from modules.webui.forms import (
    LANGUAGES,
    SOURCE_LANGUAGES,
    language_options,
    language_value,
    ordered_sources,
    processing_patch,
    rule_choices,
    sources_patch,
)
from modules.webui.i18n import TRANSLATIONS
from modules.webui.routes.dashboard import back, catalogue_for, enqueue_job, known_libraries, library_type
from modules.webui.routes.guards import get_current_user

RULE_KEYS = ("overwrite_existing", "force_unlock", "update_fields", "remove_fields", "book_titles")


def library_content_type(config, library) -> str:
    """Honor the saved type and recognize ebook names for unconfigured libraries."""
    return library_type(config, library)


def _fetch(config, operation):
    client = KomgaClient(config.komga)
    try:
        return operation(client)
    finally:
        client.session.close()


def _rules(processing: dict) -> dict:
    data = ProcessingConfig.model_validate(processing).model_dump()
    return {key: data[key] for key in RULE_KEYS}


def _sources(providers: list[dict]) -> list[dict]:
    return sorted(
        (ProviderConfig.model_validate(source).model_dump() for source in providers), key=lambda s: s["priority"]
    )


def setup_routes(templates) -> APIRouter:
    router = APIRouter(prefix="/libraries")

    async def render(request, username, library_id=None, tab="content", error=None, success=False, submitted=None):
        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        libraries, connection_error = [], False
        try:
            libraries = await run_in_threadpool(known_libraries, cfg)
        except Exception:
            connection_error = True
        libraries = sorted(libraries, key=lambda lib: lib.name.casefold())
        selected = next((lib for lib in libraries if lib.id == library_id), None)
        if selected is None and libraries and not library_id:
            selected = next((lib for lib in libraries if lib.name in cfg.komga.libraries), libraries[0])
        store = catalogue_for(cfg)
        pending = store.pending_counts()
        context = {
            "username": username,
            "libraries": [
                {"id": lib.id, "name": lib.name, "included": lib.name in cfg.komga.libraries,
                 "pending": pending.get(lib.id, 0), "type": library_type(cfg, lib)}
                for lib in libraries
            ],
            "library": selected,
            "tab": tab,
            "connection_error": connection_error,
            "error": error,
            "success": success,
            "queued": request.query_params.get("queued"),
            "message": request.query_params.get("message"),
            "catalogue_notice": request.query_params.get("catalogue_notice"),
        }
        if selected:
            effective = config_for_library(cfg, selected.id).model_dump(mode="json")
            profile = cfg.library_settings.get(selected.id)
            defaults = cfg.model_dump(mode="json")
            translation = defaults.get("translation") or {}
            context.update(
                {
                    "content_type": library_type(cfg, selected),
                    "enabled": selected.name in cfg.komga.libraries,
                    "pending": pending.get(selected.id, 0),
                    "rules": rule_choices(effective["processing"]),
                    "processing": effective["processing"],
                    "rules_inherited": not profile or profile.processing is None,
                    "sources": ordered_sources(effective["providers"]),
                    "sources_inherited": not profile or profile.providers is None,
                    "source_languages": SOURCE_LANGUAGES,
                    "translation_mode": (
                        "default" if not profile or profile.translation_enabled is None
                        else ("on" if profile.translation_enabled else "off")
                    ),
                    "translation_default": bool(translation.get("enabled")),
                    "translation_configured": bool(translation),
                    "default_language": dict(LANGUAGES).get(
                        language_value(translation.get("target_language")), translation.get("target_language", "")
                    ),
                    "language": language_value(profile.target_language if profile and profile.target_language
                                               else translation.get("target_language")),
                    "languages": language_options(profile.target_language if profile else None),
                    **(submitted or {}),
                    "manual_messages": {
                        key.removeprefix("manual."): value
                        for key, value in TRANSLATIONS["en"].items()
                        if key.startswith("manual.")
                    },
                }
            )
        return templates.TemplateResponse(request=request, name="libraries.html", context=context)

    @router.get("", response_class=HTMLResponse)
    async def page(request: Request, library: str | None = None, tab: str = "content"):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        return await render(request, username, library, tab if tab in ("content", "sources", "settings") else "content",
                            success=bool(request.query_params.get("saved")))

    async def _library(cfg, library_id):
        libraries = await run_in_threadpool(_fetch, cfg, lambda client: LocalKomgaClient(client, refresh=False).get_libraries())
        return next((item for item in libraries if item.id == library_id), None)

    @router.post("/{library_id}/settings", response_class=HTMLResponse)
    async def save(request: Request, library_id: str):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if not cfg:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        form = await request.form()
        tab = "sources" if form.get("section") == "sources" else "settings"
        try:
            library = await _library(cfg, library_id)
        except Exception:
            return await render(request, username, library_id, tab, error="libraries.connection_error")
        if not library:
            return Response(status_code=404)
        raw = cfg.model_dump(mode="json")
        profile = raw["library_settings"].get(
            library_id, {"name": library.name, "content_type": library_type(cfg, library)}
        )
        profile["name"] = library.name
        reset = form.get("reset")
        submitted = None
        if reset == "rules":
            profile["processing"] = None
        elif reset == "sources":
            profile["providers"] = None
        elif tab == "sources":
            sources = sources_patch(form, profile.get("providers") or raw["providers"])
            submitted = {"sources": ordered_sources(sources)}
            try:
                same_sources = _sources(sources) == _sources(raw["providers"])
            except (ValueError, ValidationError):
                return await render(request, username, library_id, tab, error="libraries.validation_error",
                                    submitted=submitted)
            profile["providers"] = None if profile.get("providers") is None and same_sources else sources
        else:
            if "enabled" in form and library.name not in raw["komga"]["libraries"]:
                raw["komga"]["libraries"].append(library.name)
            elif "enabled" not in form:
                raw["komga"]["libraries"] = [name for name in raw["komga"]["libraries"] if name != library.name]
            if form.get("content_type") in ("manga", "webtoon", "ebook"):
                profile["content_type"] = form["content_type"]
            current = (profile.get("processing") or raw["processing"])
            rules = processing_patch(form, current)
            # Sources have their own form; saving Settings leaves their choices untouched.
            sources = profile.get("providers") or raw["providers"]
            mode = form.get("translation_mode", "default")
            language = form.get("target_language", "").strip()
            # Shown again on a validation error so the user's entries are kept.
            submitted = {
                "enabled": "enabled" in form,
                "content_type": form.get("content_type") if form.get("content_type") in ("manga", "webtoon", "ebook") else profile.get("content_type"),
                "rules": rule_choices(rules),
                "processing": rules,
                "sources": ordered_sources(sources),
                "translation_mode": mode if mode in ("default", "on", "off") else "default",
                "language": language,
            }
            try:
                BookTitleConfig.model_validate(rules["book_titles"])
            except (ValueError, ValidationError):
                return await render(request, username, library_id, "settings", error="titles.invalid",
                                    submitted=submitted)
            try:
                same_rules = _rules(rules) == _rules(raw["processing"])
                same_sources = _sources(sources) == _sources(raw["providers"])
            except (ValueError, ValidationError):
                return await render(request, username, library_id, "settings", error="libraries.validation_error",
                                    submitted=submitted)
            # Settings identical to the defaults keep following future default changes.
            profile["processing"] = None if profile.get("processing") is None and same_rules else rules
            profile["providers"] = None if profile.get("providers") is None and same_sources else sources
            profile["translation_enabled"] = {"on": True, "off": False}.get(mode)
            profile["target_language"] = language if mode == "on" and language else None
        try:
            raw["library_settings"][library_id] = LibraryConfig.model_validate(profile).model_dump()
            candidate = type(cfg).model_validate(raw)
            effective = config_for_library(candidate, library_id)
            if effective.translation:
                type(effective.translation).model_validate(effective.translation.model_dump())
            save_config_to_db(raw)
            what = {"rules": "rules reset to defaults", "sources": "sources reset to defaults"}.get(reset, "settings saved")
            add_audit_entry("LIBRARY_SAVE", f"{library.name}: {what} by {username}.")
        except (ValueError, ValidationError):
            return await render(request, username, library_id, tab, error="libraries.validation_error",
                                submitted=None if reset else submitted)
        return back(f"/libraries?library={library_id}&tab={tab}", saved=1)

    @router.post("/{library_id}/fetch")
    async def fetch(request: Request, library_id: str):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if not cfg:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        form = await request.form()
        target = f"/libraries?library={library_id}"
        series_id, book_id = form.get("series_id") or None, form.get("book_id") or None
        try:
            def verify(client):
                library = next((lib for lib in LocalKomgaClient(client, refresh=False).get_libraries() if lib.id == library_id), None)
                if not library:
                    raise ValueError("Unknown library")
                if series_id and library_type(cfg, library) == "ebook" and not book_id:
                    raise ValueError("Ebook fetches target one book")
                if series_id:
                    series = next((s for s in client.get_series_in_library(library.id, library.name) if s.id == series_id), None)
                    if not series or series.library_id != library.id:
                        raise ValueError("Unknown series")
                    if book_id and book_id not in {b.id for b in client.get_books_in_series(series.id, series.name)}:
                        raise ValueError("Unknown book")
                return library

            library = await run_in_threadpool(_fetch, cfg, verify)
        except Exception:
            return back(target, message="libraries.fetch_error")
        snapshot = cfg.model_copy(deep=True)
        detail = ""
        if series_id:
            # A targeted fetch asks the sources again; results still wait in Review before publishing.
            profile = snapshot.library_settings.get(library_id)
            (profile.processing if profile and profile.processing else snapshot.processing).overwrite_existing = True
            detail = f", series {series_id}" + (f", book {book_id}" if book_id else "")
        job_id, error = enqueue_job(
            request, snapshot, "fetch", [library.name], username,
            [series_id] if series_id else None, [book_id] if book_id else None, detail,
            replace_edits=bool(series_id) and "replace_edits" in form,
        )
        return back(target, queued=job_id, message=error)

    @router.post("/{library_id}/skip")
    async def skip(request: Request, library_id: str):
        username = get_current_user(request)
        if not username:
            return JSONResponse({"error": "manual.session"}, status_code=401)
        cfg = get_config()
        if not cfg:
            return JSONResponse({"error": "manual.connection"}, status_code=409)
        form = await request.form()
        name = (form.get("series_name") or "").strip()
        skip = form.get("skip") == "1"
        try:
            library = await _library(cfg, library_id)
        except Exception:
            library = None
        if not library or not name:
            return JSONResponse({"error": "manual.missing"}, status_code=404)
        raw = cfg.model_dump(mode="json")
        profile = raw["library_settings"].get(library_id, {"name": library.name, "content_type": library_type(cfg, library)})
        names = [item for item in profile.get("exclude_series", []) if item != name]
        if skip:
            names.append(name)
        elif profile.get("processing"):
            profile["processing"]["exclude_series"] = [
                item for item in profile["processing"]["exclude_series"] if item != name
            ]
        profile["exclude_series"] = names
        raw["library_settings"][library_id] = LibraryConfig.model_validate(profile).model_dump()
        if not skip and name in raw["processing"]["exclude_series"]:
            raw["processing"]["exclude_series"].remove(name)
        save_config_to_db(raw)
        add_audit_entry("LIBRARY_SAVE", f"{library.name}: {'skipping' if skip else 'no longer skipping'} {name} ({username}).")
        return {"skipped": skip}

    @router.post("/{library_id}/check")
    @router.post("/{library_id}/remove-missing")
    async def check_catalogue(request: Request, library_id: str):
        if not get_current_user(request):
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if not cfg:
            return Response(status_code=404)
        form = await request.form()
        removing = request.url.path.endswith("/remove-missing")
        series_id = str(form.get("series_id", ""))

        def check(client):
            with local_edit_lock():
                library = next((lib for lib in client.get_libraries() if lib.id == library_id), None)
                if library is None:
                    raise ValueError("Unknown library")
                present = {
                    item.id for item in client.get_series_in_library(library_id, library.name)
                    if item.library_id == library_id
                }
                store = LocalCatalogue(client.base_url)
                store.reconcile_series(library_id, present)
                if removing:
                    if series_id in present or not store.remove_missing_series(library_id, series_id):
                        return "libraries.remove_unavailable"
                    add_audit_entry("catalogue_remove", f"Removed missing local series {series_id} from library {library_id}")
                return None

        try:
            error = await run_in_threadpool(_fetch, cfg, check)
        except Exception:
            error = "libraries.check_error"
        target = f"/libraries?library={library_id}"
        if error:
            return back(target, message=error)
        return back(target, catalogue_notice="libraries.removed" if removing else "libraries.checked")

    @router.get("/{library_id}/content", response_class=HTMLResponse)
    async def content(request: Request, library_id: str):
        if not get_current_user(request):
            return Response(status_code=401)
        cfg = get_config()
        if not cfg:
            return Response(status_code=404)
        excluded = set(config_for_library(cfg, library_id).processing.exclude_series)

        def fetch(client):
            client = LocalKomgaClient(client, refresh=False)
            library = next((lib for lib in client.get_libraries() if lib.id == library_id), None)
            if not library:
                raise ValueError("Unknown library")
            rows = []
            is_ebook = library_type(cfg, library) == "ebook"
            for series in client.get_series_in_library(library.id, library.name):
                if series.library_id != library.id:
                    continue
                if is_ebook:
                    for book in client.get_books_in_series(series.id, series.name):
                        rows.append({"book": book, "series": series})
                else:
                    rows.append({"book": None, "series": series})
            pending = client.store.pending_ids(library_id)
            missing = client.store.missing_series_ids(library_id)
            for row in rows:
                item = row["book"] or row["series"]
                meta = item.metadata
                row["pending"] = ("series", row["series"].id) in pending
                if row["book"]:
                    row["pending"] |= ("books", row["book"].id) in pending
                else:
                    row["pending"] |= ("book_series", row["series"].id) in pending
                row["skipped"] = row["series"].name in excluded
                row["missing_summary"] = not (meta.summary or "").strip()
                row["locked"] = any(
                    value for key, value in meta.model_dump().items() if key.endswith("_lock")
                )
                row["title"] = meta.title or item.name
                row["absent"] = row["series"].id in missing
            rows.sort(key=lambda row: row["title"].casefold())
            return library, rows, is_ebook

        try:
            library, rows, is_ebook = await run_in_threadpool(_fetch, cfg, fetch)
        except Exception:
            return templates.TemplateResponse(
                request=request,
                name="partials/library_content.html",
                context={"content_error": True, "library_id": library_id},
            )
        return templates.TemplateResponse(
            request=request,
            name="partials/library_content.html",
            context={
                "rows": rows,
                "is_ebook": is_ebook,
                "library_id": library_id,
                "enabled": library.name in cfg.komga.libraries,
            },
        )

    @router.get("/{library_id}/{entity}/{item_id}/thumbnail")
    async def thumbnail(request: Request, library_id: str, entity: Literal["books", "series"], item_id: str,
                        komga: bool = False):
        if not get_current_user(request):
            return Response(status_code=401)
        cfg = get_config()
        if not cfg:
            return Response(status_code=404)

        def fetch(client):
            local = LocalCatalogue(client.base_url).get(entity, item_id)
            # ?komga=1 shows the cover currently in Komga, for before/after comparisons.
            if not komga and local and local["library_id"] == library_id and local["cover"] not in (None, "remove"):
                import base64
                data = base64.b64decode(local["cover"])
                return data, KomgaClient.validate_cover_upload(data)
            # Read from the saved server only, never accept an arbitrary remote URL.
            response = client.session.get(
                f"{client.base_url}/api/v1/{entity}/{item_id}/thumbnail",
                headers={**client.headers, "Accept": "image/*"},
                verify=client.verify_ssl,
                timeout=(5, 20),
            )
            try:
                response.raise_for_status()
                return response.content, response.headers.get("content-type", "image/jpeg")
            finally:
                response.close()

        try:
            data, mime = await run_in_threadpool(_fetch, cfg, fetch)
            return Response(data, media_type=mime if mime.startswith("image/") else "image/jpeg")
        except Exception:
            return Response(status_code=404)

    return router
