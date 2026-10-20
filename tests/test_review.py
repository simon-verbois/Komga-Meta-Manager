"""Review workflow: unpublished changes, discards, publication and the helpers behind the reworked UI."""

import json
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from modules.config import AppConfig, LibraryConfig, ProcessingConfig, SystemConfig, config_for_library
from modules.job_queue import JobQueue
from modules.local_metadata import LocalCatalogue
from modules.models import KomgaLibrary
from modules.webui import auth, config_store, db
from modules.webui.app import create_app
from modules.webui.forms import ordered_sources, processing_patch, rule_choices, sources_patch
from modules.webui.humanize import audit_text, nav_pending, plural
from modules.workflow import automation_snapshot, job_snapshot, push_metadata

SERVER = "http://komga:25600"


@pytest.fixture
def store(tmp_path):
    db.init_db(tmp_path / "review.db")
    config_store._config = None
    return LocalCatalogue(SERVER)


def imported(store, series, **metadata):
    """Import a Komga series, then record unpublished local changes on top of it."""
    store.import_item("series", series, series.library_id, series.id)
    if metadata:
        store.patch("series", series.id, metadata)
    return store.get("series", series.id)


def test_import_records_komga_values_and_pending_changes_show_before_after(store, series):
    row = imported(store, series)
    assert json.loads(row["remote"])["summary"] == ""
    assert store.pending_changes() == []
    store.patch("series", series.id, {"summary": "From AniList", "genres": ["Action"]})
    store.patch("series", series.id, {"publisher": "Kodansha", "publisherLock": True}, manual=True)
    groups = store.pending_changes()
    assert len(groups) == 1 and groups[0]["series_id"] == series.id and groups[0]["title"] == "Example Manga"
    changes = {c["field"]: c for c in groups[0]["items"][0]["changes"]}
    # Unchanged values (genres already Action) are not listed as changes.
    assert set(changes) == {"summary", "publisher"}
    assert changes["summary"] == {"field": "summary", "before": "", "before_known": True, "after": "From AniList",
                                  "lock": False, "manual": False}
    assert changes["publisher"]["manual"] is True and changes["publisher"]["lock"] is True
    assert store.pending_counts() == {"library-1": 1}
    assert store.series_counts() == {"library-1": 1}
    assert store.pending_changes("other-library") == []
    # A new fetch keeps pending edits while refreshing the Komga baseline.
    refreshed = series.model_copy(deep=True)
    refreshed.metadata.summary = "Changed in Komga"
    store.import_item("series", refreshed, series.library_id, series.id)
    changes = {c["field"]: c for c in store.pending_changes()[0]["items"][0]["changes"]}
    assert changes["summary"]["before"] == "Changed in Komga" and changes["summary"]["after"] == "From AniList"


def test_pending_changes_cover_lock_only_and_unknown_baseline(store, series):
    imported(store, series)
    store.save_cover("series", series.id, b"image", manual=True)
    store.patch("series", series.id, {"titleLock": True})
    changes = {c["field"]: c for c in store.pending_changes()[0]["items"][0]["changes"]}
    assert changes["cover"]["after"] == "upload" and changes["cover"]["manual"] is True
    assert changes["title"]["lock_only"] is True and changes["title"]["lock"] is True
    with db.get_db() as conn:
        conn.execute("UPDATE local_metadata SET remote=NULL")
    store.patch("series", series.id, {"summary": "New"})
    changes = {c["field"]: c for c in store.pending_changes()[0]["items"][0]["changes"]}
    assert changes["summary"]["before_known"] is False and changes["summary"]["before"] is None


def test_discard_one_field_restores_komga_value_and_manual_flag(store, series):
    imported(store, series)
    store.patch("series", series.id, {"summary": "Mine", "summaryLock": True, "publisher": "Pub"}, manual=True)
    assert store.discard(series.id, "series", series.id, "summary") == 2
    row = store.get("series", series.id)
    data, pending, manual = json.loads(row["data"]), json.loads(row["pending"]), json.loads(row["manual"])
    assert data["metadata"]["summary"] == "" and data["metadata"]["summaryLock"] is False
    assert pending == {"publisher": "Pub"}
    assert manual == ["publisher"]
    # Discarding a field that has no pending change changes nothing.
    assert store.discard(series.id, "series", series.id, "summary") == 0


