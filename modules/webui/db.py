# -*- coding: utf-8 -*-
"""
SQLite database helpers for the Web UI.

Tables:
  - users        : single account (username + bcrypt hash)
  - settings     : key/value store (session_secret, app_config JSON, etc.)
  - audit_log    : immutable log of user actions (config saves, runs, etc.)
"""
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("/config/webui.db")

def _get_connection() -> sqlite3.Connection:
    """Open a connection for one database operation."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a database connection."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """Create tables if they don't exist. Call once at startup."""
    global DB_PATH
    if db_path is not None:
        DB_PATH = db_path

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS single_user ON users ((1));

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT    NOT NULL,
                action     TEXT    NOT NULL,
                detail     TEXT
            );
        """)
    logger.info("Database initialized at %s", DB_PATH)


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

def user_exists() -> bool:
    """Return True if at least one user account has been created."""
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0] > 0


def create_user(username: str, password_hash: str) -> None:
    """Insert a new user record."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, now),
        )


def get_user(username: str) -> Optional[sqlite3.Row]:
    """Return the user row for *username*, or None."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def update_password(username: str, new_hash: str) -> None:
    """Update the password hash for an existing user."""
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (new_hash, username),
        )


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def get_setting(key: str) -> Optional[str]:
    """Return the raw string value for *key*, or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    """Upsert a setting."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_setting_json(key: str) -> Optional[dict]:
    """Return a JSON-decoded setting, or None."""
    raw = get_setting(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Setting '%s' is not valid JSON.", key)
        return None


def set_setting_json(key: str, value: dict) -> None:
    """JSON-encode *value* and store it as a setting."""
    set_setting(key, json.dumps(value, ensure_ascii=False))


def config_exists() -> bool:
    """Return True if a saved app configuration exists in the database."""
    return get_setting("app_config") is not None


# ---------------------------------------------------------------------------
# Audit log helpers
# ---------------------------------------------------------------------------

def add_audit_entry(action: str, detail: Optional[str] = None) -> None:
    """Append an entry to the audit log."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO audit_log (timestamp, action, detail) VALUES (?, ?, ?)",
            (now, action, detail),
        )


def get_audit_log(limit: int = 100, offset: int = 0) -> list:
    """Return *limit* audit log rows ordered newest-first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_audit_log() -> int:
    """Return the total number of audit log entries."""
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        return row[0]
