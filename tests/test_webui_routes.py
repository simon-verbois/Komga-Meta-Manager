# -*- coding: utf-8 -*-
"""
HTTP integration tests for the Web UI routes using starlette.testclient.TestClient:
- First-run wizard (/setup)
- Authentication (/login, /logout, /account)
- Home (/, /status, /fetch, /onboarding) and job actions
- Settings tabs (/settings?tab=…, POST /settings/<tab>) and legacy /config redirects
- Activity (/logs?tab=…, /logs/jobs/list, job detail) and log fragments
"""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from modules.models import KomgaLibrary

from modules.webui import auth, config_store, db, log_buffer
from modules.webui.app import create_app


@pytest.fixture
def client(tmp_path, app_config, monkeypatch):
    db_file = tmp_path / "test_webui_routes.db"
    db.init_db(db_file)
    auth._serializer = None
    config_store._config = None
    config_store._reload_callback = None
    log_buffer.clear_buffer()

    from modules.job_queue import JobQueue

    queue = JobQueue()
    monkeypatch.setattr(queue, "start", lambda: None)
    app = create_app(job_queue=queue)
    # Starlette test client does not follow redirects by default unless specified
    with TestClient(app, follow_redirects=False) as c:
        yield c, app_config


LIBRARIES = [KomgaLibrary(id="library-1", name="Manga"), KomgaLibrary(id="library-2", name="Webtoons")]


@pytest.fixture
def configured_client(client):
    """Signed-in client with a saved configuration and a fake Komga library list (no network)."""
    c, cfg = client
    db.create_user("admin", auth.hash_password("MyPassword123!"))
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session_token("admin"))
    config_store.save_config_to_db(cfg.model_dump(mode="json"))
    with (
        patch("modules.webui.routes.dashboard.known_libraries", side_effect=lambda *_: list(LIBRARIES)) as known,
        patch("modules.webui.routes.review.known_libraries", new=known),
        patch("modules.webui.routes.libraries.known_libraries", new=known),
    ):
        yield c, cfg


def last_job() -> dict:
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
    return {**dict(row), "config": json.loads(row["config"]), "series_ids": json.loads(row["series_ids"] or "null")}


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
    assert r.headers["location"] == "/settings?tab=connection"
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
    assert "Wrong username or password" in r.text

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
    db.add_audit_entry("RUN_NOW", "Job #1 queued by 'admin' (dry_run=True)")
    r = c.get("/logs/audit/lines", cookies=cookies)
    assert r.status_code == 200
    # Unknown actions become readable labels; legacy technical flags are shown in words.
    assert "Test action" in r.text and "TEST_ACTION" not in r.text
    assert "Run started" in r.text and "(simulation)" in r.text and "dry_run" not in r.text


def test_log_debug_filter_and_pagination_bounds(configured_client):
    import logging

    c, _ = configured_client
    handler = log_buffer.BufferHandler()
    handler.emit(logging.LogRecord("test", logging.DEBUG, "", 0, "debug-only-entry", (), None))
    assert "debug-only-entry" not in c.get("/logs/exec/lines").text
    assert "debug-only-entry" in c.get("/logs/exec/lines?levels=DEBUG").text
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
    assert "Password updated." in response.text
    assert auth.decode_session_token(old_token) is None
    assert auth.decode_session_token(response.cookies[auth.SESSION_COOKIE]) == "admin"