def test_discard_whole_series_includes_books_and_cover(store, series):
    from tests.test_libraries import book

    imported(store, series, summary="New")
    store.import_item("books", book("book-1"), series.library_id, series.id)
    store.patch("books", "book-1", {"title": "Volume one"}, manual=True)
    store.save_cover("series", series.id, b"image", manual=True)
    other = series.model_copy(update={"id": "series-2"})
    imported(store, other, summary="Other")
    assert store.discard(series.id) == 3
    assert [g["series_id"] for g in store.pending_changes()] == ["series-2"]
    row = store.get("series", series.id)
    assert row["cover"] is None and row["cover_pending"] == 0 and json.loads(row["manual"]) == []
    assert json.loads(store.get("books", "book-1")["data"])["metadata"]["title"] == "book-1"


def test_discard_cover_only(store, series):
    imported(store, series, summary="New")
    store.save_cover("series", series.id, None, manual=True)
    assert store.pending_changes()[0]["items"][0]["changes"][-1]["after"] == "remove"
    assert store.discard(series.id, field="cover") == 1
    assert [c["field"] for c in store.pending_changes()[0]["items"][0]["changes"]] == ["summary"]


def test_push_updates_komga_baseline_and_clears_pending(store, series, app_config):
    imported(store, series, summary="Published summary")
    app_config.system.dry_run = False
    app_config.system.workflow = "push"
    client = Mock()
    client.get_libraries.return_value = [KomgaLibrary(id="library-1", name="Manga")]
    client.get_series_in_library.return_value = [series]
    client.get_books_in_series.return_value = []
    client.update_series_metadata.return_value = True
    with patch("modules.workflow.KomgaClient", return_value=client):
        result = push_metadata(app_config, store=store)
    assert result.success and result.processed == 1
    client.update_series_metadata.assert_called_once_with(series.id, {"summary": "Published summary"})
    row = store.get("series", series.id)
    assert json.loads(row["pending"]) == {}
    assert json.loads(row["remote"])["summary"] == "Published summary"
    assert store.pending_changes() == []


def test_push_simulation_keeps_pending_changes(store, series, app_config):
    imported(store, series, summary="Not yet")
    app_config.system.dry_run = True
    client = Mock()
    client.get_libraries.return_value = [KomgaLibrary(id="library-1", name="Manga")]
    client.get_series_in_library.return_value = [series]
    client.get_books_in_series.return_value = []
    with patch("modules.workflow.KomgaClient", return_value=client):
        push_metadata(app_config, store=store)
    client.update_series_metadata.assert_not_called()
    assert json.loads(store.get("series", series.id)["pending"]) == {"summary": "Not yet"}


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ({"workflow": "both", "dry_run": False}, True),
        ({"workflow": "push", "dry_run": False}, True),
        ({"workflow": "collect", "dry_run": False}, False),
        ({"workflow": "both", "dry_run": True}, False),
        ({}, False),
        ({"workflow": "both", "dry_run": False, "auto_publish": False}, False),
        ({"workflow": "collect", "dry_run": True, "auto_publish": True}, True),
    ],
)
def test_auto_publish_migrates_legacy_live_automation(system, expected):
    assert SystemConfig.model_validate(system).auto_publish is expected


def test_job_and_automation_snapshots_are_real_and_do_not_mutate(app_config):
    app_config.system.overwrite_local = True
    fetch = automation_snapshot(app_config)
    assert (fetch.system.workflow, fetch.system.dry_run, fetch.system.overwrite_local) == ("collect", False, False)
    app_config.system.auto_publish = True
    assert automation_snapshot(app_config).system.workflow == "both"
    assert job_snapshot(app_config, "publish").system.workflow == "push"
    assert job_snapshot(app_config, "fetch_publish").system.dry_run is False
    assert app_config.system.dry_run is True and app_config.system.overwrite_local is True
    with pytest.raises(KeyError):
        job_snapshot(app_config, "unknown")


