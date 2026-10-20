"""Integration coverage for per-library rules, targeted writes and durable logs."""

import json
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from modules.config import LibraryConfig, ProcessingConfig, ProviderConfig, TranslationConfig, config_for_library
from modules.job_queue import JobQueue
from modules.models import KomgaBook, KomgaLibrary, MetadataCreator, MetadataRecord
from modules.processor import process_libraries, process_single_series
from modules.providers import get_providers
from modules.webui import auth, config_store, db, log_buffer
from modules.webui.app import create_app
from modules.webui.forms import ordered_sources, rule_choices


def book(book_id, series_id="series-1"):
    return KomgaBook.model_validate(
        {
            "id": book_id,
            "seriesId": series_id,
            "name": book_id,
            "number": 1,
            "metadata": {
                "title": book_id,
                "titleLock": False,
                "summary": "",
                "summaryLock": False,
                "number": "1",
                "numberLock": False,
                "numberSort": 1,
                "numberSortLock": False,
                "releaseDateLock": False,
                "authors": [],
                "authorsLock": False,
                "tagsLock": False,
            },
        }
    )


def test_book_title_settings_are_local_to_library_and_keep_invalid_entries(library_client):
    client, remote = library_client
    response = client.get("/libraries?library=library-1&tab=settings")
    assert 'name="book_title_mode"' in response.text
    assert '<option value="off" selected>' in response.text
    form = {
        "enabled": "on", "content_type": "manga", "book_title_mode": "custom",
        "book_title_template": "{series} - Volume {number}", "book_title_padding": "3",
    }
    response = client.post("/libraries/library-1/settings", data=form)
    assert response.status_code == 303
    cfg = config_store.get_config()
    effective = config_for_library(cfg, "library-1")
    assert effective.processing.book_titles.mode == "custom"
    assert effective.processing.book_titles.padding == 3
    assert cfg.processing.book_titles.mode == "off"
    assert config_for_library(cfg, "library-2").processing.book_titles.mode == "off"
    response = client.post("/libraries/library-1/settings", data={**form, "book_title_template": "{number:03}"})
    assert response.status_code == 200
    assert 'value="{number:03}"' in response.text
    assert "Your settings have not been saved" in response.text
    assert config_for_library(config_store.get_config(), "library-1").processing.book_titles.template == form["book_title_template"]
    remote.update_book_metadata.assert_not_called()
    client.post("/libraries/library-1/settings", data={"reset": "rules"})
    assert config_for_library(config_store.get_config(), "library-1").processing.book_titles.mode == "off"


@pytest.fixture
def library_client(tmp_path, app_config, series, monkeypatch):
    db.init_db(tmp_path / "libraries.db")
    auth._serializer = None
    config_store._config = None
    config_store._reload_callback = None
    db.create_user("admin", auth.hash_password("LibraryTests123!"))
    config_store.save_config_to_db(app_config.model_dump(mode="json"))
    queue = JobQueue()
    monkeypatch.setattr(queue, "start", lambda: None)
    fake = Mock()
    fake.get_libraries.return_value = [
        KomgaLibrary(id="library-1", name="Manga"),
        KomgaLibrary(id="library-2", name="Ebooks"),
    ]
    fake.get_series_in_library.return_value = [series]
    fake.get_books_in_series.return_value = [book("book-1"), book("book-2")]
    fake.base_url = "http://komga:25600"
    with (
        patch("modules.webui.routes.libraries.KomgaClient", return_value=fake),
        patch("modules.webui.routes.dashboard.KomgaClient", return_value=fake),
    ):
        with TestClient(create_app(queue), follow_redirects=False) as client:
            client.cookies.set(auth.SESSION_COOKIE, auth.create_session_token("admin"))
            yield client, fake
    config_store._reload_callback = None


