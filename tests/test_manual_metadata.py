"""Manual edits must be explicit, scoped, previewable and safe to retry."""

import io
import json
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from modules.komga_client import CoverImageError, KomgaClient
from modules.manual_metadata import EditTarget, ManualEditError, apply_edits, editor_values, plan_edits
from modules.webui import auth, config_store, db
from modules.webui.app import create_app
from modules.job_queue import JobQueue
from tests.test_libraries import book
from modules.models import KomgaLibrary


def image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 48), "green").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def target(series):
    books = [book("one"), book("two")]
    for item in books:
        item.metadata.authors = [{"name": "Writer", "role": "writer"}, {"name": "Colorist", "role": "colorist"}]
    return EditTarget(series, books)


def test_manual_preview_minimal_patch_and_existing_locks(target):
    target.series.metadata.summary_lock = True
    baseline = editor_values(target)
    patches, diff = plan_edits(
        target, {"summary": "Custom summary", "title": target.series.metadata.title}, baseline, True
    )
    assert patches == [
        {"entity": "series", "id": target.series.id, "payload": {"summary": "Custom summary", "summaryLock": True}}
    ]
    assert [item["field"] for item in diff] == ["summary"]
    assert target.series.metadata.summary != "Custom summary"


def test_author_replacement_preserves_unselected_roles(target):
    baseline = editor_values(target)
    patches, _ = plan_edits(target, {"writers": ["Custom writer"]}, baseline, True)
    assert len(patches) == 2
    assert all(patch["entity"] == "books" for patch in patches)
    assert all(
        patch["payload"]["authors"]
        == [{"name": "Colorist", "role": "colorist"}, {"name": "Custom writer", "role": "writer"}]
        for patch in patches
    )
    assert all(patch["payload"]["authorsLock"] is True for patch in patches)


def test_mixed_authors_are_not_replaced_without_explicit_role(target):
    target.books[1].metadata.authors = [{"name": "Different", "role": "writer"}]
    baseline = editor_values(target)
    assert baseline["values"]["writers"] is None
    assert baseline["mixed"]["writers"] is True
    patches, _ = plan_edits(target, {"summary": "Summary"}, baseline, True)
    assert len(patches) == 1 and patches[0]["entity"] == "series"


def test_ebook_does_not_write_shared_series_or_other_books(target):
    selected = target.books[1]
    target = EditTarget(target.series, [selected], selected)
    baseline = editor_values(target)
    assert "publisher" not in baseline["values"]
    patches, _ = plan_edits(target, {"title": "Custom ebook", "writers": ["New writer"]}, baseline, False)
    assert all(patch["entity"] == "books" and patch["id"] == selected.id for patch in patches)
    assert patches[0]["payload"]["titleLock"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": "field"},
        {"status": "INVALID"},
        {"title": ""},
        {"links": [{"label": "Bad", "url": "javascript:alert(1)"}]},
        {"genres": "not a list"},
    ],
)
def test_invalid_changes_are_rejected_before_any_write(target, changes):
    with pytest.raises(ManualEditError):
        plan_edits(target, changes, editor_values(target), True)


def test_concurrent_metadata_and_author_changes_are_detected(target):
    baseline = editor_values(target)
    target.series.metadata.summary = "Changed outside KMM"
    with pytest.raises(ManualEditError, match="manual.conflict"):
        plan_edits(target, {"summary": "My draft"}, baseline, True)
    target.books[0].metadata.authors = [{"name": "Other", "role": "writer"}]
    with pytest.raises(ManualEditError, match="manual.conflict"):
        plan_edits(target, {"writers": ["New writer"]}, baseline, True)


def test_partial_writes_report_exact_successes_and_failures(target):
    client = Mock()
    client.update_book_metadata.side_effect = [True, RuntimeError("rejected")]
    patches, _ = plan_edits(target, {"writers": ["New writer"]}, editor_values(target), True)
    result = apply_edits(client, target, patches, None)
    assert [write["id"] for write in result["applied"]] == ["one"]
    assert [write["id"] for write in result["failed"]] == ["two"]


