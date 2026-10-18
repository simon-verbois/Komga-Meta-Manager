# -*- coding: utf-8 -*-
"""
Dashboard routes.

GET  /                     → dashboard (status, controls)
POST /run-now              → trigger a manual job run (HTMX)
POST /toggle-dry-run       → flip dry_run flag (HTMX)
GET  /status               → JSON status fragment (HTMX polling)
"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pydantic import ValidationError

from modules.webui.config_store import get_config, save_config_to_db
from modules.webui.db import add_audit_entry, config_exists, user_exists
from modules.webui.routes.guards import get_current_user

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared job state (set by app.py via register_job_state)
# ---------------------------------------------------------------------------

class JobState:
    """Thread-safe container for the background job status."""

    def __init__(self):
        self._lock = threading.Lock()
        self.running: bool = False
        self.last_run_at: Optional[datetime] = None
        self.last_success: Optional[bool] = None

    def start(self):
        with self._lock:
            self.running = True

    def try_start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            return True

    def finish(self, success: bool):
        with self._lock:
            self.running = False
            self.last_run_at = datetime.now(timezone.utc)
            self.last_success = success

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
                "last_success": self.last_success,
            }


_job_state = JobState()
_run_job_fn: Optional[Callable] = None  # set by app.py


def register_job_runner(fn: Callable) -> None:
    """Register the function that runs the main processing job."""
    global _run_job_fn
    _run_job_fn = fn


def get_job_state() -> JobState:
    return _job_state


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not user_exists():
            return RedirectResponse("/setup", status_code=302)
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        if not config_exists():
            return RedirectResponse("/config/komga", status_code=302)

        cfg = get_config()
        next_run = None
        if cfg and cfg.system.scheduler.enabled:
            now = datetime.now()
            hour, minute = map(int, cfg.system.scheduler.run_at.split(":"))
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "scheduler_error": bool(request.query_params.get("scheduler_error")),
                "next_run": next_run,
                "username": username,
                "cfg": cfg,
                "job": _job_state.to_dict(),
            },
        )

    @router.post("/scheduler")
    async def save_scheduler(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/config/komga", status_code=302)
        form = await request.form()
        raw = cfg.model_dump(mode="json")
        raw["system"]["scheduler"] = {
            "enabled": "scheduler_enabled" in form,
            "run_at": form.get("run_at", "04:00"),
        }
        try:
            save_config_to_db(raw)
        except ValidationError:
            return RedirectResponse("/?scheduler_error=1", status_code=303)
        add_audit_entry("CONFIG_SAVE", f"Scheduler saved by '{username}'.")
        return RedirectResponse("/", status_code=303)

    @router.post("/dry-run", response_class=HTMLResponse)
    @router.post("/run-now", response_class=HTMLResponse)
    async def run_now(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)

        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/config/komga", status_code=302)

        cfg = cfg.model_copy(deep=True)
        if request.url.path == "/dry-run":
            cfg.system.dry_run = True

        if not _job_state.try_start():
            return templates.TemplateResponse(
                request=request,
                name="partials/job_status.html",
                context={"job": _job_state.to_dict()},
            )

        add_audit_entry(
            "DRY_RUN" if request.url.path == "/dry-run" else "RUN_NOW",
            f"Manual run triggered by '{username}' "
            f"(dry_run={cfg.system.dry_run})",
        )

        def _run():
            try:
                if _run_job_fn:
                    result = _run_job_fn(cfg)
                    success = getattr(result, "success", True)
                else:
                    logger.error("No job runner registered.")
                    success = False
            except Exception as exc:
                logger.error("Manual run failed: %s", exc, exc_info=True)
                success = False
            finally:
                _job_state.finish(success)

        t = threading.Thread(target=_run, daemon=True)
        try:
            t.start()
        except Exception:
            _job_state.finish(False)
            raise

        return templates.TemplateResponse(
            request=request,
            name="partials/job_status.html",
            context={"job": _job_state.to_dict()},
        )

    @router.post("/toggle-dry-run", response_class=HTMLResponse)
    async def toggle_dry_run(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)

        cfg = get_config()
        if cfg is None:
            return RedirectResponse("/config/komga", status_code=302)

        import json
        raw = json.loads(cfg.model_dump_json())
        raw["system"]["dry_run"] = not cfg.system.dry_run
        new_cfg = save_config_to_db(raw)

        add_audit_entry(
            "DRY_RUN_TOGGLE",
            f"dry_run set to {new_cfg.system.dry_run} by '{username}'",
        )
        logger.info("dry_run toggled to %s by '%s'.", new_cfg.system.dry_run, username)

        return templates.TemplateResponse(
            request=request,
            name="partials/dry_run_badge.html",
            context={"cfg": new_cfg},
        )

    @router.get("/status", response_class=HTMLResponse)
    async def status_fragment(request: Request):
        """HTMX polling endpoint — returns updated job status fragment."""
        username = get_current_user(request)
        if not username:
            return HTMLResponse("")
        return templates.TemplateResponse(
            request=request,
            name="partials/job_status.html",
            context={"job": _job_state.to_dict()},
        )

    return router