def test_cross_origin_mutations_rejected(configured_client):
    c, _ = configured_client
    before = config_store.get_config_dict()
    for path in ("/fetch", "/onboarding", "/settings/automation", "/settings/connection", "/review/publish",
                 "/review/discard", "/libraries/library-1/settings", "/libraries/library-1/fetch"):
        assert c.post(path, headers={"Origin": "https://other.example"}).status_code == 403
        assert c.post(path, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert config_store.get_config_dict() == before
    assert c.app.state.job_queue.snapshot()["jobs"] == []


def test_protected_routes_require_login(client):
    c, _ = client
    for path in ("/settings", "/settings?tab=automation", "/config/system", "/logs", "/logs/jobs/1", "/account",
                 "/review", "/libraries"):
        assert c.get(path).headers["location"] == "/login"
    for path in ("/fetch", "/onboarding", "/settings/connection", "/settings/defaults", "/settings/automation",
                 "/settings/translation", "/review/publish", "/review/discard", "/jobs/1/cancel",
                 "/libraries/library-1/settings", "/libraries/library-1/fetch"):
        assert c.post(path).headers["location"] == "/login"
    assert c.post("/libraries/library-1/skip").status_code == 401
    assert c.get("/health").json() == {"status": "ok"}


def test_setup_rejects_oversized_password_and_second_user(client):
    import sqlite3

    c, _ = client
    response = c.post("/setup", data={"username": "admin", "password": "x" * 73, "password_confirm": "x" * 73})
    assert response.status_code == 200
    assert "72 bytes" in response.text
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


def test_interface_assets_are_served_locally(configured_client):
    c, _ = configured_client
    response = c.get("/")
    assert "cdn.tailwindcss.com" not in response.text
    assert "unpkg.com" not in response.text
    for asset, content_type in (
        ("/static/app.css", "text/css"),
        ("/static/app.js", "javascript"),
        ("/static/vendor/htmx.min.js", "javascript"),
    ):
        response = c.get(asset)
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]


def test_authentication_errors_keep_username_but_never_password(client):
    c, _ = client
    response = c.post("/setup", data={
        "username": "reader & admin", "password": "KeepThisPrivate123!", "password_confirm": "mismatch",
    })
    assert 'value="reader &amp; admin"' in response.text
    assert "KeepThisPrivate123!" not in response.text
    db.create_user("admin", auth.hash_password("MyPassword123!"))
    response = c.post("/login", data={"username": "reader & admin", "password": "KeepThisPrivate123!"})
    assert 'value="reader &amp; admin"' in response.text
    assert "KeepThisPrivate123!" not in response.text


def test_execution_logs_preserve_multiline_messages_and_escape_html(configured_client):
    import logging
    from datetime import datetime, timezone

    c, _ = configured_client
    message = 'First line\n    indented detail\n<script>alert("unsafe")</script>'
    record = logging.LogRecord("test", logging.WARNING, "", 0, message, (), None)
    record.created = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp()
    log_buffer.BufferHandler().emit(record)
    response = c.get("/logs/exec/lines")
    assert response.status_code == 200
    assert response.text.count("2020-01-02 03:04:05 UTC") == 1
    assert "WARNING" in response.text
    assert "First line\n    indented detail" in response.text
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text


@pytest.mark.parametrize("level", log_buffer.LOG_LEVELS)
def test_execution_logs_filter_each_level_independently(configured_client, level):
    import logging

    c, _ = configured_client
    for value in log_buffer.LOG_LEVELS:
        log_buffer.BufferHandler().emit(logging.LogRecord("test", getattr(logging, value), "", 0, f"entry-{value}", (), None))
    response = c.get("/logs/exec/lines", params={"levels": level})
    assert response.status_code == 200
    for value in log_buffer.LOG_LEVELS:
        assert (f"entry-{value}" in response.text) == (value == level)


def test_execution_log_filter_combinations_empty_and_invalid(configured_client):
    import logging

    c, _ = configured_client
    for value in log_buffer.LOG_LEVELS:
        log_buffer.BufferHandler().emit(logging.LogRecord("test", getattr(logging, value), "", 0, f"entry-{value}", (), None))
    default = c.get("/logs/exec/lines")
    assert "entry-DEBUG" not in default.text
    assert all(f"entry-{value}" in default.text for value in log_buffer.DEFAULT_LOG_LEVELS)
    response = c.get("/logs/exec/lines", params=[("levels", "WARNING"), ("levels", "ERROR"), ("filtered", "true")])
    assert "entry-WARNING" in response.text
    assert "entry-ERROR" in response.text
    assert "entry-INFO" not in response.text
    assert "entry-CRITICAL" not in response.text
    response = c.get("/logs/exec/lines?filtered=true")
    assert "No lines match" in response.text
    assert "entry-" not in response.text
    assert len(log_buffer.get_lines(levels=log_buffer.LOG_LEVELS)) == 5
    assert c.get("/logs/exec/lines?levels=UNKNOWN").status_code == 422
    assert c.get("/logs/exec/lines?levels=error").status_code == 422
    response = c.post("/logs/exec/clear")
    assert "No lines match" not in response.text
    assert len(log_buffer.get_lines(levels=log_buffer.LOG_LEVELS)) == 0