@pytest.fixture
def manual_client(tmp_path, app_config, series, monkeypatch):
    db.init_db(tmp_path / "manual.db")
    auth._serializer = None
    config_store._config = None
    config_store._reload_callback = None
    db.create_user("admin", auth.hash_password("ManualTests123!"))
    config_store.save_config_to_db(app_config.model_dump(mode="json"))
    queue = JobQueue()
    monkeypatch.setattr(queue, "start", lambda: None)
    fake = Mock()
    fake.base_url = "http://komga:25600"
    fake.get_libraries.return_value = [KomgaLibrary(id="library-1", name="Manga")]
    fake.get_series_in_library.return_value = [series]
    fake.get_books_in_series.return_value = [book("one"), book("two")]
    with patch("modules.webui.routes.manual_metadata.KomgaClient", return_value=fake) as constructor:
        constructor.validate_cover_upload.side_effect = KomgaClient.validate_cover_upload
        with TestClient(create_app(queue), follow_redirects=False) as client:
            client.cookies.set(auth.SESSION_COOKIE, auth.create_session_token("admin"))
            yield client, fake
    config_store._config = None


def send(client, payload, cover=None):
    data = {"edit": json.dumps(payload)}
    return client.post(
        "/libraries/library-1/manual",
        data=data,
        files={"cover": ("cover.png", cover, "image/png")} if cover is not None else None,
    )


def test_http_load_preview_apply_and_audit(manual_client):
    client, fake = manual_client
    baseline = client.get("/libraries/library-1/manual?series_id=series-1").json()
    assert baseline["values"]["title"] == "Example Manga"
    payload = {"series_id": "series-1", "baseline": baseline, "changes": {"summary": "Custom summary"}}
    preview = send(client, payload)
    assert preview.status_code == 200 and preview.json()["mode"] == "preview"
    fake.update_series_metadata.assert_not_called()
    assert preview.json()["differences"][0]["after"] == "Custom summary"
    result = send(client, {**payload, "mode": "apply"})
    assert result.status_code == 200 and not result.json()["failed"]
    fake.update_series_metadata.assert_not_called()
    from modules.local_metadata import LocalCatalogue
    row = LocalCatalogue(fake.base_url).get("series", "series-1")
    assert json.loads(row["pending"]) == {"summary": "Custom summary", "summaryLock": True}
    assert any(entry["action"] == "MANUAL_EDIT" for entry in db.get_audit_log())
    assert client.app.state.job_queue.snapshot()["jobs"] == []


def test_http_cover_preview_then_upload_and_invalid_files(manual_client):
    client, fake = manual_client
    baseline = client.get("/libraries/library-1/manual?series_id=series-1").json()
    payload = {"series_id": "series-1", "baseline": baseline, "changes": {}}
    response = send(client, payload, image_bytes())
    assert response.status_code == 200 and response.json()["cover"] is True
    fake.upload_custom_cover.assert_not_called()
    response = send(client, {**payload, "mode": "apply"}, image_bytes())
    assert response.json()["cover_applied"] is True
    fake.upload_custom_cover.assert_not_called()
    from modules.local_metadata import LocalCatalogue
    import base64
    assert base64.b64decode(LocalCatalogue(fake.base_url).get("series", "series-1")["cover"]) == image_bytes()
    fake.reset_mock()
    assert (
        send(client, {**payload, "mode": "apply", "changes": {"summary": "Invalid cover"}}, b"not an image").status_code
        == 422
    )
    fake.update_series_metadata.assert_not_called()
    fake.upload_custom_cover.assert_not_called()


def test_http_wrong_library_or_book_and_unauthenticated_requests_never_write(manual_client):
    client, fake = manual_client
    assert client.get("/libraries/wrong/manual?series_id=series-1").status_code == 404
    assert client.get("/libraries/library-1/manual?series_id=series-1&book_id=wrong").status_code == 404
    client.cookies.clear()
    assert client.get("/libraries/library-1/manual?series_id=series-1").status_code == 401
    assert send(client, {}).status_code == 401
    fake.update_series_metadata.assert_not_called()