def test_library_exclusions_merge_with_defaults_without_duplicates(app_config):
    app_config.processing.exclude_series = ["Global"]
    app_config.library_settings["library-1"] = LibraryConfig(name="Manga", exclude_series=["Local", "Global"])
    app_config.library_settings["library-2"] = LibraryConfig(
        name="Other", processing=ProcessingConfig(exclude_series=["Profile"]), exclude_series=["Local"],
    )
    assert config_for_library(app_config, "library-1").processing.exclude_series == ["Global", "Local"]
    assert config_for_library(app_config, "library-2").processing.exclude_series == ["Profile", "Local"]
    assert config_for_library(app_config, "library-3").processing.exclude_series == ["Global"]
    assert app_config.processing.exclude_series == ["Global"]
    assert app_config.library_settings["library-2"].processing.exclude_series == ["Profile"]


def test_rule_choices_and_processing_patch_round_trip():
    processing = ProcessingConfig.model_validate({
        "overwrite_existing": True,
        "exclude_series": ["Skipped"],
        "update_fields": {"summary": True, "publisher": False, "authors": {"writers": False}, "tags": {"score": True}},
        "remove_fields": {"genres": True, "language": True},
    }).model_dump()
    choices = rule_choices(processing)
    assert choices["summary"] == "fill" and choices["publisher"] == "keep" and choices["genres"] == "remove"
    assert choices["writers"] == "keep" and choices["pencillers"] == "fill" and choices["score"] == "fill"
    assert choices["language"] == "remove" and choices["reading_direction"] == "keep"
    form = FormData([(f"rule_{k}", v) for k, v in choices.items()] + [("existing_values", "replace"), ("locked_fields", "respect")])
    patch_ = ProcessingConfig.model_validate(processing_patch(form, processing)).model_dump()
    for key in ("overwrite_existing", "force_unlock", "update_fields", "remove_fields", "exclude_series"):
        assert patch_[key] == processing[key], key
    # Unknown or impossible choices fall back to leaving the field alone.
    patched = processing_patch(FormData([("rule_summary", "bogus"), ("rule_language", "fill")]), {})
    assert patched["update_fields"]["summary"] is False and patched["remove_fields"]["language"] is False
    assert patched["overwrite_existing"] is False and patched["exclude_series"] == []
    assert "language" not in patched["update_fields"]


def test_sources_patch_uses_form_order_as_priority():
    existing = [{"name": "anilist", "priority": 1, "min_score": 60}, {"name": "mangadex", "priority": 2},
                {"name": "mangaupdates", "priority": 3}]
    form = FormData([("source_order", "mangaupdates"), ("source_order", "anilist"), ("source_order", "unknown"),
                     ("mangaupdates_enabled", "1"), ("anilist_allow_adult", "1")])
    sources = sources_patch(form, existing)
    assert [(s["name"], s["priority"], s["enabled"]) for s in sources] == [
        ("mangaupdates", 1, True), ("anilist", 2, False), ("mangadex", 3, False),
    ]
    assert sources[1]["min_score"] == 60 and sources[1]["allow_adult"] is True
    assert [s["display"] for s in ordered_sources(sources)] == ["MangaUpdates", "AniList", "MangaDex"]
    assert [s["name"] for s in ordered_sources([])] == ["anilist", "mangadex", "mangaupdates"]


def test_audit_text_is_readable():
    assert audit_text({"action": "CONFIG_SAVE", "detail": "Automation saved by admin."}) == {
        "label": "Settings saved", "detail": "Automation saved by admin."}
    assert audit_text({"action": "SOMETHING_NEW", "detail": None}) == {"label": "Something new", "detail": "—"}
    manual = audit_text({"action": "MANUAL_EDIT_PARTIAL", "detail": json.dumps(
        {"user": "admin", "applied": ["summary"], "failed": ["cover"]})})
    assert manual["label"] == "Metadata partly edited"
    assert manual["detail"] == "admin saved summary. Failed: cover."
    # Stored results list the written items with their fields.
    detailed = audit_text({"action": "MANUAL_EDIT", "detail": json.dumps(
        {"user": "admin", "applied": [{"id": "s", "fields": ["title", "summary"]}, {"id": "b", "fields": ["title"]}]})})
    assert detailed["detail"] == "admin saved title, summary."
    assert audit_text({"action": "DRY_RUN_TOGGLE", "detail": "dry_run set to False by 'admin'"})["detail"] == (
        "simulation turned off by 'admin'")
    assert audit_text({"action": "MANUAL_EDIT", "detail": "not json"})["detail"] == "not json"
    assert plural(1, "job.series_one", "job.series_many") == "1 series"
    assert plural(3, "libraries.books_one", "libraries.books_many") == "3 books"


