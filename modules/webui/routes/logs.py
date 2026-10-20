# -*- coding: utf-8 -*-
"""
Log viewer routes.

GET  /logs                    → logs page (tabs: Execution / Audit)
GET  /logs/exec/lines         → HTMX fragment: execution log lines
POST /logs/exec/clear         → clear execution log buffer
GET  /logs/audit/lines        → HTMX fragment: audit log lines (paginated)
"""
import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from modules.job_queue import job_kind
from modules.webui import log_buffer
from modules.webui.db import count_audit_log, get_audit_log, get_db
from modules.webui.routes.guards import get_current_user

logger = logging.getLogger(__name__)


def describe_job(row) -> dict:
    """Summarize a stored job without exposing its saved settings or secrets."""
    saved = json.loads(row["config"])
    ids = json.loads(row["series_ids"]) if row["series_ids"] else None
    return {
        **{key: row[key] for key in ("id", "status", "source", "created_at", "started_at", "finished_at",
                                     "processed", "failed", "skipped")},
        **job_kind(saved),
        "libraries": saved["komga"]["libraries"],
        "series_count": len(ids) if ids is not None else None,
        "replace_edits": bool(saved.get("system", {}).get("overwrite_local")),
    }


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/logs")

    @router.get("", response_class=HTMLResponse)
    @router.get("/", response_class=HTMLResponse)
    async def logs_page(request: Request, tab: str = "jobs"):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        tab = {"exec": "technical", "audit": "history"}.get(tab, tab)
        return templates.TemplateResponse(
            request=request,
            name="logs.html",
            context={
                "username": username,
                "tab": tab if tab in ("jobs", "history", "technical") else "jobs",
                "log_levels": log_buffer.LOG_LEVELS,
                "default_log_levels": log_buffer.DEFAULT_LOG_LEVELS,
            },
        )

    @router.get("/jobs/list", response_class=HTMLResponse)
    async def job_list(request: Request, page: int = Query(default=1, ge=1)):
        if not get_current_user(request):
            return HTMLResponse("")
        with get_db() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 25 OFFSET ?", ((page - 1) * 25,)).fetchall()
        jobs = [describe_job(row) for row in rows]
        return templates.TemplateResponse(request=request, name="partials/jobs_list.html", context={
            "jobs": jobs, "page": page, "total_pages": max(1, (total + 24) // 25),
            "active": any(job["status"] in ("queued", "running", "stopping") for job in jobs),
        })

    # ------------------------------------------------------------------
    # Execution log
    # ------------------------------------------------------------------
    @router.get("/exec/lines", response_class=HTMLResponse)
    async def exec_log_lines(
        request: Request,
        levels: list[log_buffer.LogLevel] | None = Query(default=None),
        filtered: bool = Query(default=False),
    ):
        username = get_current_user(request)
        if not username:
            return HTMLResponse("")
        selected = levels if levels is not None else ([] if filtered else log_buffer.DEFAULT_LOG_LEVELS)
        lines = log_buffer.get_lines(levels=selected)
        return templates.TemplateResponse(
            request=request,
            name="partials/exec_log_lines.html",
            context={"lines": lines, "has_logs": bool(log_buffer.get_lines(levels=log_buffer.LOG_LEVELS))},
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
            context={"lines": [], "has_logs": False},
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

    @router.get("/jobs", response_class=HTMLResponse)
    async def job_history(request: Request):
        return RedirectResponse("/logs", status_code=302)

    @router.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail(request: Request, job_id: int):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        with get_db() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return HTMLResponse(status_code=404)
            total = conn.execute("SELECT COUNT(*) FROM job_logs WHERE job_id=?", (job_id,)).fetchone()[0]
            problems = conn.execute(
                "SELECT COUNT(*) FROM job_logs WHERE job_id=? AND level IN ('WARNING', 'ERROR', 'CRITICAL')", (job_id,)
            ).fetchone()[0]
        job = describe_job(row)
        return templates.TemplateResponse(request=request, name="job_detail.html", context={
            "username": username, "job": job, "log_count": total, "problems": problems,
            "log_levels": log_buffer.LOG_LEVELS, "default_log_levels": log_buffer.DEFAULT_LOG_LEVELS,
            "message": request.query_params.get("message"),
        })

    @router.get("/jobs/{job_id}/lines", response_class=HTMLResponse)
    async def job_lines(
        request: Request,
        job_id: int,
        page: int | None = Query(default=None, ge=1),
        levels: list[log_buffer.LogLevel] | None = Query(default=None),
        filtered: bool = Query(default=False),
    ):
        if not get_current_user(request):
            return HTMLResponse(status_code=401)
        selected = levels if levels is not None else ([] if filtered else log_buffer.DEFAULT_LOG_LEVELS)
        with get_db() as conn:
            job = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                return HTMLResponse(status_code=404)
            total = conn.execute("SELECT COUNT(*) FROM job_logs WHERE job_id=?", (job_id,)).fetchone()[0]
            # Filter before limiting: DEBUG messages must not crowd visible lines
            # out of the latest window. Explicit page requests stay chronological.
            placeholders = ",".join("?" for _ in selected)
            order = "ASC" if page is not None else "DESC"
            rows = conn.execute(
                "SELECT timestamp AS ts, level, message AS msg FROM job_logs "
                f"WHERE job_id=? AND level IN ({placeholders}) ORDER BY id {order} LIMIT 200 OFFSET ?",
                (job_id, *selected, (page - 1) * 200 if page is not None else 0),
            ).fetchall()
        lines = [dict(row) for row in rows]
        if page is None:
            lines.reverse()
        return templates.TemplateResponse(request=request, name="partials/job_log_lines.html", context={
            "job_id": job_id, "active": job["status"] in ("queued", "running", "stopping"),
            "lines": lines, "has_logs": total > 0, "log_count": total,
        })

    @router.get("/jobs/{job_id}/download")
    async def job_download(request: Request, job_id: int):
        if not get_current_user(request):
            return RedirectResponse("/login", status_code=302)
        with get_db() as conn:
            if not conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone():
                return HTMLResponse(status_code=404)
        def stream():
            with get_db() as conn:
                rows = conn.execute("SELECT * FROM job_logs WHERE job_id=? ORDER BY id", (job_id,))
                for row in rows:
                    yield f"{row['timestamp']} UTC [{row['level']}] {row['message']}\n"
        return StreamingResponse(stream(), media_type="text/plain", headers={
            "Content-Disposition": f'attachment; filename="kmm-job-{job_id}.log"',
        })

    return router