@pytest.mark.parametrize("book_id", [None, "one"])
def test_http_manual_edits_work_with_processing_disabled_without_enabling_jobs(manual_client, book_id):
    client, fake = manual_client
    raw = config_store.get_config_dict()
    raw["komga"]["libraries"] = []
    config_store.save_config_to_db(raw)
    params = {"series_id": "series-1"}
    if book_id:
        params["book_id"] = book_id
    response = client.get("/libraries/library-1/manual", params=params)
    assert response.status_code == 200
    payload = {**params, "baseline": response.json(), "changes": {"summary": "Manual correction"}}
    preview = send(client, payload, image_bytes())
    assert preview.status_code == 200 and preview.json()["cover"] is True
    fake.update_series_metadata.assert_not_called()
    fake.update_book_metadata.assert_not_called()
    fake.upload_custom_cover.assert_not_called()
    result = send(client, {**payload, "mode": "apply"}, image_bytes())
    assert result.status_code == 200 and not result.json()["failed"]
    fake.update_series_metadata.assert_not_called()
    fake.update_book_metadata.assert_not_called()
    fake.upload_custom_cover.assert_not_called()
    from modules.local_metadata import LocalCatalogue
    row = LocalCatalogue(fake.base_url).get("books" if book_id else "series", book_id or "series-1")
    assert json.loads(row["pending"]) == {"summary": "Manual correction", "summaryLock": True}
    assert config_store.get_config_dict() == raw
    assert client.app.state.job_queue.snapshot()["jobs"] == []


def test_http_conflict_preserves_current_metadata(manual_client):
    client, fake = manual_client
    baseline = client.get("/libraries/library-1/manual?series_id=series-1").json()
    from modules.local_metadata import LocalCatalogue
    LocalCatalogue(fake.base_url).patch("series", "series-1", {"summary": "Another local edit"}, manual=True)
    result = send(
        client, {"series_id": "series-1", "baseline": baseline, "changes": {"summary": "Draft"}, "mode": "apply"}
    )
    assert result.status_code == 409
    fake.update_series_metadata.assert_not_called()


def test_uploaded_cover_is_validated_selected_and_existing_images_kept(app_config):
    client = KomgaClient(app_config.komga)
    client.session = Mock()
    client.upload_custom_cover("books", "one", image_bytes())
    request = client.session.post.call_args
    assert request.args[0].endswith("/api/v1/books/one/thumbnails")
    assert request.kwargs["params"] == {"selected": "true"}
    assert request.kwargs["files"]["file"][2] == "image/png"
    client.session.delete.assert_not_called()
    client.session.post.return_value.close.assert_called_once()
    with pytest.raises(CoverImageError):
        client.validate_cover_upload(b"<svg></svg>")
    with pytest.raises(CoverImageError):
        client.validate_cover_upload(b"0" * (20 * 1024 * 1024 + 1))


def test_manual_reading_direction_uses_komga_alias_without_rewriting_other_fields(target):
    patches, diff = plan_edits(target, {"reading_direction": "RIGHT_TO_LEFT"}, editor_values(target), True)
    assert patches[0]["payload"] == {"readingDirection": "RIGHT_TO_LEFT", "readingDirectionLock": True}
    assert diff[0]["field"] == "reading_direction"


@pytest.mark.parametrize("all_books", [False, True])
def test_cover_scope_is_opt_in_and_preview_never_saves(manual_client, all_books):
    import base64
    from modules.local_metadata import LocalCatalogue

    client, fake = manual_client
    baseline = client.get("/libraries/library-1/manual?series_id=series-1").json()
    payload = {"series_id": "series-1", "baseline": baseline, "cover_all_books": all_books}
    store = LocalCatalogue(fake.base_url)
    assert send(client, payload, image_bytes()).json()["cover_book_count"] == (2 if all_books else 0)
    assert all(store.get("books", identifier)["cover"] is None for identifier in ("one", "two"))
    result = send(client, {**payload, "mode": "apply"}, image_bytes()).json()
    assert result["cover_applied"] and not result["failed"]
    assert base64.b64decode(store.get("series", "series-1")["cover"]) == image_bytes()
    for identifier in ("one", "two"):
        row = store.get("books", identifier)
        assert bool(row["cover_pending"]) is all_books
        if all_books:
            assert base64.b64decode(row["cover"]) == image_bytes()
            assert "cover" in json.loads(row["manual"])
    fake.upload_custom_cover.assert_not_called()


