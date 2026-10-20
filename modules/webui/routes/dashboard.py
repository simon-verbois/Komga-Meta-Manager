# -*- coding: utf-8 -*-
"""
Home routes.

GET  /                     → library overview, next step and current activity
POST /fetch                → fetch metadata into KMM for one or all included libraries
POST /onboarding           → choose libraries on first use, then fetch them
GET  /status               → current activity fragment (HTMX polling)
POST /jobs/{id}/{action}   → cancel, stop, force stop, or retry a job
"""
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from modules.job_queue import QueueFullError
from modules.local_metadata import LocalCatalogue, LocalKomgaClient
from modules.komga_client import KomgaClient
from modules.webui.config_store import get_config, save_config_to_db
from modules.webui.db import add_audit_entry, config_exists, get_db, user_exists
from modules.webui.routes.guards import get_current_user
from modules.workflow import job_snapshot

logger = logging.getLogger(__name__)


def catalogue_for(cfg) -> LocalCatalogue:
    return LocalCatalogue(str(cfg.komga.url).rstrip("/"))


def known_libraries(cfg, refresh: bool = False) -> list:
    """Read libraries from the local catalogue, asking Komga only when nothing is known yet."""
    client = KomgaClient(cfg.komga)
    try:
        return LocalKomgaClient(client, refresh=refresh).get_libraries()
    finally:
        client.session.close()


def library_type(cfg, library) -> str:
    profile = cfg.library_settings.get(library.id)
    if profile:
        return profile.content_type
    return "ebook" if "ebook" in library.name.casefold().replace(" ", "").replace("-", "") else "manga"