def test_first_connection_save_continues_home_and_keeps_entries_on_errors(client):
    c, _ = client
    db.create_user("admin", auth.hash_password("MyPassword123!"))
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session_token("admin"))
    page = c.get("/settings")
    assert 'id="komga-form"' in page.text
    assert 'href="/settings?tab=automation"' not in page.text
    for tab in ("defaults", "automation", "translation"):
        assert 'id="komga-form"' in c.get(f"/settings?tab={tab}").text
    response = c.post("/settings/connection", data={"url": "not a url", "api_key": "private-key"})
    assert response.status_code == 200
    assert 'value="not a url"' in response.text
    assert not db.config_exists()
    response = c.post("/settings/connection", data={"url": "http://komga:25600", "api_key": "first-key", "verify_ssl": "1"})
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cfg = config_store.get_config()
    assert cfg.komga.api_key == "first-key" and cfg.komga.libraries == [] and cfg.komga.verify_ssl is True
    response = c.post("/settings/connection", data={"url": "http://komga:25600", "api_key": "second-key"})
    assert response.headers["location"] == "/settings?tab=connection&saved=1"
    assert config_store.get_config().komga.verify_ssl is False
    assert "Connection saved." in c.get(response.headers["location"]).text


def test_connection_save_preserves_library_selection(configured_client):
    c, _ = configured_client
    c.post("/settings/connection", data={"url": "http://other:25600", "api_key": "secret", "verify_ssl": "1"})
    cfg = config_store.get_config()
    assert str(cfg.komga.url).startswith("http://other:25600")
    assert cfg.komga.libraries == ["Manga"]


def test_settings_tabs_render_and_legacy_addresses_redirect(configured_client):
    c, _ = configured_client
    raw = config_store.get_config_dict()
    raw["translation"] = None
    config_store.save_config_to_db(raw)
    for tab, marker in (("connection", 'id="komga-form"'), ("defaults", 'name="rule_summary"'),
                        ("automation", 'name="after_fetch"'), ("translation", 'name="provider"')):
        response = c.get(f"/settings?tab={tab}")
        assert response.status_code == 200
        assert marker in response.text
        assert f'href="/settings?tab={tab}" aria-current="page"' in response.text
    assert 'id="komga-form"' in c.get("/settings?tab=unknown").text
    assert 'id="komga-form"' in c.get("/settings?tab=komga").text
    for section, tab in (("komga", "connection"), ("system", "automation"), ("providers", "defaults"),
                         ("processing", "defaults"), ("translation", "translation"), ("unknown", "connection")):
        response = c.get(f"/config/{section}")
        assert response.status_code == 302
        assert response.headers["location"] == f"/settings?tab={tab}"
    assert c.get("/config").headers["location"] == "/settings?tab=connection"
    # Removed endpoints are gone rather than silently changing settings.
    for path in ("/toggle-dry-run", "/run-now", "/dry-run", "/scheduler", "/config/system", "/config/komga"):
        assert c.post(path).status_code in (404, 405)