def test_durable_job_output_survives_live_clear_and_keeps_all_pages(library_client):
    client, _ = library_client
    queue = client.app.state.job_queue
    first = queue.enqueue(config_store.get_config())
    second = queue.enqueue(config_store.get_config())
    for index in range(605):
        queue._read_output(first, json.dumps({"type": "log", "level": 10, "message": f"entry-{index}"}))
    queue._read_output(second, "other job output")
    log_buffer.clear_buffer()
    assert "entry-" not in client.get(f"/logs/jobs/{first}/lines").text
    assert "entry-0" in client.get(f"/logs/jobs/{first}/lines?page=1&levels=DEBUG").text
    assert "entry-604" in client.get(f"/logs/jobs/{first}/lines?page=4&levels=DEBUG").text
    assert "other job output" not in client.get(f"/logs/jobs/{first}/download").text
    download = client.get(f"/logs/jobs/{first}/download")
    assert len(download.text.splitlines()) == 605
    assert "entry-0" in download.text and "entry-604" in download.text
    assert "secret" not in client.get(f"/logs/jobs/{first}").text
    assert client.get(f"/logs/jobs/{first}/lines?page=0").status_code == 422
    assert client.get("/logs/jobs/9999").status_code == 404
    client.cookies.clear()
    assert client.get(f"/logs/jobs/{first}/download").status_code == 302
    assert client.get(f"/logs/jobs/{first}/lines").status_code == 401


def test_library_config_resolves_overrides_without_mutating_globals(app_config):
    app_config.translation = TranslationConfig(enabled=True, target_language="fr")
    app_config.library_settings["library-1"] = LibraryConfig(
        name="Manga",
        processing=ProcessingConfig(overwrite_existing=True),
        translation_enabled=False,
        target_language="de",
        providers=[ProviderConfig(name="mangadex", priority=1)],
    )
    effective = config_for_library(app_config, "library-1")
    assert effective.processing.overwrite_existing is True
    assert effective.translation.enabled is False
    assert effective.translation.target_language == "de"
    assert app_config.processing.overwrite_existing is False
    assert app_config.translation.enabled is True
    assert config_for_library(app_config, "another").processing == app_config.processing


def test_disabled_provider_is_never_initialized(tmp_path):
    with patch("modules.providers.get_provider") as create:
        chain = get_providers([ProviderConfig(enabled=False)], tmp_path)
    assert chain.entries == []
    create.assert_not_called()


def test_per_library_processing_uses_each_profile_and_skips_disabled(app_config, series):
    app_config.komga.libraries = ["Manga", "Webtoons"]
    app_config.library_settings = {
        "library-1": LibraryConfig(name="Manga", processing=ProcessingConfig(overwrite_existing=True)),
        "library-2": LibraryConfig(name="Webtoons", processing=ProcessingConfig(force_unlock=True)),
    }
    fake = Mock()
    fake.get_libraries.return_value = [
        KomgaLibrary(id="library-1", name="Manga"),
        KomgaLibrary(id="library-2", name="Webtoons"),
        KomgaLibrary(id="library-3", name="Ebooks"),
    ]
    fake.get_series_in_library.side_effect = lambda lib_id, name: [series.model_copy(update={"library_id": lib_id})]
    with (
        patch("modules.processor.KomgaClient", return_value=fake),
        patch("modules.processor.get_providers", return_value=Mock()),
        patch("modules.processor.Path.mkdir"),
        patch("modules.processor.process_single_series") as process,
    ):
        result = process_libraries(app_config)
    assert result.processed == 2
    configs = [call.args[1] for call in process.call_args_list]
    assert configs[0].processing.overwrite_existing is True
    assert configs[1].processing.overwrite_existing is False
    assert configs[1].processing.force_unlock is True
    assert [call.args[0] for call in fake.get_series_in_library.call_args_list] == ["library-1", "library-2"]


@pytest.mark.parametrize("dry_run", [True, False])
def test_targeted_book_preserves_other_books_authors(app_config, series, dry_run):
    app_config.system.dry_run = dry_run
    app_config.processing.overwrite_existing = True
    app_config.processing.update_fields.cover_image = False
    fake = Mock()
    fake.get_books_in_series.return_value = [book("book-1"), book("book-2")]
    metadata = MetadataRecord(
        provider="anilist",
        external_id="1",
        titles=["Example Manga"],
        creators=[MetadataCreator(name="Writer", role="writer")],
    )
    with patch("modules.processor._find_metadata_with_fallback", return_value=metadata):
        changes = process_single_series(series, app_config, fake, Mock(), None, book_ids=["book-2"])
    if dry_run:
        fake.update_book_metadata.assert_not_called()
        assert any("book-2" in line for line in changes)
        assert not any("book-1" in line for line in changes)
    else:
        fake.update_book_metadata.assert_called_once()
        assert fake.update_book_metadata.call_args.args[0] == "book-2"


