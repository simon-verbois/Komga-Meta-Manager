# -*- coding: utf-8 -*-
"""
Authentication routes: login, logout, password change.

GET  /login          → render login form
POST /login          → authenticate, set session cookie
POST /logout         → clear session cookie
GET  /account        → password change form
POST /account        → update password
"""
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from modules.webui.auth import (
    SESSION_COOKIE,
    create_session_token,
    hash_password,
    verify_password,
)
from modules.webui.db import add_audit_entry, get_user, update_password, user_exists
from modules.webui.routes.guards import get_current_user

logger = logging.getLogger(__name__)


def setup_routes(templates: Jinja2Templates) -> APIRouter:
    """Return the router with template dependency injected."""
    router = APIRouter()

    @router.get("/login", response_class=HTMLResponse)
    async def login_get(request: Request):
        if not user_exists():
            return RedirectResponse("/setup", status_code=302)
        if get_current_user(request):
            return RedirectResponse("/", status_code=302)
        return templates.TemplateResponse(
            request=request, name="login.html", context={"error": None}
        )

    @router.post("/login", response_class=HTMLResponse)
    async def login_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ):
        user = get_user(username.strip())
        if user and verify_password(password, user["password_hash"]):
            token = create_session_token(username.strip())
            add_audit_entry("LOGIN", f"User '{username.strip()}' logged in.")
            response = RedirectResponse("/", status_code=302)
            response.set_cookie(
                SESSION_COOKIE,
                token,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
                max_age=60 * 60 * 24 * 7,
            )
            return response

        logger.warning("Failed login attempt for username '%s'.", username)
        return templates.TemplateResponse(
            request=request, name="login.html", context={"error": "login.error"}
        )

    @router.post("/logout")
    async def logout(request: Request):
        username = get_current_user(request)
        if username:
            add_audit_entry("LOGOUT", f"User '{username}' logged out.")
        response = RedirectResponse("/login", status_code=302)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @router.get("/account", response_class=HTMLResponse)
    async def account_get(request: Request):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(
            request=request, name="account.html", context={"username": username, "error": None, "success": False}
        )

    @router.post("/account", response_class=HTMLResponse)
    async def account_post(
        request: Request,
        current_password: str = Form(...),
        new_password: str = Form(...),
        new_password_confirm: str = Form(...),
    ):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)

        ctx = {"username": username, "error": None, "success": False}
        user = get_user(username)
        if not user or not verify_password(current_password, user["password_hash"]):
            ctx["error"] = "account.error.current"
            return templates.TemplateResponse(request=request, name="account.html", context=ctx)
        if len(new_password.encode("utf-8")) > 72:
            ctx["error"] = "account.error.long"
            return templates.TemplateResponse(request=request, name="account.html", context=ctx)
        if len(new_password) < 8:
            ctx["error"] = "account.error.short"
            return templates.TemplateResponse(request=request, name="account.html", context=ctx)
        if new_password != new_password_confirm:
            ctx["error"] = "account.error.match"
            return templates.TemplateResponse(request=request, name="account.html", context=ctx)

        update_password(username, hash_password(new_password))
        add_audit_entry("PASSWORD_CHANGE", f"User '{username}' changed their password.")
        ctx["success"] = True
        response = templates.TemplateResponse(request=request, name="account.html", context=ctx)
        response.set_cookie(SESSION_COOKIE, create_session_token(username), httponly=True,
                            secure=request.url.scheme == "https", samesite="lax", max_age=60 * 60 * 24 * 7)
        return response

    return router
