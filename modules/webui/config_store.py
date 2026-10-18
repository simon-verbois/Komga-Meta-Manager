# -*- coding: utf-8 -*-
"""
Configuration store — reads and writes AppConfig from/to the SQLite database.

The config is stored as a JSON blob under settings key ``app_config``.
A threading.RLock protects in-memory access so the web server and the
scheduler/watcher threads can share the same AppConfig safely.
"""
import json
import logging
import threading
from typing import Optional, Callable

from pydantic import ValidationError

from modules.config import AppConfig
from .db import get_setting_json, set_setting_json

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_config: Optional[AppConfig] = None

# Optional callback invoked (with the new config) when hot-reload happens.
_reload_callback: Optional[Callable[[AppConfig], None]] = None


def register_reload_callback(fn: Callable[[AppConfig], None]) -> None:
    """Register a function to call whenever the config is reloaded."""
    global _reload_callback
    _reload_callback = fn


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_config_from_db() -> Optional[AppConfig]:
    """
    Read the app configuration from the database.

    Returns the validated AppConfig, or None if no config has been saved yet.
    """
    global _config
    with _lock:
        _config = None
    raw = get_setting_json("app_config")
    if raw is None:
        from pathlib import Path
        for legacy_path in [Path("/config/config.yml"), Path("config/config.yml")]:
            if legacy_path.is_file():
                try:
                    from modules.config import load_config
                    from .db import add_audit_entry
                    legacy_cfg = load_config(str(legacy_path))
                    cfg = save_config_to_db(json.loads(legacy_cfg.model_dump_json()))
                    add_audit_entry("MIGRATION", f"Imported existing configuration from {legacy_path}")
                    logger.info("Migrated legacy configuration from %s to database.", legacy_path)
                    return cfg
                except Exception as exc:
                    logger.warning("Could not migrate legacy config from %s: %s", legacy_path, exc)
        logger.debug("No app_config found in database.")
        return None
    try:
        cfg = AppConfig(**raw)
        with _lock:
            _config = cfg
        logger.info("Configuration loaded from database.")
        return cfg
    except (ValidationError, TypeError) as exc:
        logger.error("Stored configuration is invalid: %s", exc)
        return None


def save_config_to_db(data: dict) -> AppConfig:
    """
    Validate *data* with Pydantic, persist to the database, update the
    in-memory reference and fire the reload callback.

    Raises ``pydantic.ValidationError`` if *data* is invalid.
    """
    global _config

    # Validate first — raises ValidationError on bad input.
    cfg = AppConfig(**data)

    # Persist the canonical representation (use model_dump for correct types).
    serialisable = json.loads(cfg.model_dump_json())
    with _lock:
        set_setting_json("app_config", serialisable)
        _config = cfg

    logger.info("Configuration saved to database.")

    if _reload_callback is not None:
        try:
            _reload_callback(cfg)
        except Exception as exc:
            logger.error("Reload callback raised an exception: %s", exc)

    return cfg


# ---------------------------------------------------------------------------
# In-memory access
# ---------------------------------------------------------------------------

def get_config() -> Optional[AppConfig]:
    """Return the current in-memory AppConfig (may be None before setup)."""
    with _lock:
        return _config


def get_config_dict() -> Optional[dict]:
    """
    Return the current config as a plain dict suitable for form pre-filling.
    Secrets (api keys) are included so the UI can display masked values.
    """
    with _lock:
        if _config is None:
            return None
        return json.loads(_config.model_dump_json())


def update_config(new_cfg: AppConfig) -> None:
    """Replace the in-memory config without persisting (used for hot-reload)."""
    global _config
    with _lock:
        _config = new_cfg