def test_rejected_write_is_reported_as_failure(app_config, series):
    app_config.system.dry_run = False
    app_config.processing.overwrite_existing = True
    app_config.processing.update_fields.cover_image = False
    app_config.processing.update_fields.authors.writers = False
    app_config.processing.update_fields.authors.pencillers = False
    fake = Mock()
    fake.update_series_metadata.return_value = False
    metadata = MetadataRecord(provider="anilist", external_id="1", titles=["Example Manga"], description="New summary")
    with patch("modules.processor._find_metadata_with_fallback", return_value=metadata):
        with pytest.raises(RuntimeError, match="Komga rejected"):
            process_single_series(series, app_config, fake, Mock(), None)


def test_rejected_author_removal_marks_series_failed(app_config, series):
    app_config.system.dry_run = False
    app_config.processing.remove_fields.authors.writers = True
    selected = book("book-1")
    selected.metadata.authors = [{"name": "Writer", "role": "writer"}]
    fake = Mock()
    fake.get_books_in_series.return_value = [selected]
    fake.update_book_metadata.return_value = False
    with pytest.raises(RuntimeError, match="Could not remove authors"):
        process_single_series(series, app_config, fake, Mock(), None, book_ids=["book-1"])


def test_book_thumbnail_requests_image_and_does_not_expose_credentials(library_client):
    client, fake = library_client
    fake.base_url = "http://komga:25600"
    fake.headers = {"X-API-Key": "private", "Accept": "application/json"}
    fake.verify_ssl = True
    fake.session.get.return_value.content = b"cover image bytes"
    fake.session.get.return_value.headers = {"content-type": "image/jpeg"}
    response = client.get("/libraries/library-1/books/book-1/thumbnail")
    assert response.status_code == 200
    assert response.content == b"cover image bytes"
    assert fake.session.get.call_args.kwargs["headers"]["Accept"] == "image/*"
    assert "X-API-Key" not in response.headers
    fake.session.get.return_value.close.assert_called_once()


def test_watcher_queues_using_library_exclusions_instead_of_global_rules(app_config, series):
    from modules.processor import watch_for_new_series

    app_config.processing.exclude_series = [series.name]
    app_config.library_settings["library-1"] = LibraryConfig(
        name="Manga", processing=ProcessingConfig(exclude_series=["Excluded by library"])
    )
    excluded = series.model_copy(update={"id": "series-2", "name": "Excluded by library"})
    fake = Mock()
    fake.get_series_in_library.return_value = [series, excluded]
    enqueue = Mock()
    result = watch_for_new_series(
        app_config,
        fake,
        {"Manga": "library-1"},
        {"library-1": set()},
        Mock(),
        None,
        enqueue_series=enqueue,
    )
    assert result.found == 2
    enqueue.assert_called_once_with([series.id])


def test_ebook_library_displays_books_and_saved_type_takes_precedence(library_client, series):
    client, fake = library_client
    fake.get_series_in_library.return_value = [series.model_copy(update={"library_id": "library-2"})]
    response = client.get("/libraries/library-2/content")
    assert 'data-book-id="book-1"' in response.text
    assert 'data-book-id="book-2"' in response.text
    assert "2 books" in response.text
    fake.get_books_in_series.assert_called_once()
    raw = config_store.get_config_dict()
    raw["library_settings"]["library-2"] = {"name": "Ebooks", "content_type": "webtoon"}
    config_store.save_config_to_db(raw)
    fake.get_books_in_series.reset_mock()
    response = client.get("/libraries/library-2/content")
    assert 'data-book-id=""' in response.text
    assert "1 series" in response.text
    fake.get_books_in_series.assert_not_called()




def settings_form(cfg=None, **overrides) -> dict:
    """The library settings form as the browser submits it, filled with the current defaults."""
    raw = (cfg or config_store.get_config()).model_dump(mode="json")
    data = {f"rule_{name}": choice for name, choice in rule_choices(raw["processing"]).items()}
    data["existing_values"] = "replace" if raw["processing"]["overwrite_existing"] else "keep"
    data["locked_fields"] = "change" if raw["processing"]["force_unlock"] else "respect"
    data["source_order"] = []
    for source in ordered_sources(raw["providers"]):
        name = source["name"]
        data["source_order"].append(name)
        if source["enabled"]:
            data[f"{name}_enabled"] = "1"
        if source["allow_adult"]:
            data[f"{name}_allow_adult"] = "1"
        data[f"{name}_min_score"] = str(source["min_score"])
        data[f"{name}_preferred_language"] = source["preferred_language"]
        data[f"{name}_cache_ttl"] = str(source["cache"]["ttl_hours"])
    data["translation_mode"] = "default"
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def last_job():
    with db.get_db() as conn:
        return conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 1").fetchone()