def test_nav_pending_counts_series_and_tolerates_missing_config(store, series, app_config):
    assert nav_pending() == 0
    config_store.save_config_to_db(app_config.model_dump(mode="json"))
    assert nav_pending() == 0
    imported(store, series, summary="New")
    imported(store, series.model_copy(update={"id": "series-2"}), summary="New")
    assert nav_pending() == 2
    with patch("modules.webui.humanize.get_config", side_effect=RuntimeError):
        assert nav_pending() == 0


@pytest.fixture
def review_client(store, app_config, monkeypatch):
    auth._serializer = None
    config_store._reload_callback = None
    db.create_user("admin", auth.hash_password("ReviewTests123!"))
    config_store.save_config_to_db(app_config.model_dump(mode="json"))
    queue = JobQueue()
    monkeypatch.setattr(queue, "start", lambda: None)
    libraries = [KomgaLibrary(id="library-1", name="Manga"), KomgaLibrary(id="library-2", name="Webtoons")]
    with patch("modules.webui.routes.review.known_libraries", return_value=libraries), \
            patch("modules.webui.routes.dashboard.known_libraries", return_value=libraries):
        with TestClient(create_app(queue), follow_redirects=False) as client:
            client.cookies.set(auth.SESSION_COOKIE, auth.create_session_token("admin"))
            yield client


def jobs():
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    return [{**dict(r), "config": json.loads(r["config"]), "series_ids": json.loads(r["series_ids"] or "null")} for r in rows]


def test_review_lists_changes_with_navigation_badge(review_client, store, series):
    imported(store, series, summary="Fetched <b>summary</b>", genres=["Action", "Drama"])
    store.patch("series", series.id, {"publisher": "Mine"}, manual=True)
    page = review_client.get("/review").text
    assert "3 changes · 1 series" in page
    assert "Example Manga" in page and "Manga" in page
    assert "Fetched &lt;b&gt;summary&lt;/b&gt;" in page
    assert "Your edit" in page and "From sources" in page
    assert "In Komga now" in page and "After publishing" in page
    assert '<span class="nav-count"' in page
    assert 'name="series_id" value="series-1" form="publish-form"' in page
    assert "Publish all to Komga" in page
    home = review_client.get("/").text
    assert "1 series has changes to review" in home
    assert 'href="/review?library=library-1"' in home


def test_review_separates_series_and_orders_books_by_number(review_client, store, series):
    from tests.test_libraries import book

    imported(store, series, summary="A long summary. " * 50 + "The final sentence.")
    for number in (20, 2, 8):
        item = book(f"book-{number}")
        item.metadata.title = f"Old title {number}"
        item.metadata.number = str(number)
        item.metadata.number_sort = number
        store.import_item("books", item, series.library_id, series.id)
        store.patch("books", item.id, {"title": f"Volume {number}"})
    response = review_client.get("/review")
    group = response.context["groups"][0]
    assert group["change_count"] == 4
    assert [item["id"] for item in group["books"]] == ["book-2", "book-8", "book-20"]
    assert group["books"][0]["current_title"] == "Old title 2"
    assert group["books"][0]["title"] == "Volume 2"
    assert "Series metadata" in response.text and "Book changes" in response.text
    assert 'class="review-book" data-book-id="book-2"' in response.text
    assert 'class="review-series-details" open' in response.text
    assert "Read full summary" in response.text and "The final sentence." in response.text


