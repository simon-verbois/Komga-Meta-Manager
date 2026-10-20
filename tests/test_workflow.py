"""Verify phase boundaries, local override protection and publication retries."""

import json
from unittest.mock import Mock, patch

import pytest

from modules.local_metadata import LocalCatalogue, LocalKomgaClient
from modules.models import KomgaLibrary
from modules.processor import ProcessingResult
from modules.webui import db
from modules.workflow import push_metadata, run_workflow
from tests.test_libraries import book


@pytest.fixture
def catalogue(tmp_path, app_config, series):
    db.init_db(tmp_path / "catalogue.db")
    client = Mock(base_url="http://komga:25600")
    client.get_libraries.return_value = [KomgaLibrary(id=series.library_id, name="Manga")]
    client.get_series_in_library.return_value = [series]
    client.get_books_in_series.return_value = [book("one"), book("two")]
    local = LocalKomgaClient(client)
    local.get_libraries()
    local.get_series_in_library(series.library_id, "Manga")
    local.get_books_in_series(series.id, series.name)
    return local, client


def test_collect_writes_locally_and_imports_all_books(catalogue, series):
    local, remote = catalogue
    local.update_series_metadata(series.id, {"summary": "Source summary"})
    local.update_book_metadata("one", {"authors": [{"name": "Writer", "role": "writer"}]})
    assert json.loads(local.store.get("series", series.id)["pending"])["summary"] == "Source summary"
    assert len(local.store.items("books", series.library_id, series.id)) == 2
    remote.update_series_metadata.assert_not_called()
    remote.update_book_metadata.assert_not_called()


@pytest.mark.parametrize("preview", [True, False])
def test_title_option_fetch_review_publish_without_sources(catalogue, app_config, series, preview):
    from modules.config import BookTitleConfig, LibraryConfig, ProcessingConfig

    local, remote = catalogue
    app_config.system.workflow = "collect"
    app_config.system.dry_run = preview
    for source in app_config.providers:
        source.enabled = False
    app_config.library_settings[series.library_id] = LibraryConfig(
        name="Manga", processing=ProcessingConfig(book_titles=BookTitleConfig(mode="volume", padding=2))
    )
    before = local.store.get("books", "one")
    local.store.patch("books", "two", {"title": "My title"}, manual=True)
    with (
        patch("modules.workflow.KomgaClient", return_value=remote),
        patch("modules.processor.Path.mkdir"),
    ):
        result = run_workflow(app_config)
        assert result.success
        remote.update_book_metadata.assert_not_called()
        if preview:
            assert local.store.get("books", "one") == before
            return
        assert json.loads(local.store.get("books", "one")["pending"]) == {"title": "Volume 01"}
        assert json.loads(local.store.get("books", "two")["pending"]) == {"title": "My title"}
        groups = local.store.pending_changes(series.library_id)
        assert any(change["after"] == "Volume 01" for group in groups for item in group["items"] for change in item["changes"])
        app_config.system.workflow = "push"
        assert run_workflow(app_config).success
        remote.update_book_metadata.assert_any_call("one", {"title": "Volume 01"})
        remote.update_book_metadata.assert_any_call("two", {"title": "My title"})
        assert json.loads(local.store.get("books", "one")["pending"]) == {}
        remote.update_book_metadata.reset_mock()
        # A successful publish followed by a refresh must not keep adding to titles.
        for item in remote.get_books_in_series.return_value:
            item.metadata.title = "Volume 01" if item.id == "one" else "My title"
        app_config.system.workflow = "collect"
        assert run_workflow(app_config).success
        assert json.loads(local.store.get("books", "one")["pending"]) == {}
        remote.update_book_metadata.assert_not_called()


