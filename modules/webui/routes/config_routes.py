# -*- coding: utf-8 -*-
"""
Configuration routes — one GET+POST per config section.

Sections:
  /config/system
  /config/komga
  /config/providers
  /config/processing
  /config/translation
"""
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from modules.config import KomgaConfig
from modules.komga_client import KomgaClient
from modules.webui.config_store import get_config_dict, save_config_to_db
from modules.webui.db import add_audit_entry, config_exists
from modules.webui.routes.guards import get_current_user

logger = logging.getLogger(__name__)

SECTIONS = ["system", "komga", "providers", "processing", "translation"]


def _base_ctx(request: Request, section: str, username: str) -> dict:
    return {
        "request": request,
        "username": username,
        "section": section,
        "sections": SECTIONS,
        "cfg": get_config_dict() or {},
        "error": None,
        "success": False,
        "errors": {},
    }


def _merge_and_save(section: str, patch: dict, username: str) -> tuple[dict | None, str | None]:
    """
    Merge *patch* into the current config dict, validate, and save.
    Returns (new_cfg_dict, error_message) — error_message is None on success.
    """
    current = get_config_dict() or {}
    current[section] = patch
    try:
        new_cfg = save_config_to_db(current)
        add_audit_entry("CONFIG_SAVE", f"Section '{section}' saved by '{username}'.")
        return json.loads(new_cfg.model_dump_json()), None
    except ValidationError as exc:
        errors = {e["loc"][-1]: e["msg"] for e in exc.errors()}
        return None, errors
    except Exception as exc:
        return None, str(exc)


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/config")

    # ------------------------------------------------------------------
    # /config  — redirect to system (or komga if not configured)
    # ------------------------------------------------------------------
    @router.get("", response_class=HTMLResponse)
    @router.get("/", response_class=HTMLResponse)
    async def config_index(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        if not config_exists():
            return RedirectResponse("/config/komga", status_code=302)
        return RedirectResponse("/config/system", status_code=302)

    # ------------------------------------------------------------------
    # SYSTEM
    # ------------------------------------------------------------------
    @router.get("/system", response_class=HTMLResponse)
    async def system_get(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        if not config_exists():
            return RedirectResponse("/config/komga", status_code=302)
        ctx = _base_ctx(request, "system", username)
        return templates.TemplateResponse(request=request, name="config/system.html", context=ctx)

    @router.post("/system", response_class=HTMLResponse)
    async def system_post(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)

        form = await request.form()
        patch = {
            "dry_run": "dry_run" in form,
            "debug": "debug" in form,
            "scheduler": {
                "enabled": "scheduler_enabled" in form,
                "run_at": form.get("run_at", "04:00"),
            },
            "watcher": {
                "enabled": "watcher_enabled" in form,
                "polling_interval_minutes": form.get("polling_interval_minutes", "5"),
            },
        }
        new_dict, err = _merge_and_save("system", patch, username)
        ctx = _base_ctx(request, "system", username)
        if err:
            ctx["error"] = err
            ctx["cfg"]["system"] = patch
        else:
            ctx["cfg"] = new_dict
            ctx["success"] = True
        return templates.TemplateResponse(request=request, name="config/system.html", context=ctx)

    # ------------------------------------------------------------------
    # KOMGA
    # ------------------------------------------------------------------
    @router.post("/komga/libraries")
    async def komga_libraries(request: Request):
        if not get_current_user(request):
            return RedirectResponse("/login", status_code=302)
        form = await request.form()
        try:
            connection = KomgaConfig(
                url=form.get("url", ""),
                api_key=form.get("api_key", ""),
                verify_ssl="verify_ssl" in form,
            )
        except ValidationError:
            return JSONResponse({"error": "invalid_connection"}, status_code=422)

        def fetch_libraries():
            client = KomgaClient(connection)
            try:
                return [lib.model_dump() for lib in client.get_libraries()]
            finally:
                client.session.close()

        try:
            libraries = await run_in_threadpool(fetch_libraries)
        except Exception:
            # Do not expose connection details or credentials in the response.
            logger.warning("Could not fetch libraries from Komga.")
            return JSONResponse({"error": "fetch_failed"}, status_code=502)
        return {"libraries": libraries}

    @router.get("/komga", response_class=HTMLResponse)
    async def komga_get(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        ctx = _base_ctx(request, "komga", username)
        return templates.TemplateResponse(request=request, name="config/komga.html", context=ctx)

    @router.post("/komga", response_class=HTMLResponse)
    async def komga_post(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)

        form = await request.form()
        if form.get("library_selection") == "checkboxes":
            libraries = list(dict.fromkeys(form.getlist("enabled_libraries")))
        else:
            # Preserve compatibility with existing clients that submit names by line.
            raw_libs = form.get("libraries", "")
            libraries = [line.strip() for line in raw_libs.splitlines() if line.strip()]

        patch = {
            "url": form.get("url", ""),
            "api_key": form.get("api_key", ""),
            "libraries": libraries,
            "verify_ssl": "verify_ssl" in form,
        }
        new_dict, err = _merge_and_save("komga", patch, username)
        ctx = _base_ctx(request, "komga", username)
        if err:
            ctx["error"] = err
            ctx["cfg"]["komga"] = patch
        else:
            ctx["cfg"] = new_dict
            ctx["success"] = True
        return templates.TemplateResponse(request=request, name="config/komga.html", context=ctx)

    # ------------------------------------------------------------------
    # PROVIDERS
    # ------------------------------------------------------------------
    @router.get("/providers", response_class=HTMLResponse)
    async def providers_get(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        if not config_exists():
            return RedirectResponse("/config/komga", status_code=302)
        ctx = _base_ctx(request, "providers", username)
        return templates.TemplateResponse(request=request, name="config/providers.html", context=ctx)

    @router.post("/providers", response_class=HTMLResponse)
    async def providers_post(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)

        form = await request.form()
        provider_names = ["anilist", "mangadex", "mangaupdates"]
        providers = []
        for name in provider_names:
            providers.append({
                "name": name,
                "priority": form.get(f"{name}_priority", str(len(providers) + 1)),
                "min_score": form.get(f"{name}_min_score", "80"),
                "allow_adult": f"{name}_allow_adult" in form,
                "preferred_language": form.get(f"{name}_preferred_language", "en"),
                "cache": {
                    "ttl_hours": form.get(f"{name}_cache_ttl", "168"),
                },
            })

        current = get_config_dict() or {}
        current["providers"] = providers
        try:
            new_cfg = save_config_to_db(current)
            add_audit_entry("CONFIG_SAVE", f"Section 'providers' saved by '{username}'.")
            ctx = _base_ctx(request, "providers", username)
            ctx["cfg"] = json.loads(new_cfg.model_dump_json())
            ctx["success"] = True
        except Exception as exc:
            ctx = _base_ctx(request, "providers", username)
            ctx["error"] = ({".".join(map(str, e["loc"])): e["msg"] for e in exc.errors()}
                            if isinstance(exc, ValidationError) else str(exc))
            ctx["cfg"]["providers"] = providers
        return templates.TemplateResponse(request=request, name="config/providers.html", context=ctx)

    # ------------------------------------------------------------------
    # PROCESSING
    # ------------------------------------------------------------------
    @router.get("/processing", response_class=HTMLResponse)
    async def processing_get(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        if not config_exists():
            return RedirectResponse("/config/komga", status_code=302)
        ctx = _base_ctx(request, "processing", username)
        return templates.TemplateResponse(request=request, name="config/processing.html", context=ctx)

    @router.post("/processing", response_class=HTMLResponse)
    async def processing_post(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)

        form = await request.form()
        raw_exclude = form.get("exclude_series", "")
        exclude = [s.strip() for s in raw_exclude.splitlines() if s.strip()]

        patch = {
            "overwrite_existing": "overwrite_existing" in form,
            "force_unlock": "force_unlock" in form,
            "exclude_series": exclude,
            "update_fields": {
                "summary": "uf_summary" in form,
                "publisher": "uf_publisher" in form,
                "genres": "uf_genres" in form,
                "status": "uf_status" in form,
                "cover_image": "uf_cover_image" in form,
                "link": "uf_link" in form,
                "authors": {
                    "writers": "uf_authors_writers" in form,
                    "pencillers": "uf_authors_pencillers" in form,
                },
                "tags": {"score": "uf_tags_score" in form},
            },
            "remove_fields": {
                "summary": "rf_summary" in form,
                "publisher": "rf_publisher" in form,
                "language": "rf_language" in form,
                "reading_direction": "rf_reading_direction" in form,
                "genres": "rf_genres" in form,
                "status": "rf_status" in form,
                "cover_image": "rf_cover_image" in form,
                "link": "rf_link" in form,
                "authors": {
                    "writers": "rf_authors_writers" in form,
                    "pencillers": "rf_authors_pencillers" in form,
                },
                "tags": {"score": "rf_tags_score" in form},
            },
        }
        new_dict, err = _merge_and_save("processing", patch, username)
        ctx = _base_ctx(request, "processing", username)
        if err:
            ctx["error"] = err
            ctx["cfg"]["processing"] = patch
        else:
            ctx["cfg"] = new_dict
            ctx["success"] = True
        return templates.TemplateResponse(request=request, name="config/processing.html", context=ctx)

    # ------------------------------------------------------------------
    # TRANSLATION
    # ------------------------------------------------------------------
    @router.get("/translation", response_class=HTMLResponse)
    async def translation_get(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        if not config_exists():
            return RedirectResponse("/config/komga", status_code=302)
        ctx = _base_ctx(request, "translation", username)
        return templates.TemplateResponse(request=request, name="config/translation.html", context=ctx)

    @router.post("/translation", response_class=HTMLResponse)
    async def translation_post(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)

        form = await request.form()
        enabled = "enabled" in form
        provider = form.get("provider", "google")
        target_language = form.get("target_language", "EN-US")
        deepl_key = form.get("deepl_api_key", "")

        patch: dict = {
            "enabled": enabled,
            "provider": provider,
            "target_language": target_language,
        }
        if provider == "deepl" and deepl_key.strip():
            patch["deepl"] = {"api_key": deepl_key.strip()}

        new_dict, err = _merge_and_save("translation", patch, username)
        ctx = _base_ctx(request, "translation", username)
        if err:
            ctx["error"] = err
            ctx["cfg"]["translation"] = patch
        else:
            ctx["cfg"] = new_dict
            ctx["success"] = True
        return templates.TemplateResponse(request=request, name="config/translation.html", context=ctx)

    return router