def test_review_warns_from_all_remote_books_without_correcting_or_blocking(review_client, store, series):
    from tests.test_libraries import book

    imported(store, series, summary="Pending summary")
    for identifier, number in (("first", "1"), ("second", "2")):
        item = book(identifier)
        item.metadata.title = "Dr Stone T01"
        item.metadata.number = number
        store.import_item("books", item, series.library_id, series.id)
    # Renaming one book locally must not conceal issues in the Komga baseline.
    store.patch("books", "second", {"title": "Tome 2"})
    before = [store.get("books", identifier) for identifier in ("first", "second")]
    response = review_client.get("/review")
    group = response.context["groups"][0]
    assert [w["code"] for w in group["warnings"]] == ["duplicate_title_number", "title_number_mismatch"]
    assert [b["id"] for b in group["warnings"][0]["books"]] == ["first", "second"]
    assert "Numbering warning" in response.text
    assert "Inspect numbering warnings before publishing" in response.text
    assert "KMM does not fix these issues" in response.text
    assert [store.get("books", identifier) for identifier in ("first", "second")] == before
    result = review_client.post("/review/publish", data={"series_id": series.id})
    assert "queued=" in result.headers["location"]
    assert jobs()[-1]["series_ids"] == [series.id]
    assert [store.get("books", identifier) for identifier in ("first", "second")] == before


def test_review_warnings_are_scoped_and_ignore_unknown_remote_metadata(review_client, store, series):
    from tests.test_libraries import book

    imported(store, series, summary="Pending")
    item = book("one")
    item.metadata.title = "Volume 1"
    store.import_item("books", item, series.library_id, series.id)
    other = series.model_copy(update={"id": "series-2", "library_id": "library-2"})
    imported(store, other, summary="Other")
    store.import_item("books", book("foreign", other.id), other.library_id, other.id)
    # Same number in another series/server must not create a duplicate.
    LocalCatalogue("http://another-komga").import_item("books", book("foreign-server"), series.library_id, series.id)
    unknown = book("unknown")
    unknown.metadata.title = "Volume 9"
    store.import_item("books", unknown, series.library_id, series.id)
    with db.get_db() as conn:
        conn.execute("UPDATE local_metadata SET remote=NULL WHERE id='unknown'")
    response = review_client.get("/review?library=library-1")
    assert len(response.context["groups"]) == 1
    assert response.context["groups"][0]["warnings"] == []
    assert 'class="review-warnings"' not in response.text
    store.patch("books", "one", {"title": "Volume 8"})
    assert store.pending_changes()[0]["warnings"] == []


def test_review_discard_routes(review_client, store, series):
    imported(store, series, summary="Fetched", publisher="Pub")
    response = review_client.post("/review/discard", data={
        "series_id": series.id, "entity": "series", "item_id": series.id, "field": "summary", "library": "library-1",
    })
    assert response.status_code == 303
    assert response.headers["location"] == "/review?library=library-1&discarded=1"
    assert [c["field"] for c in store.pending_changes()[0]["items"][0]["changes"]] == ["publisher"]
    response = review_client.post("/review/discard", data={"series_id": series.id, "title": "Example Manga"})
    assert response.headers["location"].startswith("/review?discarded=")
    assert store.pending_changes() == []
    assert "1 change discarded" in review_client.get("/review?discarded=1").text
    assert any(e["action"] == "CHANGES_DISCARDED" for e in db.get_audit_log())
    response = review_client.post("/review/discard", data={"series_id": "unknown"})
    assert response.headers["location"] == "/review?discarded=0"


def test_review_publish_all_selected_or_by_library(review_client, store, series):
    imported(store, series, summary="One")
    other = series.model_copy(update={"id": "series-2", "library_id": "library-2"})
    imported(store, other, summary="Two")
    before = config_store.get_config_dict()
    response = review_client.post("/review/publish")
    assert response.status_code == 303
    job = jobs()[-1]
    assert response.headers["location"] == f"/review?queued={job['id']}"
    system = job["config"]["system"]
    assert (system["workflow"], system["dry_run"], system["overwrite_local"]) == ("push", False, False)
    assert job["config"]["komga"]["libraries"] == ["Manga", "Webtoons"]
    assert job["series_ids"] is None
    review_client.post("/review/publish", data={"series_id": ["series-2"]})
    job = jobs()[-1]
    assert job["config"]["komga"]["libraries"] == ["Webtoons"] and job["series_ids"] == ["series-2"]
    response = review_client.post("/review/publish", data={"library": "library-1"})
    job = jobs()[-1]
    assert response.headers["location"] == f"/review?library=library-1&queued={job['id']}"
    assert job["config"]["komga"]["libraries"] == ["Manga"] and job["series_ids"] == ["series-1"]
    # Selecting unknown series publishes nothing.
    assert "message=review.nothing" in review_client.post("/review/publish", data={"series_id": ["nope"]}).headers["location"]
    assert len(jobs()) == 3
    assert config_store.get_config_dict() == before
    assert "Publish #3 started" in review_client.get("/review?queued=3").text


