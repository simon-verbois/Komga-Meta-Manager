# -*- coding: utf-8 -*-
"""
HTTP integration tests for the Web UI routes using starlette.testclient.TestClient:
- First-run wizard (/setup)
- Authentication (/login, /logout, /account)
- Dashboard (/ and /status and /toggle-dry-run and /run-now)
- Configuration sections (/config/komga, /config/system, etc.)
- Logs (/logs/exec/lines, /logs/audit/lines)
"""
import pytest
from fastapi.testclient import TestClient

from modules.webui import auth, config_store, db, log_buffer
from modules.webui.app import create_app


@pytest.fixture
def client(tmp_path, app_config):
    db_file = tmp_path / "test_webui_routes.db"
    db.init_db(db_file)
    auth._serializer = None
    config_store._config = None
    config_store._reload_callback = None
    log_buffer.clear_buffer()

    app = create_app()
    # Starlette test client does not follow redirects by default unless specified
    with TestClient(app, follow_redirects=False) as c:
        yield c, app_config


def test_unsetup_redirects_to_setup(client):
    c, _ = client
    response = c.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/setup"


def test_setup_wizard_flow(client):
    c, app_config = client

    # GET /setup renders form
    r = c.get("/setup")
    assert r.status_code == 200
    assert "setup" in r.text.lower()

    # Password mismatch error
    r = c.post("/setup", data={
        "username": "admin",
        "password": "Password123!",
        "password_confirm": "DifferentPassword123!",
    })
    assert r.status_code == 200
    assert "Passwords do not match" in r.text or "setup.error.match" in r.text

    # Successful setup
    r = c.post("/setup", data={
        "username": "admin",
        "password": "Password123!",
        "password_confirm": "Password123!",
    })
    assert r.status_code == 302
    assert r.headers["location"] == "/config/komga"
    assert auth.SESSION_COOKIE in r.cookies

    # User is now in DB
    assert db.user_exists()


def test_auth_login_logout(client):
    c, _ = client
    # Create user
    db.create_user("admin", auth.hash_password("MyPassword123!"))

    # Wrong credentials
    r = c.post("/login", data={"username": "admin", "password": "Wrong"})
    assert r.status_code == 200
    assert "Invalid username or password" in r.text or "login.error" in r.text

    # Correct credentials
    r = c.post("/login", data={"username": "admin", "password": "MyPassword123!"})
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    assert auth.SESSION_COOKIE in r.cookies
    token = r.cookies[auth.SESSION_COOKIE]

    # Logout
    r = c.post("/logout", cookies={auth.SESSION_COOKIE: token})
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_dashboard_and_dry_run_toggle(client):
    c, app_config = client
    # Create user and config
    db.create_user("admin", auth.hash_password("MyPassword123!"))
    token = auth.create_session_token("admin")
    cookies = {auth.SESSION_COOKIE: token}

    data = app_config.model_dump()
    data["komga"]["url"] = str(data["komga"]["url"])
    config_store.save_config_to_db(data)

    # Access dashboard
    r = c.get("/", cookies=cookies)
    assert r.status_code == 200
    assert "Dashboard" in r.text

    # Toggle dry-run
    initial_dry_run = config_store.get_config().system.dry_run
    r = c.post("/toggle-dry-run", cookies=cookies)
    assert r.status_code == 200
    assert config_store.get_config().system.dry_run != initial_dry_run


def test_config_pages_save(client):
    c, app_config = client
    db.create_user("admin", auth.hash_password("MyPassword123!"))
    token = auth.create_session_token("admin")
    cookies = {auth.SESSION_COOKIE: token}

    # Save Komga config
    r = c.post("/config/komga", data={
        "url": "http://mykomga:8080",
        "api_key": "testkey123",
        "libraries": "Manga\nWebtoons",
        "verify_ssl": "1",
    }, cookies=cookies)
    assert r.status_code == 200
    assert "Configuration saved" in r.text

    cfg = config_store.get_config()
    assert cfg is not None
    assert str(cfg.komga.url).rstrip("/") == "http://mykomga:8080"
    assert cfg.komga.libraries == ["Manga", "Webtoons"]

    # Save System config
    r = c.post("/config/system", data={
        "dry_run": "1",
        "debug": "1",
        "scheduler_enabled": "1",
        "run_at": "05:30",
        "polling_interval_minutes": "10",
    }, cookies=cookies)
    assert r.status_code == 200
    cfg = config_store.get_config()
    assert cfg.system.scheduler.enabled is True
    assert cfg.system.scheduler.run_at == "05:30"
    assert cfg.system.debug is True


def test_log_endpoints(client):
    c, _ = client
    db.create_user("admin", auth.hash_password("MyPassword123!"))
    token = auth.create_session_token("admin")
    cookies = {auth.SESSION_COOKIE: token}

    # Exec log lines
    r = c.get("/logs/exec/lines", cookies=cookies)
    assert r.status_code == 200

    # Clear exec log
    r = c.post("/logs/exec/clear", cookies=cookies)
    assert r.status_code == 200

    # Audit log lines
    db.add_audit_entry("TEST_ACTION", "Testing audit line")
    r = c.get("/logs/audit/lines", cookies=cookies)
    assert r.status_code == 200
    assert "TEST_ACTION" in r.text