def test_manual_overrides_survive_import_provider_refresh_and_successful_push(catalogue, app_config, series):
    local, remote = catalogue
    app_config.system.dry_run = False
    local.store.patch("series", series.id, {"summary": "My correction", "summaryLock": False}, manual=True)
    with patch("modules.workflow.KomgaClient", return_value=remote):
        assert push_metadata(app_config).success
    assert json.loads(local.store.get("series", series.id)["pending"]) == {}
    imported = local.get_series_in_library(series.library_id, "Manga")[0]
    assert imported.metadata.summary == "My correction"
    local.update_series_metadata(
        series.id, {"summary": "New source summary", "summaryLock": True, "publisher": "Source"}
    )
    data = json.loads(local.store.get("series", series.id)["data"])["metadata"]
    assert data["summary"] == "My correction" and data["summaryLock"] is False
    assert data["publisher"] == "Source"
    local.replace = True
    imported = local.get_series_in_library(series.library_id, "Manga")[0]
    assert imported.metadata.summary == series.metadata.summary
    local.update_series_metadata(series.id, {"summary": "Replacement"})
    assert json.loads(local.store.get("series", series.id)["data"])["metadata"]["summary"] == "Replacement"


def test_simulation_preserves_local_state_and_never_pushes(catalogue, app_config, series):
    local, remote = catalogue
    local.store.patch("series", series.id, {"summary": "Draft"}, manual=True)
    before = local.store.get("series", series.id)
    with patch("modules.workflow.KomgaClient", return_value=remote):
        assert push_metadata(app_config).success
    assert local.store.get("series", series.id) == before
    remote.update_series_metadata.assert_not_called()
    preview = LocalKomgaClient(remote, replace=True, preview=True)
    assert preview.get_series_in_library(series.library_id, "Manga")[0].metadata.summary == ""
    assert local.store.get("series", series.id) == before


def test_push_failure_retains_pending_changes_and_retry_succeeds(catalogue, app_config, series):
    local, remote = catalogue
    app_config.system.dry_run = False
    local.update_series_metadata(series.id, {"summary": "Draft"})
    remote.update_series_metadata.return_value = False
    with patch("modules.workflow.KomgaClient", return_value=remote):
        result = push_metadata(app_config)
        assert not result.success and result.failed == 1
        assert json.loads(local.store.get("series", series.id)["pending"]) == {"summary": "Draft"}
        remote.update_series_metadata.return_value = True
        assert push_metadata(app_config).success
    assert json.loads(local.store.get("series", series.id)["pending"]) == {}


def test_push_respects_remote_locks_and_force_unlock(catalogue, app_config, series):
    local, remote = catalogue
    app_config.system.dry_run = False
    local.update_series_metadata(series.id, {"summary": "Draft", "summaryLock": False})
    series.metadata.summary_lock = True
    with patch("modules.workflow.KomgaClient", return_value=remote):
        assert not push_metadata(app_config).success
        remote.update_series_metadata.assert_not_called()
        app_config.processing.force_unlock = True
        assert push_metadata(app_config).success
    remote.update_series_metadata.assert_called_once_with(series.id, {"summary": "Draft", "summaryLock": False})


@pytest.mark.parametrize("external_change", [None, "number", "title", "number_lock"])
def test_manual_numbering_can_update_known_locks_but_preserves_external_changes(catalogue, app_config, series, external_change):
    from modules.book_numbering import plan_numbering
    from modules.config import BookTitleConfig

    local, remote = catalogue
    item = remote.get_books_in_series.return_value[0]
    item.metadata.number_lock = external_change != "number_lock"
    item.metadata.number_sort_lock = True
    item.metadata.title_lock = True
    local.store.import_item("books", item, series.library_id, series.id)
    patches = plan_numbering(series, [item], BookTitleConfig(mode="volume"), {item.id: "0"})
    local.store.patch_many(patches, manual=True)
    if external_change:
        setattr(item.metadata, external_change, True if external_change == "number_lock" else "99")
    app_config.system.dry_run = False
    with patch("modules.workflow.KomgaClient", return_value=remote):
        result = push_metadata(app_config, series_ids=[series.id], book_ids=[item.id])
    if external_change:
        assert not result.success
        remote.update_book_metadata.assert_not_called()
        assert json.loads(local.store.get("books", item.id)["pending"])["number"] == "0"
    else:
        assert result.success
        remote.update_book_metadata.assert_called_once_with(item.id, {"number": "0", "numberSort": 0.0, "title": "Volume 0"})
        assert json.loads(local.store.get("books", item.id)["pending"]) == {}