def test_review_publish_reports_connection_error(review_client, store, series):
    imported(store, series, summary="One")
    with patch("modules.webui.routes.review.known_libraries", side_effect=RuntimeError("secret host")):
        response = review_client.post("/review/publish")
    assert "message=libraries.connection_error" in response.headers["location"]
    assert jobs() == []


def test_review_requires_login_and_same_origin(review_client, store, series):
    imported(store, series, summary="One")
    for path in ("/review/publish", "/review/discard"):
        assert review_client.post(path, data={"series_id": series.id}, headers={"Origin": "https://evil.example"}).status_code == 403
    review_client.cookies.clear()
    assert review_client.get("/review").headers["location"] == "/login"
    for path in ("/review/publish", "/review/discard"):
        assert review_client.post(path, data={"series_id": series.id}).headers["location"] == "/login"
    assert len(store.pending_changes()) == 1 and jobs() == []


def test_app_config_round_trip_keeps_auto_publish(app_config):
    app_config.system.auto_publish = True
    assert AppConfig.model_validate(app_config.model_dump(mode="json")).system.auto_publish is True


def numbering_form(client, series_id, numbers):
    page = client.get(f"/review/numbering/{series_id}")
    return {"version": page.context["version"], "book_id": list(numbers), "number": list(numbers.values())}


def test_manual_volume_zero_is_local_scoped_persistent_and_reviewable(review_client, store, series, app_config):
    from tests.test_libraries import book

    app_config.processing.book_titles.mode = "custom"
    app_config.processing.book_titles.template = "Tome {number}"
    config_store.save_config_to_db(app_config.model_dump(mode="json"))
    imported(store, series, summary="Pending")
    items = [book("zero"), book("one")]
    items[1].metadata.number = "2"
    for item in items:
        store.import_item("books", item, series.library_id, series.id)
        store.patch("books", item.id, {"title": f"Tome {item.metadata.number}"})
    foreign = book("foreign", "series-2")
    store.import_item("books", foreign, "library-2", "series-2")
    before_foreign = store.get("books", foreign.id)
    path = f"/review/numbering/{series.id}"
    page = review_client.get(path)
    assert 'value="0"' in page.text and 'Fill consecutive numbers' in page.text
    assert len(page.context["rows"]) == 2
    response = review_client.post(path, data=numbering_form(review_client, series.id, {"zero": "0", "one": "1"}))
    assert "numbering_saved=1" in response.headers["location"]
    row = store.get("books", "zero")
    pending = json.loads(row["pending"])
    assert pending["title"] == "Tome 0" and pending["number"] == "0" and pending["numberSort"] == 0
    assert {"title", "number", "numberSort"} <= set(json.loads(row["manual"]))
    assert json.loads(row["remote"])["number"] == "1"
    assert store.get("books", foreign.id) == before_foreign
    assert jobs() == []
    review = review_client.get("/review").text
    assert 'Book number' in review and 'Sort number' in review and 'Tome 0' in review
    # Refetching and provider writes cannot replace manually saved numbers/titles.
    refreshed = store.import_item("books", items[0], series.library_id, series.id)
    assert str(refreshed.metadata.number) == "0" and refreshed.metadata.title == "Tome 0"
    store.patch("books", "zero", {"number": "99", "title": "Source title", "numberSort": 99})
    assert json.loads(store.get("books", "zero")["data"])["metadata"]["number"] == "0"
    # Discard restores the last Komga baseline and removes protection for these fields.
    for field in ("number", "numberSort", "title"):
        store.discard(series.id, "books", "zero", field)
    restored = store.get("books", "zero")
    assert json.loads(restored["data"])["metadata"]["number"] == "1"
    assert json.loads(restored["manual"]) == []