def test_library_settings_inherit_defaults_until_customized(library_client):
    client, _ = library_client
    response = client.post("/libraries/library-2/settings", data=settings_form(enabled="1", content_type="ebook"))
    assert response.status_code == 303
    assert response.headers["location"] == "/libraries?library=library-2&tab=settings&saved=1"
    saved = config_store.get_config()
    assert saved.komga.libraries == ["Manga", "Ebooks"]
    profile = saved.library_settings["library-2"]
    assert profile.content_type == "ebook"
    # Submitting the defaults unchanged keeps following future default changes.
    assert profile.processing is None and profile.providers is None
    page = client.get(response.headers["location"]).text
    assert "Library settings saved" in page and "Uses defaults" in page
    client.post("/libraries/library-2/settings", data=settings_form(
        enabled="1", content_type="ebook", rule_summary="keep", rule_publisher="remove",
        translation_mode="on", target_language="fr",
    ))
    saved = config_store.get_config()
    profile = saved.library_settings["library-2"]
    assert profile.processing.update_fields.summary is False
    assert profile.processing.remove_fields.publisher is True
    assert saved.processing.update_fields.summary is True and saved.processing.remove_fields.publisher is False
    assert profile.providers is None
    assert profile.translation_enabled is True and profile.target_language == "fr"
    assert config_for_library(saved, "library-1").processing == saved.processing
    assert "Use defaults" in client.get("/libraries?library=library-2&tab=settings").text
    # The connection tab keeps the library selection.
    client.post("/settings/connection", data={"url": "http://komga:25600", "api_key": "secret", "verify_ssl": "1"})
    assert config_store.get_config().komga.libraries == ["Manga", "Ebooks"]
    client.post("/libraries/library-2/settings", data={"reset": "rules"})
    profile = config_store.get_config().library_settings["library-2"]
    assert profile.processing is None and profile.translation_enabled is True
    assert config_store.get_config().komga.libraries == ["Manga", "Ebooks"]
    client.post("/libraries/library-2/settings", data=settings_form(content_type="ebook", translation_mode="off"))
    saved = config_store.get_config()
    assert saved.komga.libraries == ["Manga"]
    assert saved.library_settings["library-2"].translation_enabled is False
    assert saved.library_settings["library-2"].target_language is None


def test_library_sources_order_enable_and_invalid_form(library_client):
    client, _ = library_client
    data = settings_form(section="sources", source_order=["mangadex", "anilist", "mangaupdates"], anilist_enabled=None, mangaupdates_enabled=None)
    assert client.post("/libraries/library-1/settings", data=data).status_code == 303
    cfg = config_store.get_config()
    effective = config_for_library(cfg, "library-1")
    assert [p.name for p in effective.providers if p.enabled] == ["mangadex"]
    assert [p.name for p in sorted(effective.providers, key=lambda p: p.priority)] == ["mangadex", "anilist", "mangaupdates"]
    assert all(p.enabled for p in cfg.providers)
    client.post("/libraries/library-1/settings", data={"reset": "sources"})
    assert config_store.get_config().library_settings["library-1"].providers is None
    before = config_store.get_config_dict()
    response = client.post("/libraries/library-1/settings", data=settings_form(section="sources", anilist_min_score="500"))
    assert response.status_code == 200
    assert "Some settings are invalid" in response.text
    assert config_store.get_config_dict() == before


def test_invalid_library_settings_keep_entries(library_client):
    client, _ = library_client
    response = client.post("/libraries/library-1/settings", data=settings_form(section="sources", anilist_min_score="500"))
    assert 'value="500"' in response.text