def test_push_limits_library_series_and_books(catalogue, app_config, series):
    local, remote = catalogue
    app_config.system.dry_run = False
    for identifier in ["one", "two"]:
        local.update_book_metadata(identifier, {"summary": "Draft"})
    with patch("modules.workflow.KomgaClient", return_value=remote):
        assert push_metadata(app_config, series_ids=["other"]).success
        remote.update_book_metadata.assert_not_called()
        assert push_metadata(app_config, series_ids=[series.id], book_ids=["one"]).success
    remote.update_book_metadata.assert_called_once_with("one", {"summary": "Draft"})
    assert json.loads(local.store.get("books", "two")["pending"]) == {"summary": "Draft"}


def test_store_is_isolated_by_server(catalogue, series):
    local, _ = catalogue
    assert LocalCatalogue("http://another-komga").get("series", series.id) is None
    assert local.store.get("series", series.id)


def test_workflow_skips_push_after_failed_collection(catalogue, app_config):
    app_config.system.dry_run = False
    with (
        patch("modules.workflow.process_libraries", return_value=ProcessingResult(success=False)),
        patch("modules.workflow.push_metadata") as push,
    ):
        assert not run_workflow(app_config).success
        push.assert_not_called()


def test_push_phase_never_calls_metadata_sources(catalogue, app_config):
    _, remote = catalogue
    app_config.system.workflow = "push"
    with (
        patch("modules.workflow.KomgaClient", return_value=remote),
        patch("modules.workflow.process_libraries") as collect,
    ):
        assert run_workflow(app_config).success
        collect.assert_not_called()


def test_editor_can_use_imported_catalogue_without_remote_reads(catalogue, series):
    _, remote = catalogue
    remote.get_libraries.side_effect = RuntimeError("offline")
    remote.get_series_in_library.side_effect = RuntimeError("offline")
    remote.get_books_in_series.side_effect = RuntimeError("offline")
    local = LocalKomgaClient(remote, manual=True, refresh=False)
    assert local.get_libraries()[0].name == "Manga"
    assert local.get_series_in_library(series.library_id, "Manga")[0].id == series.id
    assert len(local.get_books_in_series(series.id, series.name)) == 2


@pytest.mark.parametrize("phase", ["collect", "both"])
@pytest.mark.parametrize("preview", [False, True])
def test_complete_collection_and_publication_pipeline(catalogue, app_config, series, phase, preview):
    from tests.test_process_flow import full_match

    local, remote = catalogue
    app_config.system.workflow = phase
    app_config.system.dry_run = preview
    app_config.processing.update_fields.cover_image = False
    provider = Mock()
    provider.search.return_value = [full_match()]
    provider.get_metadata.side_effect = lambda candidate: candidate
    before = local.store.get("series", series.id)
    with (
        patch("modules.workflow.KomgaClient", return_value=remote),
        patch("modules.processor.get_providers", return_value=provider),
        patch("modules.processor.Path"),
    ):
        result = run_workflow(app_config)
    assert result.success
    if preview:
        assert local.store.get("series", series.id) == before
        remote.update_series_metadata.assert_not_called()
    else:
        row = local.store.get("series", series.id)
        assert json.loads(row["data"])["metadata"]["summary"] == "A summary"
        if phase == "collect":
            assert json.loads(row["pending"])["summary"] == "A summary"
            remote.update_series_metadata.assert_not_called()
        else:
            assert json.loads(row["pending"]) == {}
            assert remote.update_series_metadata.call_args.args[1]["summary"] == "A summary"


def test_targeted_replacement_preserves_other_series_and_books(catalogue, series):
    local, remote = catalogue
    other = series.model_copy(update={"id": "other-series"}, deep=True)
    remote.get_series_in_library.return_value = [series, other]
    local.get_series_in_library(series.library_id, "Manga")
    for identifier in [series.id, other.id]:
        local.store.patch("series", identifier, {"summary": "Manual series"}, manual=True)
    for identifier in ["one", "two"]:
        local.store.patch("books", identifier, {"summary": "Manual book"}, manual=True)
    targeted = LocalKomgaClient(remote, replace=True, series_ids=[series.id], book_ids=["one"])
    targeted.get_series_in_library(series.library_id, "Manga")
    targeted.get_books_in_series(series.id, series.name)
    assert json.loads(local.store.get("series", other.id)["data"])["metadata"]["summary"] == "Manual series"
    assert json.loads(local.store.get("books", "two")["data"])["metadata"]["summary"] == "Manual book"
    assert json.loads(local.store.get("books", "one")["manual"]) == []


