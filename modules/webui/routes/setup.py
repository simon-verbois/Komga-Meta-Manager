# -*- coding: utf-8 -*-
"""
First-run setup wizard routes.

GET  /setup  → render the account-creation form
POST /setup  → create the user account, redirect to config/komga
"""
import logging
import sqlite3

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from modules.webui.auth import SESSION_COOKIE, create_session_token, hash_password
from modules.webui.db import add_audit_entry, create_user, user_exists

logger = logging.getLogger(__name__)


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    """Return the router with template dependency injected."""
    router = APIRouter()

    @router.get("/setup", response_class=HTMLResponse)
    async def setup_get(request: Request):
        if user_exists():
            return RedirectResponse("/", status_code=302)
        return templates.TemplateResponse(
            request=request, name="setup.html", context={"error": None}
        )

    @router.post("/setup", response_class=HTMLResponse)
    async def setup_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        password_confirm: str = Form(...),
    ):
        # Guard: if account already exists, don't allow re-setup via this route.
        if user_exists():
            return RedirectResponse("/", status_code=302)

        error = None
        if not username.strip():
            error = "setup.error.username_empty"
        elif len(password.encode("utf-8")) > 72:
            error = "setup.error.long"
        elif len(password) < 8:
            error = "setup.error.short"
        elif password != password_confirm:
            error = "setup.error.match"

        if error:
            return templates.TemplateResponse(
                request=request, name="setup.html", context={"error": error, "username": username}
            )

        try:
            create_user(username.strip(), hash_password(password))
        except sqlite3.IntegrityError:
            return RedirectResponse("/login", status_code=302)
        add_audit_entry("SETUP_COMPLETE", f"Account created for '{username.strip()}'")
        logger.info("Setup complete. Account created for '%s'.", username.strip())

        token = create_session_token(username.strip())
        response = RedirectResponse("/settings?tab=connection", status_code=302)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
        )
        return response

    return router
