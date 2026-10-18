# -*- coding: utf-8 -*-
"""
Shared request helpers — session resolution, login-required guard.
"""
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse

from modules.webui.auth import SESSION_COOKIE, decode_session_token
from modules.webui.db import get_user


def get_current_user(request: Request) -> Optional[str]:
    """
    Return the username from the session cookie, or None if not authenticated.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    username = decode_session_token(token)
    return username if username and get_user(username) else None


def require_auth(request: Request) -> str:
    """
    Return the current username, redirecting to /login if unauthenticated.
    Raises RedirectResponse (caught by FastAPI) when not logged in.
    """
    username = get_current_user(request)
    if not username:
        raise _redirect("/login")
    return username


class _redirect(Exception):
    """Thin wrapper so we can raise a redirect from helper functions."""
    def __init__(self, url: str):
        self.response = RedirectResponse(url, status_code=302)