@pytest.fixture
def configured_client(client):
    from modules.webui.routes import dashboard

    c, cfg = client
    db.create_user("admin", auth.hash_password("MyPassword123!"))
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session_token("admin"))
    config_store.save_config_to_db(cfg.model_dump(mode="json"))
    dashboard._job_state = dashboard.JobState()
    dashboard._run_job_fn = None
    yield c, cfg
    dashboard._run_job_fn = None


def test_all_config_pages_with_optional_translation(configured_client):
    c, _ = configured_client
    raw = config_store.get_config_dict()
    raw["translation"] = None
    config_store.save_config_to_db(raw)
    for section in ("system", "komga", "providers", "processing", "translation"):
        r = c.get(f"/config/{section}")
        assert r.status_code == 200
        assert 'name="' in r.text

    raw["translation"] = {"enabled": False, "provider": "google", "deepl": None}
    config_store.save_config_to_db(raw)
    assert c.get("/config/translation").status_code == 200


def test_invalid_numeric_input_preserves_config(configured_client):
    c, _ = configured_client
    before = config_store.get_config_dict()
    response = c.post("/config/system", data={"polling_interval_minutes": "invalid", "run_at": "04:00"})
    assert response.status_code == 200
    assert "Validation error" in response.text
    assert config_store.get_config_dict() == before
    response = c.post("/config/providers", data={"anilist_priority": ""})
    assert response.status_code == 200
    assert "Validation error" in response.text
    assert config_store.get_config_dict() == before


def test_dry_run_uses_snapshot_and_rejects_duplicate(configured_client):
    import threading
    from modules.processor import ProcessingResult
    from modules.webui.routes import dashboard

    c, _ = configured_client
    raw = config_store.get_config_dict()
    raw["system"]["dry_run"] = False
    config_store.save_config_to_db(raw)
    before = config_store.get_config_dict()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    received = []

    def run(cfg):
        received.append(cfg)
        entered.set()
        assert release.wait(5)
        return ProcessingResult(success=True)

    original_finish = dashboard._job_state.finish

    def finish(success):
        original_finish(success)
        finished.set()

    dashboard._job_state.finish = finish
    dashboard.register_job_runner(run)
    try:
        assert c.post("/dry-run").status_code == 200
        assert entered.wait(2)
        assert c.post("/run-now").status_code == 200
        assert len(received) == 1
        assert received[0].system.dry_run is True
        assert config_store.get_config_dict() == before
        assert "Running" in c.get("/status").text
    finally:
        release.set()
        assert finished.wait(2)
    assert "Success" in c.get("/status").text
    assert any(e["action"] == "DRY_RUN" for e in db.get_audit_log())


def test_scheduler_form_reloads_without_changing_other_settings(configured_client):
    from unittest.mock import Mock

    c, _ = configured_client
    before = config_store.get_config_dict()
    callback = Mock()
    config_store.register_reload_callback(callback)
    response = c.post("/scheduler", data={"scheduler_enabled": "on", "run_at": "16:45"})
    assert response.status_code == 303
    callback.assert_called_once()
    after = config_store.get_config_dict()
    assert after["system"]["scheduler"] == {"enabled": True, "run_at": "16:45"}
    assert after["komga"] == before["komga"]
    assert after["system"]["dry_run"] == before["system"]["dry_run"]
    assert "Next run" in c.get("/").text
    c.post("/scheduler", data={"run_at": "25:70"})
    assert config_store.get_config_dict() == after


def test_log_debug_filter_and_pagination_bounds(configured_client):
    import logging

    c, _ = configured_client
    handler = log_buffer.BufferHandler()
    handler.emit(logging.LogRecord("test", logging.DEBUG, "", 0, "debug-only-entry", (), None))
    assert "debug-only-entry" not in c.get("/logs/exec/lines").text
    assert "debug-only-entry" in c.get("/logs/exec/lines?debug=true").text
    for query in ("per_page=0", "per_page=-1", "per_page=1000", "page=0"):
        assert c.get("/logs/audit/lines?" + query).status_code == 422


def test_password_change_invalidates_old_sessions(configured_client):
    c, _ = configured_client
    old_token = c.cookies.get(auth.SESSION_COOKIE)
    response = c.post("/account", data={
        "current_password": "MyPassword123!",
        "new_password": "ChangedPassword123!",
        "new_password_confirm": "ChangedPassword123!",
    })
    assert response.status_code == 200
    assert "Password updated successfully" in response.text
    assert auth.decode_session_token(old_token) is None
    assert auth.decode_session_token(response.cookies[auth.SESSION_COOKIE]) == "admin"