def test_sources_tab_is_second_and_saves_without_changing_settings(library_client):
    client, _ = library_client
    client.post("/libraries/library-1/settings", data=settings_form(
        enabled="1", content_type="webtoon", locked_fields="change", rule_summary="keep",
        translation_mode="on", target_language="fr",
    ))
    before = config_store.get_config_dict()
    response = client.get("/libraries?library=library-1&tab=sources")
    assert response.status_code == 200
    tabs = response.text.split('aria-label="Library views"')[1].split('</nav>')[0]
    assert tabs.index('>Series</a>') < tabs.index('Metadata sources</a>') < tabs.index('Settings</a>')
    assert 'name="section" value="sources"' in response.text
    assert 'name="rule_summary"' not in response.text
    response = client.post("/libraries/library-1/settings", data=settings_form(
        section="sources", anilist_enabled=None, source_order=["mangadex", "mangaupdates", "anilist"],
    ))
    assert response.headers["location"] == "/libraries?library=library-1&tab=sources&saved=1"
    after = config_store.get_config_dict()
    assert after["komga"] == before["komga"]
    for key in before["library_settings"]["library-1"]:
        if key != "providers":
            assert after["library_settings"]["library-1"][key] == before["library_settings"]["library-1"][key]
    saved_sources = after["library_settings"]["library-1"]["providers"]
    assert saved_sources[0]["name"] == "mangadex"
    assert not next(source for source in saved_sources if source["name"] == "anilist")["enabled"]
    client.post("/libraries/library-1/settings", data=settings_form(enabled="1"))
    assert config_store.get_config_dict()["library_settings"]["library-1"]["providers"] == saved_sources
    response = client.post("/libraries/library-1/settings", data={"section": "sources", "reset": "sources"})
    assert "tab=sources" in response.headers["location"]
    assert config_store.get_config().library_settings["library-1"].providers is None


def test_library_settings_reject_unknown_library_and_keep_other_profiles(library_client):
    client, _ = library_client
    raw = config_store.get_config_dict()
    raw["library_settings"]["library-2"] = {"name": "Ebooks", "content_type": "ebook", "exclude_series": ["Kept"]}
    config_store.save_config_to_db(raw)
    before = config_store.get_config_dict()
    assert client.post("/libraries/unknown/settings", data=settings_form()).status_code == 404
    assert config_store.get_config_dict() == before
    client.post("/libraries/library-1/settings", data=settings_form(content_type="webtoon"))
    after = config_store.get_config_dict()
    assert after["komga"]["libraries"] == []
    assert after["library_settings"]["library-1"]["content_type"] == "webtoon"
    assert after["library_settings"]["library-2"] == before["library_settings"]["library-2"]
    assert after["processing"] == before["processing"] and after["providers"] == before["providers"]
    page = client.get("/libraries?library=library-1&tab=settings").text
    assert 'id="anilist_enabled"' not in page and 'name="rule_summary"' in page
    assert 'href="/libraries?library=library-1&tab=settings" aria-current="page"' in page


def test_targeted_fetch_snapshot_and_wrong_series_or_book_rejected(library_client):
    client, _ = library_client
    raw = config_store.get_config_dict()
    raw["system"]["dry_run"] = True
    raw["processing"]["force_unlock"] = True
    config_store.save_config_to_db(raw)
    before = config_store.get_config_dict()
    response = client.post(
        "/libraries/library-1/fetch", data={"series_id": "series-1", "book_id": "book-2", "replace_edits": "1"},
    )
    assert response.status_code == 303
    row = last_job()
    assert response.headers["location"] == f"/libraries?library=library-1&queued={row['id']}"
    cfg = json.loads(row["config"])
    assert cfg["system"]["workflow"] == "collect"
    assert cfg["system"]["dry_run"] is False
    assert cfg["system"]["overwrite_local"] is True
    assert cfg["processing"]["overwrite_existing"] is True
    assert cfg["processing"]["force_unlock"] is True
    assert cfg["komga"]["libraries"] == ["Manga"]
    assert json.loads(row["book_ids"]) == ["book-2"]
    assert json.loads(row["series_ids"]) == ["series-1"]
    assert config_store.get_config_dict() == before
    client.post("/libraries/library-1/fetch", data={"series_id": "series-1", "book_id": "book-1"})
    assert json.loads(last_job()["config"])["system"]["overwrite_local"] is False
    for library_id, data in [
        ("library-2", {"series_id": "series-1", "book_id": "book-2"}),
        ("library-1", {"series_id": "series-1", "book_id": "wrong-book"}),
        ("library-1", {"series_id": "unknown"}),
        ("unknown", {}),
    ]:
        response = client.post(f"/libraries/{library_id}/fetch", data=data)
        assert "message=libraries.fetch_error" in response.headers["location"]
    assert len(client.app.state.job_queue.snapshot()["jobs"]) == 2


