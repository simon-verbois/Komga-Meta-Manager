# -*- coding: utf-8 -*-
"""
Log viewer routes.

GET  /logs                    → logs page (tabs: Execution / Audit)
GET  /logs/exec/lines         → HTMX fragment: execution log lines
POST /logs/exec/clear         → clear execution log buffer
GET  /logs/audit/lines        → HTMX fragment: audit log lines (paginated)
"""
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from modules.webui import log_buffer
from modules.webui.db import count_audit_log, get_audit_log
from modules.webui.routes.guards import get_current_user

logger = logging.getLogger(__name__)


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/logs")

    @router.get("", response_class=HTMLResponse)
    @router.get("/", response_class=HTMLResponse)
    async def logs_page(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(
            request=request, name="logs.html", context={"username": username}
        )

    # ------------------------------------------------------------------
    # Execution log
    # ------------------------------------------------------------------
    @router.get("/exec/lines", response_class=HTMLResponse)
    async def exec_log_lines(
        request: Request,
        debug: bool = Query(default=False),
    ):
        username = get_current_user(request)
        if not username:
            return HTMLResponse("")
        lines = log_buffer.get_lines(include_debug=debug)
        return templates.TemplateResponse(
            request=request,
            name="partials/exec_log_lines.html",
            context={"lines": lines, "debug": debug},
        )

    @router.post("/exec/clear", response_class=HTMLResponse)
    async def exec_log_clear(request: Request):
        username = get_current_user(request)
        if not username:
            return HTMLResponse("")
        log_buffer.clear_buffer()
        return templates.TemplateResponse(
            request=request,
            name="partials/exec_log_lines.html",
            context={"lines": [], "debug": False},
        )

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    @router.get("/audit/lines", response_class=HTMLResponse)
    async def audit_log_lines(
        request: Request,
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=50, ge=1, le=200),
    ):
        username = get_current_user(request)
        if not username:
            return HTMLResponse("")
        offset = (page - 1) * per_page
        entries = get_audit_log(limit=per_page, offset=offset)
        total = count_audit_log()
        total_pages = max(1, (total + per_page - 1) // per_page)
        return templates.TemplateResponse(
            request=request,
            name="partials/audit_log_lines.html",
            context={
                "entries": entries,
                "page": page,
                "total_pages": total_pages,
            },
        )

    return router
