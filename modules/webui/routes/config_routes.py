# -*- coding: utf-8 -*-
"""
Settings routes.

GET  /settings?tab=…              → connection, defaults, automation or services
POST /settings/connection         → Komga address and API key
POST /settings/defaults           → default metadata rules and sources for every library
POST /settings/automation         → daily run, new-series watcher and automatic publishing
POST /settings/services           → external source credentials and translation settings
POST /settings/translation        → legacy translation form, preserved for compatibility
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
from modules.source_catalogue import compatible_sources
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
from modules.webui.i18n import t

logger = logging.getLogger(__name__)

TABS = ("connection", "defaults", "automation", "services")
LEGACY = {"komga": "connection", "system": "automation", "providers": "defaults", "processing": "defaults",
          "translation": "services"}


def _errors(exc: ValidationError) -> dict:
    return {".".join(str(part) for part in e["loc"]): e["msg"] for e in exc.errors()}


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def render(request: Request, username: str, tab: str, cfg: dict | None = None, error=None, success=False, submitted_keys=None):
        cfg = cfg if cfg is not None else (get_config_dict() or {})
        translation = cfg.get("translation") or {}
        stored = get_config_dict() or {}
        stored_translation = stored.get("translation") or {}
        context = {
            "username": username,
            "tab": tab,
            "cfg": cfg,
            "error": error,
            "success": success,
            "configured": config_exists(),
            "submitted_keys": submitted_keys or {},
            "saved_service_keys": {
                "googlebooks": bool(stored.get("google_books_api_key")),
                "deepl": bool((stored_translation.get("deepl") or {}).get("api_key")),
            },
        }
        if tab == "defaults":
            context.update(
                rules=rule_choices(cfg.get("processing", {})),
                processing=cfg.get("processing", {}),
                sources=ordered_sources(cfg.get("providers", [])),
                source_languages=SOURCE_LANGUAGES,
                available_sources=ordered_sources([{"name": name, "enabled": False} for name in compatible_sources("manga")
                                                   if name not in {s["name"] for s in cfg.get("providers", [])}]),
                google_books_ready=bool(cfg.get("google_books_api_key")),
            )
        if tab == "services":
            context.update(
                languages=language_options(translation.get("target_language")),
                language=language_value(translation.get("target_language")),
            )
        return templates.TemplateResponse(request=request, name="settings.html", context=context)

    def save(request, username, tab, raw, audit, submitted_keys=None):
        try:
            saved = save_config_to_db(raw)
        except ValidationError as exc:
            return render(request, username, tab, raw, error=_errors(exc), submitted_keys=submitted_keys)
        except Exception as exc:
            return render(request, username, tab, raw, error=str(exc), submitted_keys=submitted_keys)
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
        try:
            raw["providers"] = sources_patch(form, raw.get("providers", []))
        except ValueError:
            return render(request, username, "defaults", raw, error={"providers": t("sources.invalid_set")})
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

    @router.post("/settings/services", response_class=HTMLResponse)
    @router.post("/settings/translation", response_class=HTMLResponse)
    async def services(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        form = await request.form()
        raw = get_config_dict() or {}
        if request.url.path == "/settings/services" and form.get("section") in ("metadata", "all"):
            key = form.get("google_books_api_key", "").strip()
            if "remove_google_books_key" in form:
                raw["google_books_api_key"] = ""
            elif key:
                raw["google_books_api_key"] = key
            if form.get("section") == "metadata":
                return save(request, username, "services", raw, "External metadata services", {"google_books_api_key": key, "remove_google_books_key": "remove_google_books_key" in form})
        saved = raw.get("translation") or {}
        patch = {
            "enabled": "enabled" in form,
            "provider": form.get("provider", "google"),
            "target_language": form.get("target_language", "en-us"),
            "google_fallback": ("google_fallback" in form) if "translation_options_present" in form else saved.get("google_fallback", True),
        }
        key = form.get("deepl_api_key", "").strip()
        if "remove_deepl_key" in form:
            patch["deepl"] = None
        elif key:
            patch["deepl"] = {"api_key": key}
        elif saved.get("deepl"):
            patch["deepl"] = saved["deepl"]
        raw["translation"] = patch
        return save(request, username, "services", raw, "External services", {
            "deepl_api_key": key,
            "google_books_api_key": form.get("google_books_api_key", "").strip(),
            "remove_google_books_key": "remove_google_books_key" in form,
            "remove_deepl_key": "remove_deepl_key" in form,
        })

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