def test_automation_saves_schedule_watcher_and_publishing_choice(configured_client):
    from unittest.mock import Mock

    c, _ = configured_client
    raw = config_store.get_config_dict()
    raw["system"]["debug"] = True
    config_store.save_config_to_db(raw)
    callback = Mock()
    config_store.register_reload_callback(callback)
    page = c.get("/settings?tab=automation")
    assert 'name="debug"' not in page.text and 'name="dry_run"' not in page.text and 'name="workflow"' not in page.text
    assert 'value="review" checked' in page.text
    response = c.post("/settings/automation", data={
        "scheduler_enabled": "1", "run_at": "16:45", "watcher_enabled": "1",
        "polling_interval_minutes": "12", "after_fetch": "publish",
    })
    assert response.status_code == 303
    assert response.headers["location"] == "/settings?tab=automation&saved=1"
    callback.assert_called_once()
    system = config_store.get_config().system
    assert system.scheduler.enabled and system.scheduler.run_at == "16:45"
    assert system.watcher.enabled and system.watcher.polling_interval_minutes == 12
    assert system.auto_publish is True and system.debug is True
    home = c.get("/")
    assert "Fetches every day at 16:45" in home.text
    assert "published to Komga automatically" in home.text
    c.post("/settings/automation", data={"run_at": "04:00", "polling_interval_minutes": "5", "after_fetch": "review"})
    assert config_store.get_config().system.auto_publish is False
    assert config_store.get_config().system.scheduler.enabled is False


def test_invalid_automation_input_keeps_entries_and_saved_config(configured_client):
    c, _ = configured_client
    before = config_store.get_config_dict()
    for data in ({"polling_interval_minutes": "invalid", "run_at": "04:00"}, {"polling_interval_minutes": "5", "run_at": "25:70"}):
        response = c.post("/settings/automation", data=data)
        assert response.status_code == 200
        assert "Some values are invalid." in response.text
        assert config_store.get_config_dict() == before
    assert 'value="25:70"' in response.text


def test_defaults_save_rules_and_source_order(configured_client):
    c, _ = configured_client
    data = {
        "rule_summary": "fill", "rule_publisher": "keep", "rule_genres": "remove", "rule_status": "fill",
        "rule_cover_image": "keep", "rule_link": "fill", "rule_writers": "fill", "rule_pencillers": "keep",
        "rule_score": "fill", "rule_language": "remove", "rule_reading_direction": "keep",
        "existing_values": "replace", "locked_fields": "respect",
        "source_order": ["mangaupdates", "anilist", "mangadex"],
        "mangaupdates_enabled": "1", "anilist_enabled": "1", "anilist_min_score": "70",
    }
    response = c.post("/settings/defaults", data=data)
    assert response.status_code == 303
    cfg = config_store.get_config()
    p = cfg.processing
    assert p.update_fields.summary and not p.update_fields.publisher and not p.update_fields.genres
    assert p.remove_fields.genres and p.remove_fields.language and not p.remove_fields.reading_direction
    assert p.update_fields.authors.writers and not p.update_fields.authors.pencillers
    assert p.update_fields.tags.score and p.update_fields.link
    assert p.overwrite_existing is True and p.force_unlock is False
    assert [(s.name, s.priority, s.enabled) for s in cfg.providers] == [
        ("mangaupdates", 1, True), ("anilist", 2, True), ("mangadex", 3, False),
    ]
    assert next(s for s in cfg.providers if s.name == "anilist").min_score == 70
    page = c.get("/settings?tab=defaults").text
    assert 'id="rule-genres-remove" name="rule_genres" value="remove" checked' in page
    assert page.index('data-source="mangaupdates"') < page.index('data-source="anilist"') < page.index('data-source="mangadex"')


def test_translation_keeps_deepl_key_and_normalizes_language(configured_client):
    c, _ = configured_client
    c.post("/settings/translation", data={"enabled": "1", "provider": "deepl", "target_language": "fr", "deepl_api_key": "deepl-secret"})
    tr = config_store.get_config().translation
    assert tr.enabled and tr.provider == "deepl" and tr.target_language == "FR" and tr.deepl.api_key == "deepl-secret"
    c.post("/settings/translation", data={"provider": "deepl", "target_language": "en-us"})
    tr = config_store.get_config().translation
    assert tr.enabled is False and tr.deepl.api_key == "deepl-secret" and tr.target_language == "EN-US"
    c.post("/settings/translation", data={"provider": "google", "target_language": "en-us"})
    assert config_store.get_config().translation.target_language == "en"
    page = c.get("/settings?tab=translation").text
    assert '<option value="en-us" selected>' in page
    response = c.post("/settings/translation", data={"enabled": "1", "provider": "unknown"})
    assert response.status_code == 200 and "Some values are invalid." in response.text