def test_targeted_fetch_overrides_only_the_library_profile(library_client):
    client, _ = library_client
    client.post("/libraries/library-1/settings", data=settings_form(enabled="1", rule_summary="keep"))
    before = config_store.get_config_dict()
    client.post("/libraries/library-1/fetch", data={"series_id": "series-1"})
    cfg = json.loads(last_job()["config"])
    assert cfg["library_settings"]["library-1"]["processing"]["overwrite_existing"] is True
    assert cfg["processing"]["overwrite_existing"] is False
    assert config_store.get_config_dict() == before


def test_whole_library_fetch_keeps_rules_and_works_when_not_included(library_client):
    client, _ = library_client
    raw = config_store.get_config_dict()
    raw["komga"]["libraries"] = []
    config_store.save_config_to_db(raw)
    response = client.post("/libraries/library-1/fetch")
    assert response.status_code == 303
    row = last_job()
    cfg = json.loads(row["config"])
    assert cfg["komga"]["libraries"] == ["Manga"]
    assert cfg["processing"]["overwrite_existing"] is False
    assert cfg["system"]["overwrite_local"] is False
    assert json.loads(row["series_ids"]) is None
    assert config_store.get_config_dict() == raw


def test_not_included_library_stays_editable(library_client):
    client, _ = library_client
    raw = config_store.get_config_dict()
    raw["komga"]["libraries"] = []
    config_store.save_config_to_db(raw)
    content = client.get("/libraries/library-1/content")
    assert 'data-overwrite' in content.text and "disabled" not in content.text.split("book-grid", 1)[1]
    page = client.get("/libraries?library=library-1")
    assert "Not included" in page.text
    assert 'action="/libraries/library-1/fetch"' in page.text
    assert config_store.get_config_dict() == raw


def test_library_content_empty_connection_and_navigation(library_client):
    client, fake = library_client
    response = client.get("/libraries?library=library-1")
    assert response.status_code == 200
    assert 'id="overwrite-dialog"' in response.text
    assert 'class="workspace-footer"' not in response.text
    assert "github.com/simon-verbois/Komga-Meta-Manager" in response.text
    assert 'aria-current="page"' in response.text.split('class="pill-nav"', 1)[1]
    content = client.get("/libraries/library-1/content")
    assert 'data-series-id="series-1"' in content.text
    assert 'data-book-id=""' in content.text
    assert "1 series" in content.text
    assert 'data-missing="1"' in content.text
    fake.get_books_in_series.assert_not_called()
    fake.get_series_in_library.return_value = []
    # Browsing keeps the imported local catalogue until the next fetch.
    assert 'data-series-id="series-1"' in client.get("/libraries/library-1/content").text
    with db.get_db() as conn:
        conn.execute("DELETE FROM local_metadata")
    assert "No series yet" in client.get("/libraries/library-1/content").text
    fake.get_libraries.side_effect = RuntimeError("Secret connection failure")
    with db.get_db() as conn:
        conn.execute("DELETE FROM local_libraries")
    page = client.get("/libraries").text
    assert "KMM cannot reach Komga" in page
    assert "Secret connection failure" not in page
    fake.get_series_in_library.side_effect = RuntimeError("Secret connection failure")
    content = client.get("/libraries/library-1/content").text
    assert "could not be loaded" in content and "Secret" not in content


def test_content_and_fetch_cannot_escape_selected_library(library_client, series):
    client, fake = library_client
    fake.get_series_in_library.return_value = [series.model_copy(update={"library_id": "other-library"})]
    assert "data-overwrite" not in client.get("/libraries/library-1/content").text
    result = client.post("/libraries/library-1/fetch", data={"series_id": series.id})
    assert "message=libraries.fetch_error" in result.headers["location"]
    assert client.app.state.job_queue.snapshot()["jobs"] == []


def test_series_fetch_targets_all_books_in_one_series(library_client):
    client, fake = library_client
    response = client.post("/libraries/library-1/fetch", data={"series_id": "series-1"})
    assert response.status_code == 303
    fake.get_books_in_series.assert_not_called()
    job = last_job()
    assert json.loads(job["series_ids"]) == ["series-1"]
    assert json.loads(job["book_ids"]) is None
    assert json.loads(job["config"])["system"]["dry_run"] is False