def test_numbering_validation_conflicts_and_foreign_books_preserve_entries(review_client, store, series):
    from tests.test_libraries import book

    imported(store, series, summary="Pending")
    store.import_item("books", book("a"), series.library_id, series.id)
    path = f"/review/numbering/{series.id}"
    original = store.get("books", "a")
    data = numbering_form(review_client, series.id, {"a": "-1"})
    response = review_client.post(path, data=data)
    assert response.status_code == 422 and 'value="-1"' in response.text
    assert store.get("books", "a") == original
    data = numbering_form(review_client, series.id, {"a": "0"})
    store.patch("books", "a", {"summary": "Concurrent edit"})
    response = review_client.post(path, data=data)
    assert response.status_code == 409 and 'value="0"' in response.text
    assert json.loads(store.get("books", "a")["pending"]) == {"summary": "Concurrent edit"}
    data = numbering_form(review_client, series.id, {"foreign": "0"})
    assert review_client.post(path, data=data).status_code == 409
    data = numbering_form(review_client, series.id, {"a": "0"})
    data["book_id"], data["number"] = ["a", "a"], ["0", "1"]
    assert review_client.post(path, data=data).status_code == 409
    assert review_client.get(path + "?library=library-2").status_code == 404
    assert review_client.get("/review/numbering/unknown").status_code == 404


def test_numbering_batch_rolls_back_if_any_target_is_missing(store, series):
    from tests.test_libraries import book

    store.import_item("books", book("a"), series.library_id, series.id)
    before = store.get("books", "a")
    with pytest.raises(ValueError):
        store.patch_many([
            {"entity": "books", "id": "a", "payload": {"number": "0"}},
            {"entity": "books", "id": "missing", "payload": {"number": "1"}},
        ], manual=True)
    assert store.get("books", "a") == before


def test_numbering_requires_auth_and_configuration(review_client, store, series):
    from tests.test_libraries import book

    imported(store, series)
    store.import_item("books", book("a"), series.library_id, series.id)
    path = f"/review/numbering/{series.id}"
    with patch("modules.webui.routes.review.get_config", return_value=None):
        assert review_client.get(path).headers["location"].startswith("/settings")
    review_client.cookies.clear()
    assert review_client.get(path).headers["location"] == "/login"
    assert review_client.post(path).headers["location"] == "/login"


def test_reordered_number_overrides_swap_books_without_touching_other_fields(review_client, store, series, app_config):
    from tests.test_libraries import book

    app_config.processing.book_titles.mode = "custom"
    app_config.processing.book_titles.template = "Tome {number}"
    config_store.save_config_to_db(app_config.model_dump(mode="json"))
    imported(store, series, summary="Pending")
    for identifier, number, title in (("shinjuku", "24", "La Bataille Du No Man's Land De Shinjuku"),
                                      ("volume-24", "25", "Jujutsu Kaisen T24"),
                                      ("volume-26", "26", "Jujutsu Kaisen T26")):
        item = book(identifier)
        item.metadata.number = number
        item.metadata.number_sort = int(number)
        item.metadata.title = title
        store.import_item("books", item, series.library_id, series.id)
        store.patch("books", item.id, {"title": f"Tome {number}", "summary": "Keep this summary"})
    path = f"/review/numbering/{series.id}"
    original_third = store.get("books", "volume-26")
    data = numbering_form(review_client, series.id, {"volume-24": "24", "shinjuku": "25", "volume-26": "26"})
    assert review_client.post(path, data=data).status_code == 303
    for identifier, expected in (("volume-24", "24"), ("shinjuku", "25")):
        row = store.get("books", identifier)
        metadata = json.loads(row["data"])["metadata"]
        assert metadata["number"] == expected and metadata["numberSort"] == int(expected)
        assert metadata["title"] == f"Tome {expected}"
        assert metadata["summary"] == "Keep this summary"
        assert {"number", "numberSort", "title"} <= set(json.loads(row["manual"]))
    assert store.get("books", "volume-26") == original_third
    page = review_client.get(path)
    assert [row["id"] for row in page.context["rows"]] == ["volume-24", "shinjuku", "volume-26"]
    assert 'data-numbering-move="-1"' in page.text and 'Move down' in page.text
    assert jobs() == []