def test_home_onboarding_chooses_libraries_and_starts_fetch(configured_client):
    c, _ = configured_client
    raw = config_store.get_config_dict()
    raw["komga"]["libraries"] = []
    config_store.save_config_to_db(raw)
    page = c.get("/")
    assert "Choose the libraries to manage" in page.text
    assert 'name="type_library-2"' in page.text
    response = c.post("/onboarding", data={})
    assert "message=onboarding.none" in response.headers["location"]
    assert c.app.state.job_queue.snapshot()["jobs"] == []
    response = c.post("/onboarding", data={"library": "library-2", "type_library-2": "webtoon", "type_library-1": "ebook"})
    assert response.status_code == 303
    cfg = config_store.get_config()
    assert cfg.komga.libraries == ["Webtoons"]
    assert cfg.library_settings["library-2"].content_type == "webtoon"
    assert cfg.library_settings["library-1"].content_type == "ebook"
    job = last_job()
    assert response.headers["location"] == f"/?queued={job['id']}"
    assert job["config"]["komga"]["libraries"] == ["Webtoons"]
    assert job["config"]["system"]["workflow"] == "collect" and job["config"]["system"]["dry_run"] is False


def test_home_shows_next_step_libraries_and_activity(configured_client):
    c, _ = configured_client
    page = c.get("/")
    assert page.status_code == 200
    assert "<h1>Home</h1>" in page.text
    assert "Everything is published" in page.text
    assert 'href="/libraries?library=library-1"' in page.text and "Webtoons" in page.text
    assert "No jobs yet" in page.text
    assert "Changes wait for your review" in page.text
    assert "Dry-Run" not in page.text and "Choose phases" not in page.text
    raw = config_store.get_config_dict()
    raw["komga"]["libraries"] = []
    raw["library_settings"] = {}
    config_store.save_config_to_db(raw)
    from modules.local_metadata import LocalCatalogue
    LocalCatalogue("http://komga:25600")
    with db.get_db() as conn:
        conn.execute("INSERT INTO local_metadata (server, entity, id, library_id, series_id, data) VALUES (?, 'series', 's', 'library-1', 's', '{}')",
                     ("http://komga:25600",))
    assert "No library is included" in c.get("/").text


def test_home_reports_connection_errors_without_details(configured_client):
    c, _ = configured_client
    with patch("modules.webui.routes.dashboard.known_libraries", side_effect=RuntimeError("private-host secret")):
        page = c.get("/")
    assert page.status_code == 200
    assert "KMM cannot reach Komga." in page.text
    assert "private-host" not in page.text


def test_fetch_queues_local_fetch_without_changing_settings(configured_client):
    c, _ = configured_client
    raw = config_store.get_config_dict()
    raw["system"].update(dry_run=True, workflow="push", overwrite_local=True)
    config_store.save_config_to_db(raw)
    before = config_store.get_config_dict()
    response = c.post("/fetch")
    job = last_job()
    assert response.status_code == 303 and response.headers["location"] == f"/?queued={job['id']}"
    system = job["config"]["system"]
    assert (system["workflow"], system["dry_run"], system["overwrite_local"]) == ("collect", False, False)
    assert job["config"]["komga"]["libraries"] == ["Manga"]
    assert job["source"] == "manual" and job["series_ids"] is None
    assert config_store.get_config_dict() == before
    c.post("/fetch", data={"library_id": "library-2", "next": "/libraries?library=library-2"})
    assert last_job()["config"]["komga"]["libraries"] == ["Webtoons"]
    response = c.post("/fetch", data={"next": "//evil.example/"})
    assert response.headers["location"].startswith("/?queued=")
    response = c.post("/fetch", data={"library_id": "missing"})
    assert "message=queue.no_libraries" in response.headers["location"]
    assert len(c.app.state.job_queue.snapshot()["jobs"]) == 3
    assert any(e["action"] == "JOB_QUEUED" for e in db.get_audit_log())
    assert "Fetch #1 started" in c.get("/?queued=1").text


