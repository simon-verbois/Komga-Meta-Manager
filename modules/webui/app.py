# -*- coding: utf-8 -*-
"""
FastAPI application factory for the Komga Meta Manager Web UI.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlsplit
from fastapi.templating import Jinja2Templates

from modules.job_queue import JobQueue, get_job_queue
from modules.webui.i18n import make_translator
from modules.version import get_version
from modules.webui.routes import setup as setup_mod
from modules.webui.routes import auth_routes, config_routes, dashboard, libraries, logs, manual_metadata, review
from modules.webui.forms import language_options, language_value
from modules.webui.humanize import audit_text, nav_pending, plural

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    job_queue: Optional[JobQueue] = None,
    reload_callback: Optional[Callable] = None,
) -> FastAPI:
    """
    Build and return the FastAPI application.

    Args:
        job_queue: Shared persistent queue (defaults to the process-wide queue).
        reload_callback: Callable invoked with the new AppConfig on every config save.
    """
    version = get_version()
    queue = job_queue if job_queue is not None else get_job_queue()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        queue.start()
        try:
            yield
        finally:
            queue.close()

    app = FastAPI(title="Komga Meta Manager", version=version, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.job_queue = queue

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.globals["t"] = make_translator()
    templates.env.globals["app_version"] = version
    templates.env.globals["nav_pending"] = nav_pending
    templates.env.globals["plural"] = plural
    templates.env.globals["language_value"] = language_value
    templates.env.globals["language_options"] = language_options
    templates.env.filters["audit_text"] = audit_text

    # ------------------------------------------------------------------
    # Static files
    # ------------------------------------------------------------------
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    @app.middleware("http")
    async def protect_mutations(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            cross_site = request.headers.get("sec-fetch-site") == "cross-site"
            if cross_site or (origin and urlsplit(origin).netloc != request.url.netloc):
                return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    # ------------------------------------------------------------------
    # Register config reload callback
    # ------------------------------------------------------------------
    if reload_callback is not None:
        from modules.webui.config_store import register_reload_callback
        register_reload_callback(reload_callback)

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(setup_mod.setup_routes(templates))
    app.include_router(auth_routes.setup_routes(templates))
    app.include_router(dashboard.setup_routes(templates))
    app.include_router(config_routes.setup_routes(templates))
    app.include_router(logs.setup_routes(templates))
    app.include_router(libraries.setup_routes(templates))
    app.include_router(manual_metadata.setup_routes())
    app.include_router(review.setup_routes(templates))

    # ------------------------------------------------------------------
    # Global redirect handler: convert guard RedirectExc into response
    # ------------------------------------------------------------------
    from modules.webui.routes.guards import _redirect as RedirectExc

    @app.exception_handler(RedirectExc)
    async def _redirect_handler(request: Request, exc: RedirectExc):
        return exc.response

    logger.info("Web UI application created.")
    return app