def last_fetches(limit: int = 200) -> dict[str, str]:
    """Most recent successful fetch time per library name."""
    seen: dict[str, str] = {}
    with get_db() as conn:
        rows = conn.execute(
            "SELECT config, finished_at FROM jobs WHERE status='succeeded' ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    for row in rows:
        saved = json.loads(row["config"])
        system = saved.get("system", {})
        if system.get("workflow", "both") == "push" or system.get("dry_run"):
            continue
        for name in saved["komga"]["libraries"]:
            seen.setdefault(name, row["finished_at"])
    return seen


def enqueue_job(request: Request, cfg, action: str, libraries: list[str], username: str, series_ids=None,
                book_ids=None, detail: str = "", replace_edits: bool = False) -> tuple[int | None, str | None]:
    """Queue a real fetch or publish limited to the given libraries; return (job id, error key)."""
    snapshot = job_snapshot(cfg, action)
    snapshot.komga.libraries = libraries
    snapshot.system.overwrite_local = replace_edits
    try:
        job_id = request.app.state.job_queue.enqueue(snapshot, "manual", series_ids, book_ids)
    except QueueFullError:
        return None, "queue.full"
    except ValueError:
        return None, "queue.no_libraries"
    verb = {"fetch": "Fetch", "publish": "Publish", "fetch_publish": "Fetch and publish"}[action]
    add_audit_entry(
        "JOB_QUEUED", f"{verb} job #{job_id} for {', '.join(libraries)}{detail}"
        f"{' (replacing manual edits)' if replace_edits else ''}, queued by {username}."
    )
    return job_id, None


def back(path: str, **params) -> RedirectResponse:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    return RedirectResponse(path + ("&" if "?" in path else "?") + query if query else path, status_code=303)


def safe_next(value: str | None, default: str = "/") -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else default


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def activity(request: Request, message: str | None = None):
        return templates.TemplateResponse(
            request=request,
            name="partials/activity_strip.html",
            context={"queue": request.app.state.job_queue.snapshot(), "queue_message": message},
        )

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if not user_exists():
            return RedirectResponse("/setup", status_code=302)
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        if not config_exists():
            return RedirectResponse("/settings?tab=connection", status_code=302)

        cfg = get_config()
        connection_error = False
        try:
            libraries = await run_in_threadpool(known_libraries, cfg)
        except Exception:
            libraries, connection_error = [], True
        store = catalogue_for(cfg)
        pending, series, fetched = store.pending_counts(), store.series_counts(), last_fetches()
        rows = [
            {
                "id": lib.id,
                "name": lib.name,
                "type": library_type(cfg, lib),
                "included": lib.name in cfg.komga.libraries,
                "pending": pending.get(lib.id, 0),
                "series": series.get(lib.id, 0),
                "fetched": fetched.get(lib.name),
            }
            for lib in sorted(libraries, key=lambda lib: lib.name.casefold())
        ]
        next_run = None
        if cfg.system.scheduler.enabled:
            now = datetime.now()
            hour, minute = map(int, cfg.system.scheduler.run_at.split(":"))
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "username": username,
                "cfg": cfg,
                "rows": rows,
                "onboarding": bool(rows) and not cfg.komga.libraries and not any(r["series"] for r in rows),
                "pending_total": sum(r["pending"] for r in rows),
                "connection_error": connection_error,
                "next_run": next_run,
                "queue": request.app.state.job_queue.snapshot(),
                "queued": request.query_params.get("queued"),
                "message": request.query_params.get("message"),
            },
        )

    @router.post("/fetch")
    async def fetch(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        form = await request.form()
        target = safe_next(form.get("next"))
        names = cfg.komga.libraries
        if form.get("library_id"):
            try:
                libraries = await run_in_threadpool(known_libraries, cfg)
            except Exception:
                return back(target, message="libraries.connection_error")
            names = [lib.name for lib in libraries if lib.id == form.get("library_id")]
        job_id, error = enqueue_job(request, cfg, "fetch", names, username)
        return back(target, queued=job_id, message=error)

    @router.post("/onboarding")
    async def onboarding(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        form = await request.form()
        try:
            libraries = await run_in_threadpool(known_libraries, cfg, True)
        except Exception:
            return back("/", message="libraries.connection_error")
        chosen = set(form.getlist("library"))
        raw = cfg.model_dump(mode="json")
        raw["komga"]["libraries"] = [lib.name for lib in libraries if lib.id in chosen]
        for lib in libraries:
            kind = form.get(f"type_{lib.id}")
            if kind in ("manga", "webtoon", "ebook"):
                profile = raw["library_settings"].get(lib.id, {"name": lib.name})
                profile.update(name=lib.name, content_type=kind)
                raw["library_settings"][lib.id] = profile
        if not raw["komga"]["libraries"]:
            return back("/", message="onboarding.none")
        try:
            cfg = save_config_to_db(raw)
        except ValidationError:
            return back("/", message="libraries.validation_error")
        add_audit_entry("LIBRARY_SAVE", f"Libraries chosen by {username}: {', '.join(cfg.komga.libraries)}.")
        job_id, error = enqueue_job(request, cfg, "fetch", cfg.komga.libraries, username)
        return back("/", queued=job_id, message=error)

    @router.post("/jobs/{job_id}/{action}", response_class=HTMLResponse)
    async def job_action(request: Request, job_id: int, action: str):
        if not get_current_user(request):
            return RedirectResponse("/login", status_code=302)
        queue = request.app.state.job_queue
        message = None
        new_id = None
        try:
            if action == "retry":
                new_id = queue.retry(job_id)
                changed = new_id is not None
            elif action in ("cancel", "kill"):
                changed = await run_in_threadpool(queue.cancel, job_id, force=action == "kill")
            else:
                changed = False
            if not changed:
                message = "queue.action_unavailable"
        except QueueFullError:
            message = "queue.full"
        if request.headers.get("HX-Request"):
            return activity(request, message)
        form = await request.form()
        target = safe_next(form.get("next"), f"/logs/jobs/{new_id or job_id}")
        if new_id:
            target = f"/logs/jobs/{new_id}"
        return back(target, message=message)

    @router.get("/status", response_class=HTMLResponse)
    async def status_fragment(request: Request):
        """HTMX polling endpoint — returns the current activity fragment."""
        if not get_current_user(request):
            return HTMLResponse("")
        return activity(request)

    return router