def test_fetch_reports_full_queue_and_missing_libraries(configured_client, monkeypatch):
    c, _ = configured_client
    monkeypatch.setattr("modules.job_queue.MAX_PENDING", 1)
    c.post("/fetch")
    response = c.post("/fetch")
    assert "message=queue.full" in response.headers["location"]
    assert "100 jobs are already waiting" in c.get(response.headers["location"]).text
    raw = config_store.get_config_dict()
    raw["komga"]["libraries"] = []
    config_store.save_config_to_db(raw)
    assert "message=queue.no_libraries" in c.post("/fetch").headers["location"]
    assert len(c.app.state.job_queue.snapshot()["jobs"]) == 1


def test_job_actions_cancel_retry_and_validate_state(configured_client):
    c, _ = configured_client
    c.post("/fetch")
    job_id = c.app.state.job_queue.snapshot()["jobs"][0]["id"]
    assert "Waiting" in c.get("/status").text
    hx = {"HX-Request": "true"}
    response = c.post(f"/jobs/{job_id}/cancel", headers=hx)
    assert response.status_code == 200 and 'id="activity-strip"' in response.text
    assert "Cancelled" in response.text
    assert "already changed state" in c.post(f"/jobs/{job_id}/kill", headers=hx).text
    response = c.post(f"/jobs/{job_id}/retry")
    assert response.status_code == 303
    new = c.app.state.job_queue.snapshot()["jobs"][0]
    assert new["source"] == "retry" and new["status"] == "queued"
    assert response.headers["location"] == f"/logs/jobs/{new['id']}"
    response = c.post("/jobs/99999/cancel")
    assert response.status_code == 303 and "message=queue.action_unavailable" in response.headers["location"]
    assert "already changed state" in c.post(f"/jobs/{job_id}/unknown", headers=hx).text


def test_job_actions_require_auth_and_same_origin(configured_client):
    c, _ = configured_client
    c.post("/fetch")
    job_id = c.app.state.job_queue.snapshot()["jobs"][0]["id"]
    for action in ("cancel", "kill", "retry"):
        assert c.post(f"/jobs/{job_id}/{action}", headers={"Origin": "https://other.example"}).status_code == 403
    c.cookies.clear()
    for action in ("cancel", "kill", "retry"):
        assert c.post(f"/jobs/{job_id}/{action}").status_code == 302
    assert c.app.state.job_queue.snapshot()["jobs"][0]["status"] == "queued"


def test_activity_tabs_job_list_and_detail(configured_client):
    c, _ = configured_client
    assert 'id="job-list"' in c.get("/logs").text
    assert 'id="audit-log-lines"' in c.get("/logs?tab=history").text
    assert 'id="audit-log-lines"' in c.get("/logs?tab=audit").text
    assert 'id="exec-log-lines"' in c.get("/logs?tab=technical").text
    assert 'id="exec-log-lines"' in c.get("/logs?tab=exec").text
    assert 'value="DEBUG"' in c.get("/logs?tab=technical").text
    assert c.get("/logs/jobs").headers["location"] == "/logs"
    assert "No jobs yet" in c.get("/logs/jobs/list").text
    c.post("/fetch")
    job_id = last_job()["id"]
    listing = c.get("/logs/jobs/list").text
    assert f'href="/logs/jobs/{job_id}"' in listing and "Fetch" in listing and "Manga" in listing
    assert "every 3s" in listing
    detail = c.get(f"/logs/jobs/{job_id}").text
    assert "Komga is not modified" in detail
    assert "secret" not in detail
    assert f'action="/jobs/{job_id}/cancel"' in detail
    assert c.get("/logs/jobs/list?page=0").status_code == 422


def test_review_page_without_changes_and_navigation(configured_client):
    c, _ = configured_client
    page = c.get("/review")
    assert page.status_code == 200
    assert "Nothing to review" in page.text
    assert 'href="/review" class="nav-item active" aria-current="page"' in page.text
    assert 'class="nav-count"' not in page.text
    response = c.post("/review/publish")
    assert "message=review.nothing" in response.headers["location"]
    assert c.app.state.job_queue.snapshot()["jobs"] == []