def test_custom_cover_survives_push_and_is_not_uploaded_again(catalogue, app_config, series):
    from tests.test_manual_metadata import image_bytes

    local, remote = catalogue
    app_config.system.dry_run = False
    content = image_bytes()
    local.store.save_cover("series", series.id, content, manual=True)
    with patch("modules.workflow.KomgaClient", return_value=remote):
        assert push_metadata(app_config).success
        row = local.store.get("series", series.id)
        assert row["cover"] and not row["cover_pending"]
        assert push_metadata(app_config).success
    remote.upload_custom_cover.assert_called_once_with("series", series.id, content)
    local.update_series_poster(series.id, "https://unused.test/cover.jpg", overwrite_existing=True)
    remote._download_cover_image.assert_not_called()


def test_collection_replacement_preserves_excluded_series(catalogue, series):
    local, remote = catalogue
    local.store.patch("series", series.id, {"summary": "Manual"}, manual=True)
    refresh = LocalKomgaClient(remote, replace=True, exclude_series=[series.name])
    refresh.get_series_in_library(series.library_id, "Manga")
    assert json.loads(local.store.get("series", series.id)["data"])["metadata"]["summary"] == "Manual"


def test_push_missing_library_reports_failure_and_preserves_pending(catalogue, app_config, series):
    local, remote = catalogue
    local.update_series_metadata(series.id, {"summary": "Draft"})
    remote.get_libraries.return_value = []
    with patch("modules.workflow.KomgaClient", return_value=remote):
        assert not push_metadata(app_config).success
    assert json.loads(local.store.get("series", series.id)["pending"]) == {"summary": "Draft"}


def test_fetch_marks_absent_series_preserves_edits_and_clears_on_return(catalogue, series):
    local, remote = catalogue
    local.store.patch('series', series.id, {'summary': 'Keep my draft'}, manual=True)
    remote.get_series_in_library.return_value = []
    assert local.get_series_in_library(series.library_id, 'Manga') == []
    assert local.store.missing_series_ids(series.library_id) == {series.id}
    assert local.store.get('books', 'one')['missing'] == 1
    row = local.store.get('series', series.id)
    assert json.loads(row['pending']) == {'summary': 'Keep my draft'}
    remote.get_series_in_library.return_value = [series]
    local.get_series_in_library(series.library_id, 'Manga')
    assert local.store.missing_series_ids(series.library_id) == set()
    assert local.store.get('books', 'one')['missing'] == 0
    assert json.loads(local.store.get('series', series.id)['pending']) == {'summary': 'Keep my draft'}


def test_failed_fetch_and_preview_do_not_mark_absent(catalogue, series):
    local, remote = catalogue
    remote.get_series_in_library.side_effect = RuntimeError('Komga unavailable')
    with pytest.raises(RuntimeError):
        local.get_series_in_library(series.library_id, 'Manga')
    assert local.store.missing_series_ids(series.library_id) == set()
    remote.get_series_in_library.side_effect = None
    remote.get_series_in_library.return_value = []
    LocalKomgaClient(remote, preview=True).get_series_in_library(series.library_id, 'Manga')
    assert local.store.missing_series_ids(series.library_id) == set()


def test_remove_missing_is_scoped_and_removes_child_books(catalogue, series):
    local, _ = catalogue
    foreign_server = LocalCatalogue('http://other-komga')
    foreign_server.import_item('series', series, series.library_id, series.id)
    other = series.model_copy(update={'id': 'other', 'library_id': 'other-library'})
    local.store.import_item('series', other, other.library_id, other.id)
    assert not local.store.remove_missing_series(series.library_id, series.id)
    local.store.reconcile_series(series.library_id, set())
    assert not local.store.remove_missing_series('other-library', series.id)
    assert local.store.remove_missing_series(series.library_id, series.id)
    assert local.store.get('series', series.id) is None
    assert local.store.items('books', series.library_id) == []
    assert foreign_server.get('series', series.id) is not None
    assert local.store.get('series', other.id) is not None