def test_ebook_fetch_targets_one_book(library_client, series):
    client, fake = library_client
    fake.get_series_in_library.return_value = [series.model_copy(update={"library_id": "library-2"})]
    result = client.post("/libraries/library-2/fetch", data={"series_id": series.id, "book_id": "book-2"})
    assert result.status_code == 303
    assert json.loads(last_job()["book_ids"]) == ["book-2"]


def test_ebook_fetch_requires_book(library_client, series):
    client, fake = library_client
    raw = config_store.get_config_dict()
    raw["library_settings"]["library-2"] = {"name": "Ebooks", "content_type": "ebook"}
    config_store.save_config_to_db(raw)
    fake.get_series_in_library.return_value = [series.model_copy(update={"library_id": "library-2"})]
    result = client.post("/libraries/library-2/fetch", data={"series_id": series.id})
    assert "message=libraries.fetch_error" in result.headers["location"]


def test_skip_series_updates_library_exclusions(library_client):
    client, _ = library_client
    raw = config_store.get_config_dict()
    raw["processing"]["exclude_series"] = ["Example Manga"]
    raw["library_settings"]["library-1"] = {
        "name": "Manga", "processing": {**raw["processing"], "exclude_series": ["Example Manga", "Other"]},
    }
    config_store.save_config_to_db(raw)
    response = client.post("/libraries/library-1/skip", data={"series_name": "Example Manga", "skip": "0"})
    assert response.json() == {"skipped": False}
    cfg = config_store.get_config()
    assert "Example Manga" not in config_for_library(cfg, "library-1").processing.exclude_series
    assert "Other" in config_for_library(cfg, "library-1").processing.exclude_series
    assert cfg.processing.exclude_series == []
    assert 'data-skipped="0"' in client.get("/libraries/library-1/content").text
    assert client.post("/libraries/library-1/skip", data={"series_name": "Example Manga", "skip": "1"}).json() == {"skipped": True}
    cfg = config_store.get_config()
    assert cfg.library_settings["library-1"].exclude_series == ["Example Manga"]
    assert "Example Manga" in config_for_library(cfg, "library-1").processing.exclude_series
    assert "Example Manga" not in config_for_library(cfg, "library-2").processing.exclude_series
    assert 'data-skipped="1"' in client.get("/libraries/library-1/content").text
    assert client.post("/libraries/unknown/skip", data={"series_name": "Example Manga", "skip": "1"}).status_code == 404
    assert client.post("/libraries/library-1/skip", data={"series_name": " ", "skip": "1"}).status_code == 404
    client.cookies.clear()
    assert client.post("/libraries/library-1/skip", data={"series_name": "Example Manga"}).status_code == 401


def test_check_and_remove_missing_series(library_client):
    from modules.local_metadata import LocalCatalogue

    client, remote = library_client
    client.get('/libraries/library-1/content')
    store = LocalCatalogue(remote.base_url)
    store.patch('series', 'series-1', {'summary': 'My unpublished draft'}, manual=True)
    remote.get_series_in_library.return_value = []
    response = client.post('/libraries/library-1/check')
    assert 'catalogue_notice=libraries.checked' in response.headers['location']
    content = client.get('/libraries/library-1/content').text
    assert 'data-absent="1"' in content
    assert 'Missing from Komga' in content
    assert 'data-confirm=' in content and 'aria-label="Remove Example Manga from KMM"' in content
    assert json.loads(store.get('series', 'series-1')['pending'])['summary'] == 'My unpublished draft'
    response = client.post('/libraries/library-1/remove-missing', data={'series_id': 'series-1'})
    assert 'catalogue_notice=libraries.removed' in response.headers['location']
    assert store.get('series', 'series-1') is None
    remote.update_series_metadata.assert_not_called()
    remote.update_book_metadata.assert_not_called()


