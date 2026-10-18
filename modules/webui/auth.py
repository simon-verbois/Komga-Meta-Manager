# -*- coding: utf-8 -*-
"""
Authentication helpers: password hashing and signed session cookies.
"""
import logging
import secrets
import hashlib

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import bcrypt

from .db import get_setting, set_setting, get_user

logger = logging.getLogger(__name__)

# Session cookie name used across the app.
SESSION_COOKIE = "kmm_session"
# Sessions expire after 7 days of inactivity.
SESSION_MAX_AGE = 60 * 60 * 24 * 7


def hash_password(plain: str) -> str:
    """Return a bcrypt hash for *plain*."""
    plain_bytes = plain.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    plain_bytes = plain.encode("utf-8")
    hashed_bytes = hashed.encode("utf-8")
    try:
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session secret — generated once, persisted in the DB
# ---------------------------------------------------------------------------

_serializer: URLSafeTimedSerializer | None = None


def _get_serializer() -> URLSafeTimedSerializer:
    """Return a cached serializer, initialising the secret key on first call."""
    global _serializer
    if _serializer is not None:
        return _serializer

    secret = get_setting("session_secret")
    if not secret:
        secret = secrets.token_hex(32)
        set_setting("session_secret", secret)
        logger.info("Generated new session secret.")

    _serializer = URLSafeTimedSerializer(secret, salt="kmm-session")
    return _serializer


def create_session_token(username: str) -> str:
    """Return a signed, time-limited session token for *username*."""
    user = get_user(username)
    version = hashlib.sha256(user["password_hash"].encode()).hexdigest() if user else None
    return _get_serializer().dumps({"u": username, "v": version})


def decode_session_token(token: str) -> str | None:
    """
    Return the username embedded in *token*, or None if invalid / expired.
    """
    try:
        data = _get_serializer().loads(token, max_age=SESSION_MAX_AGE)
        username = data.get("u")
        user = get_user(username) if isinstance(username, str) else None
        if user and data.get("v") != hashlib.sha256(user["password_hash"].encode()).hexdigest():
            return None
        return username if isinstance(username, str) else None
    except (BadSignature, SignatureExpired):
        return None
