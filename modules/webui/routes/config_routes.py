# -*- coding: utf-8 -*-
"""
Settings routes.

GET  /settings?tab=…              → connection, defaults, automation or translation
POST /settings/connection         → Komga address and API key
POST /settings/defaults           → default metadata rules and sources for every library
POST /settings/automation         → daily run, new-series watcher and automatic publishing
POST /settings/translation        → summary translation service and default language
POST /config/komga/libraries      → test a connection by listing its libraries (JSON)
GET  /config/…                    → legacy addresses, redirected to the matching tab
"""
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
from modules.webui.forms import (
    SOURCE_LANGUAGES,
    language_options,
    language_value,
    ordered_sources,
    processing_patch,
    rule_choices,
    sources_patch,
)
from modules.webui.routes.guards import get_current_user

logger = logging.getLogger(__name__)

TABS = ("connection", "defaults", "automation", "translation")
LEGACY = {"komga": "connection", "system": "automation", "providers": "defaults", "processing": "defaults",
          "translation": "translation"}


def _errors(exc: ValidationError) -> dict:
    return {".".join(str(part) for part in e["loc"]): e["msg"] for e in exc.errors()}


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def render(request: Request, username: str, tab: str, cfg: dict | None = None, error=None, success=False):
        cfg = cfg if cfg is not None else (get_config_dict() or {})
        translation = cfg.get("translation") or {}
        context = {
            "username": username,
            "tab": tab,
            "cfg": cfg,
            "error": error,
            "success": success,
            "configured": config_exists(),
        }
        if tab == "defaults":
            context.update(
                rules=rule_choices(cfg.get("processing", {})),
                processing=cfg.get("processing", {}),
                sources=ordered_sources(cfg.get("providers", [])),
                source_languages=SOURCE_LANGUAGES,
            )
        if tab == "translation":
            context.update(
                languages=language_options(translation.get("target_language")),
                language=language_value(translation.get("target_language")),
            )
        return templates.TemplateResponse(request=request, name="settings.html", context=context)

    def save(request, username, tab, raw, audit):
        try:
            saved = save_config_to_db(raw)
        except ValidationError as exc:
            return render(request, username, tab, raw, error=_errors(exc))
        except Exception as exc:
            return render(request, username, tab, raw, error=str(exc))
        add_audit_entry("CONFIG_SAVE", f"{audit} saved by {username}.")
        return RedirectResponse(f"/settings?tab={tab}&saved=1", status_code=303) if saved else None

    @router.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request, tab: str = "connection"):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        tab = LEGACY.get(tab, tab)
        if tab not in TABS or (tab != "connection" and not config_exists()):
            tab = "connection"
        return render(request, username, tab, success=bool(request.query_params.get("saved")))

    @router.post("/settings/connection", response_class=HTMLResponse)
    async def connection(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        first_time = not config_exists()
        form = await request.form()
        raw = get_config_dict() or {}
        raw["komga"] = {
            **raw.get("komga", {}),
            "url": form.get("url", "").strip(),
            "api_key": form.get("api_key", "").strip(),
            "verify_ssl": "verify_ssl" in form,
        }
        raw["komga"].setdefault("libraries", [])
        response = save(request, username, "connection", raw, "Komga connection")
        if first_time and isinstance(response, RedirectResponse):
            # First connection: continue with choosing libraries on Home.
            return RedirectResponse("/", status_code=303)
        return response

    @router.post("/settings/defaults", response_class=HTMLResponse)
    async def defaults(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        form = await request.form()
        raw = get_config_dict() or {}
        raw["processing"] = processing_patch(form, raw.get("processing"))
        raw["providers"] = sources_patch(form, raw.get("providers", []))
        return save(request, username, "defaults", raw, "Default rules and sources")

    @router.post("/settings/automation", response_class=HTMLResponse)
    async def automation(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        form = await request.form()
        raw = get_config_dict() or {}
        system = raw.get("system", {})
        raw["system"] = {
            **system,
            "auto_publish": form.get("after_fetch") == "publish",
            "scheduler": {"enabled": "scheduler_enabled" in form, "run_at": form.get("run_at", "04:00")},
            "watcher": {
                "enabled": "watcher_enabled" in form,
                "polling_interval_minutes": form.get("polling_interval_minutes", "5"),
            },
        }
        return save(request, username, "automation", raw, "Automation")

    @router.post("/settings/translation", response_class=HTMLResponse)
    async def translation(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        form = await request.form()
        raw = get_config_dict() or {}
        saved = raw.get("translation") or {}
        patch = {
            "enabled": "enabled" in form,
            "provider": form.get("provider", "google"),
            "target_language": form.get("target_language", "en-us"),
        }
        key = form.get("deepl_api_key", "").strip()
        if key:
            patch["deepl"] = {"api_key": key}
        elif saved.get("deepl"):
            patch["deepl"] = saved["deepl"]
        raw["translation"] = patch
        return save(request, username, "translation", raw, "Translation")

    @router.post("/config/komga/libraries")
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

    @router.get("/config", response_class=HTMLResponse)
    @router.get("/config/", response_class=HTMLResponse)
    @router.get("/config/{section}", response_class=HTMLResponse)
    async def legacy(request: Request, section: str = "komga"):
        if not get_current_user(request):
            return RedirectResponse("/login", status_code=302)
        return RedirectResponse(f"/settings?tab={LEGACY.get(section, 'connection')}", status_code=302)

    return router