def test_remove_local_series_keeps_other_scopes_and_never_contacts_komga(library_client):
    from modules.local_metadata import LocalCatalogue, LocalKomgaClient

    client, remote = library_client
    client.get('/libraries/library-1/content')
    store = LocalCatalogue(remote.base_url)
    series = store.items('series', 'library-1')[0]
    store.import_item('books', book('book-1'), 'library-1', series.id)
    store.patch('series', series.id, {'summary': 'Draft'}, manual=True)
    store.patch('books', 'book-1', {'summary': 'Book draft'}, manual=True)
    other = series.model_copy(update={'id': 'other-series', 'library_id': 'library-2'})
    store.import_item('series', other, 'library-2', other.id)
    other_server = LocalCatalogue('http://other-komga')
    other_server.import_item('series', series, 'library-1', series.id)
    remote.reset_mock()

    response = client.post(f'/libraries/library-1/series/{series.id}/remove')

    assert 'catalogue_notice=libraries.item_removed' in response.headers['location']
    assert store.get('series', series.id) is None
    assert store.get('books', 'book-1') is None
    assert store.get('series', other.id) is not None
    assert other_server.get('series', series.id) is not None
    assert store.pending_counts() == {}
    assert not remote.mock_calls
    assert 'data-book-title=' not in client.get('/libraries/library-1/content').text
    remote.get_series_in_library.assert_not_called()
    # An intentional Fetch can reimport an object still in Komga.
    assert LocalKomgaClient(remote, refresh=True).get_series_in_library('library-1', 'Manga')
    assert store.get('series', series.id) is not None


def test_remove_local_book_preserves_parent_and_siblings(library_client):
    from modules.local_metadata import LocalCatalogue, LocalKomgaClient

    client, remote = library_client
    client.get('/libraries/library-1/content')
    store = LocalCatalogue(remote.base_url)
    for identifier in ('book-1', 'book-2'):
        store.import_item('books', book(identifier), 'library-1', 'series-1')
    remote.reset_mock()
    response = client.post('/libraries/library-1/books/book-1/remove')
    assert 'catalogue_notice=libraries.item_removed' in response.headers['location']
    assert store.get('books', 'book-1') is None
    assert store.get('books', 'book-2') is not None
    assert store.get('series', 'series-1') is not None
    client.post('/libraries/library-1/books/book-2/remove')
    local = LocalKomgaClient(remote, refresh=False)
    local.get_series_in_library('library-1', 'Manga')
    assert local.get_books_in_series('series-1', 'Example Manga') == []
    assert not remote.mock_calls


def test_remove_local_rejects_wrong_library_unknown_item_and_unauthenticated(library_client):
    from modules.local_metadata import LocalCatalogue

    client, remote = library_client
    content = client.get('/libraries/library-1/content').text
    assert '/libraries/library-1/series/series-1/remove' in content
    assert 'Komga metadata, books and files will NOT be changed or deleted' in content
    for path in ('library-2/series/series-1', 'library-1/series/unknown'):
        response = client.post(f'/libraries/{path}/remove')
        assert 'message=libraries.remove_item_unavailable' in response.headers['location']
    assert LocalCatalogue(remote.base_url).get('series', 'series-1') is not None
    client.cookies.clear()
    assert client.post('/libraries/library-1/series/series-1/remove').headers['location'] == '/login'


def test_remove_local_database_failure_shows_actionable_error(library_client):
    client, _ = library_client
    with patch('modules.local_metadata.LocalCatalogue.remove_item', side_effect=RuntimeError('Private error')):
        response = client.post('/libraries/library-1/series/series-1/remove')
    assert 'message=libraries.remove_error' in response.headers['location']


def test_remove_missing_rechecks_remote_and_keeps_edits_on_failure(library_client):
    from modules.local_metadata import LocalCatalogue

    client, remote = library_client
    client.get('/libraries/library-1/content')
    store = LocalCatalogue(remote.base_url)
    store.reconcile_series('library-1', set())
    response = client.post('/libraries/library-1/remove-missing', data={'series_id': 'series-1'})
    assert 'message=libraries.remove_unavailable' in response.headers['location']
    assert store.get('series', 'series-1')['missing'] == 0
    store.patch('series', 'series-1', {'summary': 'Preserved'})
    store.reconcile_series('library-1', set())
    remote.get_series_in_library.side_effect = RuntimeError('Private error')
    response = client.post('/libraries/library-1/remove-missing', data={'series_id': 'series-1'})
    assert 'message=libraries.check_error' in response.headers['location']
    row = store.get('series', 'series-1')
    assert row['missing'] == 1 and json.loads(row['pending'])['summary'] == 'Preserved'
    client.cookies.clear()
    assert client.post('/libraries/library-1/check').headers['location'] == '/login'
    assert client.post('/libraries/library-1/remove-missing').headers['location'] == '/login'
