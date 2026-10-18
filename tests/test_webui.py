# -*- coding: utf-8 -*-
"""
Unit tests for the Web UI module:
- Database and Auth (password hashing, sessions, users)
- Configuration store (load, save, validation, hot reload)
- Log buffer (circular buffer, debug filtering)
- i18n
- Audit logging
"""
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from modules.config import AppConfig
from modules.webui import auth, config_store, db, i18n, log_buffer


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Point the Web UI DB to a temporary file for each test."""
    db_file = tmp_path / "test_webui.db"
    db.init_db(db_file)
    auth._serializer = None  # reset serializer
    config_store._config = None
    config_store._reload_callback = None
    log_buffer.clear_buffer()
    yield db_file


# ---------------------------------------------------------------------------
# Database & Auth tests
# ---------------------------------------------------------------------------

def test_user_lifecycle():
    assert not db.user_exists()

    # Create user
    pw_hash = auth.hash_password("SuperSecret123!")
    db.create_user("admin", pw_hash)

    assert db.user_exists()
    user = db.get_user("admin")
    assert user is not None
    assert user["username"] == "admin"
    assert auth.verify_password("SuperSecret123!", user["password_hash"])
    assert not auth.verify_password("WrongPassword", user["password_hash"])

    # Update password
    new_hash = auth.hash_password("BrandNewSecret456!")
    db.update_password("admin", new_hash)
    updated_user = db.get_user("admin")
    assert auth.verify_password("BrandNewSecret456!", updated_user["password_hash"])
    assert not auth.verify_password("SuperSecret123!", updated_user["password_hash"])


def test_session_token():
    token = auth.create_session_token("admin")
    assert isinstance(token, str)

    username = auth.decode_session_token(token)
    assert username == "admin"

    # Tampered token
    assert auth.decode_session_token(token + "corrupted") is None
    assert auth.decode_session_token("invalid-garbage") is None


def test_settings_storage():
    assert db.get_setting("custom_key") is None
    db.set_setting("custom_key", "custom_value")
    assert db.get_setting("custom_key") == "custom_value"

    # Upsert
    db.set_setting("custom_key", "updated_value")
    assert db.get_setting("custom_key") == "updated_value"

    # JSON settings
    db.set_setting_json("json_key", {"foo": "bar", "num": 42})
    assert db.get_setting_json("json_key") == {"foo": "bar", "num": 42}


def test_audit_log():
    assert db.count_audit_log() == 0
    db.add_audit_entry("LOGIN", "Admin logged in")
    db.add_audit_entry("CONFIG_SAVE", "Saved system config")

    assert db.count_audit_log() == 2
    entries = db.get_audit_log(limit=10)
    assert len(entries) == 2
    assert entries[0]["action"] == "CONFIG_SAVE"  # newest first
    assert entries[1]["action"] == "LOGIN"


# ---------------------------------------------------------------------------
# Config Store tests
# ---------------------------------------------------------------------------

def test_config_store_load_save(app_config):
    assert not db.config_exists()
    assert config_store.get_config() is None

    # Save
    data = app_config.model_dump()
    # HttpUrl in pydantic model_dump can be HttpUrl object; serialize to string
    data["komga"]["url"] = str(data["komga"]["url"])
    saved_cfg = config_store.save_config_to_db(data)
    assert isinstance(saved_cfg, AppConfig)
    assert db.config_exists()

    # Load from DB
    loaded_cfg = config_store.load_config_from_db()
    assert loaded_cfg is not None
    assert str(loaded_cfg.komga.url).rstrip("/") == str(app_config.komga.url).rstrip("/")
    assert loaded_cfg.komga.api_key == "secret"

    # In-memory getter
    assert config_store.get_config() is not None
    cfg_dict = config_store.get_config_dict()
    assert cfg_dict is not None
    assert "komga" in cfg_dict


def test_config_store_hot_reload_callback(app_config):
    mock_callback = Mock()
    config_store.register_reload_callback(mock_callback)

    data = app_config.model_dump()
    data["komga"]["url"] = str(data["komga"]["url"])
    config_store.save_config_to_db(data)

    mock_callback.assert_called_once()
    assert isinstance(mock_callback.call_args[0][0], AppConfig)


def test_config_store_invalid_data_raises():
    with pytest.raises(ValidationError):
        config_store.save_config_to_db({"komga": {"url": "not-a-valid-url"}})


# ---------------------------------------------------------------------------
# Log Buffer tests
# ---------------------------------------------------------------------------

def test_log_buffer_filtering():
    import logging

    handler = log_buffer.install_handler()
    logger = logging.getLogger("test_logger")
    logger.setLevel(logging.DEBUG)

    logger.info("Informational message")
    logger.debug("Debug message")
    logger.warning("Warning message")

    lines_without_debug = log_buffer.get_lines(include_debug=False)
    assert any("Informational message" in entry["msg"] for entry in lines_without_debug)
    assert any("Warning message" in entry["msg"] for entry in lines_without_debug)
    assert not any("Debug message" in entry["msg"] for entry in lines_without_debug)

    lines_with_debug = log_buffer.get_lines(include_debug=True)
    assert any("Debug message" in entry["msg"] for entry in lines_with_debug)

    log_buffer.clear_buffer()
    assert len(log_buffer.get_lines(include_debug=True)) == 0

    logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# i18n tests
# ---------------------------------------------------------------------------

def test_i18n_translation():
    i18n.set_locale("en")
    assert i18n.t("nav.dashboard") == "Dashboard"
    assert i18n.t("common.save") == "Save"

    # Missing key falls back to key itself
    assert i18n.t("unknown.key.foo") == "unknown.key.foo"

    # Parameter substitution
    msg = i18n.t("dashboard.watcher.interval", n=15)
    assert "15" in msg


def test_logging_reload_does_not_duplicate_handler():
    import logging
    from modules.main import setup_logging

    root = logging.getLogger()
    previous_level = root.level
    previous_handlers = list(root.handlers)
    try:
        setup_logging(False)
        setup_logging(True)
        setup_logging(False)
        assert sum(isinstance(h, log_buffer.BufferHandler) for h in root.handlers) == 1
        assert root.level == logging.INFO
    finally:
        root.handlers[:] = previous_handlers
        root.setLevel(previous_level)


def test_config_migration_and_database_reload(tmp_path, monkeypatch, app_config):
    import yaml
    from pathlib import Path
    from modules import config

    legacy = tmp_path / "config.yml"
    legacy.write_text(yaml.safe_dump(app_config.model_dump(mode="json")))
    original_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: True if p == Path("/config/config.yml") else original_is_file(p))
    original_load = config.load_config
    monkeypatch.setattr(config, "load_config", lambda _: original_load(str(legacy)))
    loaded = config_store.load_config_from_db()
    assert loaded.komga.api_key == app_config.komga.api_key
    assert db.config_exists()
    legacy.unlink()
    config_store.update_config(None)
    assert config_store.load_config_from_db() == loaded
    assert any(e["action"] == "MIGRATION" for e in db.get_audit_log())