@pytest.mark.parametrize("conflict", [False, True])
def test_numbering_keeps_reordered_rows_and_values_on_error(review_client, store, series, conflict):
    from tests.test_libraries import book

    imported(store, series)
    for identifier in ("a", "b"):
        store.import_item("books", book(identifier), series.library_id, series.id)
    data = numbering_form(review_client, series.id, {"b": "0", "a": "invalid"})
    if conflict:
        store.patch("books", "a", {"summary": "Changed since opening"})
    before = [store.get("books", identifier) for identifier in ("a", "b")]
    response = review_client.post(f"/review/numbering/{series.id}", data=data)
    assert response.status_code == (409 if conflict else 422)
    assert [row["id"] for row in response.context["rows"]] == ["b", "a"]
    assert [row["number"] for row in response.context["rows"]] == ["0", "invalid"]
    assert [store.get("books", identifier) for identifier in ("a", "b")] == before


def test_review_drag_saves_local_manual_order_and_returns_updated_review(review_client, store, series, app_config):
    from tests.test_libraries import book

    app_config.processing.book_titles.mode = "custom"
    app_config.processing.book_titles.template = "Tome {number}"
    config_store.save_config_to_db(app_config.model_dump(mode="json"))
    imported(store, series, summary="Keep")
    for identifier, number in (("shinjuku", "24"), ("volume-24", "25"), ("unchanged", "26")):
        item = book(identifier)
        item.metadata.number, item.metadata.number_sort = number, int(number)
        store.import_item("books", item, series.library_id, series.id)
        if identifier != "unchanged":
            store.patch("books", item.id, {"title": f"Tome {number}", "authors": [{"name": "Author", "role": "writer"}]})
    before = store.get("books", "unchanged")
    page = review_client.get("/review?library=library-1")
    assert 'data-order-handle' in page.text and 'review-book-edit' not in page.text
    group = page.context["groups"][0]
    response = review_client.post(f"/review/reorder/{series.id}?library=library-1", json={
        "version": group["order_version"], "order": ["volume-24", "shinjuku"],
    })
    assert response.status_code == 200 and 'data-review-order' in response.text
    assert [item["id"] for item in response.context["groups"][0]["books"]] == ["volume-24", "shinjuku"]
    for identifier, number in (("volume-24", "24"), ("shinjuku", "25")):
        row = store.get("books", identifier)
        pending = json.loads(row["pending"])
        assert pending["number"] == number and pending["numberSort"] == int(number)
        assert pending["title"] == f"Tome {number}"
        assert pending["authors"] == [{"name": "Author", "role": "writer"}]
        assert {"title", "number", "numberSort"} <= set(json.loads(row["manual"]))
    assert store.get("books", "unchanged") == before
    assert jobs() == []


@pytest.mark.parametrize("failure", ["stale", "foreign", "duplicate", "missing", "wrong_library", "invalid"])
def test_review_drag_rejects_conflicts_without_writing(review_client, store, series, failure):
    from tests.test_libraries import book

    imported(store, series, summary="Keep")
    for identifier in ("a", "b"):
        item = book(identifier)
        item.metadata.number = "1" if identifier == "a" else "2"
        store.import_item("books", item, series.library_id, series.id)
        store.patch("books", identifier, {"summary": "Pending"})
    group = review_client.get("/review").context["groups"][0]
    payload = {"version": group["order_version"], "order": ["b", "a"]}
    path = f"/review/reorder/{series.id}"
    if failure == "stale":
        store.patch("books", "a", {"summary": "Concurrent"})
    elif failure == "foreign":
        payload["order"] = ["foreign", "a"]
    elif failure == "duplicate":
        payload["order"] = ["a", "a", "b"]
    elif failure == "missing":
        payload["order"] = ["a"]
    elif failure == "wrong_library":
        path += "?library=library-2"
    elif failure == "invalid":
        payload = {"order": "bad"}
    before = [store.get("books", identifier) for identifier in ("a", "b")]
    response = review_client.post(path, json=payload)
    assert response.status_code in (404, 409, 422)
    assert "error" in response.json()
    assert [store.get("books", identifier) for identifier in ("a", "b")] == before


def test_review_drag_requires_auth_and_configuration(review_client):
    with patch("modules.webui.routes.review.get_config", return_value=None):
        assert review_client.post("/review/reorder/series-1", json={}).status_code == 409
    review_client.cookies.clear()
    assert review_client.post("/review/reorder/series-1", json={}).status_code == 401