def test_cross_origin_mutations_rejected(configured_client):
    c, _ = configured_client
    before = config_store.get_config_dict()
    assert c.post("/toggle-dry-run", headers={"Origin": "https://other.example"}).status_code == 403
    assert c.post("/toggle-dry-run", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert config_store.get_config_dict() == before


def test_protected_routes_require_login(client):
    c, _ = client
    for path in ("/config/system", "/config/komga", "/logs", "/account"):
        assert c.get(path).headers["location"] == "/login"
    for path in ("/run-now", "/dry-run", "/scheduler", "/toggle-dry-run", "/config/komga"):
        assert c.post(path).headers["location"] == "/login"
    assert c.get("/health").json() == {"status": "ok"}


def test_setup_rejects_oversized_password_and_second_user(client):
    import sqlite3

    c, _ = client
    response = c.post("/setup", data={"username": "admin", "password": "x" * 73, "password_confirm": "x" * 73})
    assert response.status_code == 200
    assert "72 UTF-8 bytes" in response.text
    assert not db.user_exists()
    db.create_user("admin", auth.hash_password("Password123!"))
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user("second", auth.hash_password("Password123!"))


def test_packaged_version_is_used_by_api_and_ui(configured_client):
    from modules.version import get_version

    c, _ = configured_client
    assert c.app.version == get_version()
    assert get_version() in c.get("/").text


def test_komga_library_discovery_uses_form_connection_without_saving(configured_client):
    from unittest.mock import patch
    from modules.models import KomgaLibrary

    c, _ = configured_client
    before = config_store.get_config_dict()
    with patch("modules.webui.routes.config_routes.KomgaClient") as client_cls:
        komga = client_cls.return_value
        komga.get_libraries.return_value = [
            KomgaLibrary(id="1", name="Manga"),
            KomgaLibrary(id="2", name="Comics & Webtoons"),
        ]
        response = c.post("/config/komga/libraries", data={
            "url": "https://new-komga:25600", "api_key": "new-key", "verify_ssl": "1",
        })
        assert response.status_code == 200
        assert response.json() == {"libraries": [
            {"id": "1", "name": "Manga"}, {"id": "2", "name": "Comics & Webtoons"},
        ]}
        connection = client_cls.call_args.args[0]
        assert str(connection.url) == "https://new-komga:25600/"
        assert connection.api_key == "new-key"
        assert connection.verify_ssl is True
        komga.session.close.assert_called_once()
    assert config_store.get_config_dict() == before


def test_library_discovery_handles_empty_results_and_failure(configured_client):
    from unittest.mock import patch
    from modules.komga_client import KomgaAPIError

    c, _ = configured_client
    before = config_store.get_config_dict()
    data = {"url": "http://komga:25600", "api_key": "secret"}
    with patch("modules.webui.routes.config_routes.KomgaClient") as client_cls:
        komga = client_cls.return_value
        komga.get_libraries.return_value = []
        assert c.post("/config/komga/libraries", data=data).json() == {"libraries": []}
        assert client_cls.call_args.args[0].verify_ssl is False
        komga.get_libraries.side_effect = KomgaAPIError("private connection details")
        response = c.post("/config/komga/libraries", data=data)
        assert response.status_code == 502
        assert response.json() == {"error": "fetch_failed"}
        assert komga.session.close.call_count == 2
    assert config_store.get_config_dict() == before


def test_library_discovery_validates_connection_and_requires_login(client):
    from unittest.mock import patch

    c, _ = client
    assert c.post("/config/komga/libraries").headers["location"] == "/login"
    db.create_user("admin", auth.hash_password("MyPassword123!"))
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session_token("admin"))
    with patch("modules.webui.routes.config_routes.KomgaClient") as client_cls:
        assert c.post("/config/komga/libraries", data={"url": "invalid", "api_key": "key"}).status_code == 422
        client_cls.assert_not_called()
    assert not db.config_exists()


def test_library_checkboxes_save_subset_and_allow_disabling_all(configured_client):
    from unittest.mock import Mock

    c, _ = configured_client
    callback = Mock()
    config_store.register_reload_callback(callback)
    data = {
        "url": "http://komga:25600", "api_key": "secret", "verify_ssl": "1",
        "library_selection": "checkboxes", "enabled_libraries": ["Webtoons", "Comics & Manga"],
    }
    response = c.post("/config/komga", data=data)
    assert "Configuration saved" in response.text
    assert config_store.get_config().komga.libraries == ["Webtoons", "Comics & Manga"]
    callback.assert_called_once()
    assert 'value="Comics &amp; Manga" checked' in response.text
    # Invalid connection data must not overwrite the saved selection.
    response = c.post("/config/komga", data={**data, "url": "invalid", "enabled_libraries": "Other"})
    assert "Validation error" in response.text
    assert 'value="Other" checked' in response.text
    assert config_store.get_config().komga.libraries == ["Webtoons", "Comics & Manga"]
    del data["enabled_libraries"]
    assert "Configuration saved" in c.post("/config/komga", data=data).text
    assert config_store.get_config().komga.libraries == []
    assert config_store.load_config_from_db().komga.libraries == []
    assert "None enabled" in c.get("/").text