@pytest.mark.parametrize("source", ["local", "remote", "missing"])
def test_copy_current_series_cover_without_upload(manual_client, source):
    import base64
    from modules.local_metadata import LocalCatalogue

    client, fake = manual_client
    baseline = client.get("/libraries/library-1/manual?series_id=series-1").json()
    store = LocalCatalogue(fake.base_url)
    if source == "local":
        store.save_cover("series", "series-1", image_bytes(), manual=True)
    else:
        fake.headers = {}
        fake.verify_ssl = True
        fake.session.get.return_value.iter_content.return_value = [image_bytes() if source == "remote" else b"bad"]
        fake.validate_cover_upload.side_effect = KomgaClient.validate_cover_upload
    payload = {"series_id": "series-1", "baseline": baseline, "cover_all_books": True, "mode": "apply"}
    response = send(client, payload)
    if source == "missing":
        assert response.status_code == 422
        assert response.json()["error"] == "manual.cover_unavailable"
        assert store.get("books", "one")["cover"] is None
    else:
        assert response.status_code == 200 and response.json()["cover_applied"]
        for identifier in ("one", "two"):
            assert base64.b64decode(store.get("books", identifier)["cover"]) == image_bytes()
        if source == "remote":
            assert store.get("series", "series-1")["cover_pending"] == 0
    fake.upload_custom_cover.assert_not_called()


@pytest.mark.parametrize("option,book_id", [("true", None), (1, None), (True, "one")])
def test_reject_invalid_bulk_cover_scope(manual_client, option, book_id):
    client, fake = manual_client
    response = send(client, {"series_id": "series-1", "book_id": book_id, "cover_all_books": option})
    assert response.status_code == 422
    fake.upload_custom_cover.assert_not_called()


def test_bulk_cover_reports_partial_failure_and_attempts_remaining_books(target):
    client = Mock()
    client.upload_custom_cover.side_effect = [None, RuntimeError("failed"), None]
    result = apply_edits(client, target, [], image_bytes(), cover_all_books=True)
    assert not result["cover_applied"]
    assert result["failed"] == [{"entity": "books", "id": "one", "cover": True}]
    assert [item["id"] for item in result["applied"]] == [target.series.id, "two"]


def test_bulk_cover_excludes_foreign_books_and_publishes_from_review(manual_client):
    from modules.workflow import push_metadata
    from modules.local_metadata import LocalCatalogue

    client, fake = manual_client
    fake.get_books_in_series.return_value.append(book("foreign", "another-series"))
    baseline = client.get("/libraries/library-1/manual?series_id=series-1").json()
    assert baseline["book_count"] == 2
    response = send(client, {
        "series_id": "series-1", "baseline": baseline, "cover_all_books": True, "mode": "apply",
    }, image_bytes())
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["applied"]] == ["series-1", "one", "two"]
    fake.upload_custom_cover.assert_not_called()
    config = config_store.get_config().model_copy(deep=True)
    config.system.dry_run = False
    config.komga.libraries = ["Manga"]
    with patch("modules.workflow.KomgaClient", return_value=fake):
        assert push_metadata(config, series_ids=["series-1"]).success
    assert [(call.args[0], call.args[1]) for call in fake.upload_custom_cover.call_args_list] == [
        ("series", "series-1"), ("books", "one"), ("books", "two"),
    ]
    assert all(call.args[2] == image_bytes() for call in fake.upload_custom_cover.call_args_list)
    assert LocalCatalogue(fake.base_url).get("books", "one")["cover_pending"] == 0


def test_bulk_cover_rejects_empty_series(manual_client):
    client, fake = manual_client
    fake.get_books_in_series.return_value = []
    baseline = client.get("/libraries/library-1/manual?series_id=series-1").json()
    response = send(client, {
        "series_id": "series-1", "baseline": baseline, "cover_all_books": True, "mode": "apply",
    }, image_bytes())
    assert response.status_code == 422
    assert response.json()["error"] == "manual.cover_no_books"
    fake.upload_custom_cover.assert_not_called()
