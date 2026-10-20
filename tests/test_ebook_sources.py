"""Coverage for reusable templates, edition identity and strictly book-scoped writes."""

import json
from unittest.mock import Mock, patch

import pytest
import requests
from pydantic import ValidationError
from starlette.datastructures import FormData

from modules.config import EbookMatch, LibraryConfig, ProviderConfig, SourceTemplate, config_for_library
from modules.ebook_metadata import candidate_score, find_book_metadata, match_status, process_ebook_series
from modules.local_metadata import LocalCatalogue, LocalKomgaClient
from modules.models import MetadataCreator, MetadataRecord
from modules.providers import ConfiguredProvider, ProviderChain
from modules.providers.base import MetadataProviderError
from modules.providers.ebooks import BnfProvider, BookQuery, GooglebooksProvider, OpenlibraryProvider, normalize_isbn
from modules.source_catalogue import builtin_templates
from modules.webui import config_store
from modules.webui.forms import sources_patch
from tests.test_libraries import book, library_client as _library_client


@pytest.fixture
def library_client(tmp_path, app_config, series, monkeypatch):
    yield from _library_client.__wrapped__(tmp_path, app_config, series, monkeypatch)


ISBN = "9782070612758"


def record(**values):
    return MetadataRecord(
        provider="openlibrary",
        external_id="OL123M",
        titles=["Le petit prince"],
        isbns=[ISBN],
        author_names=["Antoine de Saint-Exupéry"],
        language="fr",
        **values,
    )


def chain_with(*records):
    entries = []
    for index, item in enumerate(records, 1):
        provider = Mock()
        provider.search_book.return_value = item if isinstance(item, list) else [item]
        provider.get_metadata.side_effect = lambda candidate: candidate
        if not isinstance(item, list):
            provider.get_by_id.return_value = item
        entries.append(
            ConfiguredProvider(
                ProviderConfig(
                    name=(item[0] if isinstance(item, list) else item).provider, priority=index, preferred_language="fr"
                ),
                provider,
            )
        )
    return ProviderChain(entries)


def ebook_config(config):
    config.library_settings["library-1"] = LibraryConfig(name="Ebooks", content_type="ebook")
    result = config_for_library(config, "library-1")
    result.processing.update_fields.cover_image = False
    result.processing.update_fields.authors.pencillers = False
    return result


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(ISBN, ISBN), ("978-2-07-061275-8", ISBN), ("2070612759", ISBN), ("9782070612759", ""), ("garbage", "")],
)
def test_isbn_checksum_and_normalization(raw, expected):
    assert normalize_isbn(raw) == expected


def test_legacy_sources_are_preserved_and_ebooks_get_separate_defaults(app_config):
    previous = app_config.model_dump(mode="json")
    app_config.library_settings["library-1"] = LibraryConfig(name="Manga")
    app_config.library_settings["library-2"] = LibraryConfig(name="Ebooks", content_type="ebook")
    assert [source.name for source in config_for_library(app_config, "library-2").providers] == [
        "openlibrary",
        "googlebooks",
    ]
    assert [source.model_dump() for source in config_for_library(app_config, "library-1").providers] == previous[
        "providers"
    ]
    assert app_config.model_dump()["providers"] == previous["providers"]


def test_empty_source_set_is_explicit_and_survives_other_settings(library_client):
    client, _ = library_client
    response = client.post("/libraries/library-2/settings", data={"section": "sources"})
    assert response.status_code == 303
    assert config_store.get_config().library_settings["library-2"].providers == []
    client.post("/libraries/library-2/settings", data={"content_type": "ebook", "enabled": "1"})
    assert config_store.get_config().library_settings["library-2"].providers == []
    assert config_for_library(config_store.get_config(), "library-2").providers == []
    page = client.get("/libraries?library=library-2&tab=sources")
    assert "No sources selected" in page.text


def source_form(**extra):
    return {
        "section": "sources",
        "source_order": ["bnf", "openlibrary"],
        "bnf_enabled": "1",
        "openlibrary_enabled": "1",
        "bnf_preferred_language": "fr",
        "openlibrary_preferred_language": "fr",
        **extra,
    }


def test_personal_template_copies_options_and_deletion_does_not_change_library(library_client):
    client, _ = library_client
    response = client.post(
        "/libraries/library-2/settings", data=source_form(source_action="template_save", template_name="French novels")
    )
    assert response.status_code == 303
    cfg = config_store.get_config()
    key, template = next(iter(cfg.source_templates.items()))
    assert template.name == "French novels" and template.providers[0].name == "bnf"
    assert template.providers[0].preferred_language == "fr"
    assert template.content_type == "ebook"
    saved = cfg.library_settings["library-2"].providers
    assert saved == template.providers
    assert key in client.get("/libraries?library=library-2&tab=sources").text
    assert key not in client.get("/libraries?library=library-1&tab=sources").text
    response = client.post(
        "/libraries/library-2/settings", data=source_form(source_action="template_delete", source_template=key)
    )
    assert response.status_code == 200
    assert config_store.get_config().source_templates == {}
    assert config_store.get_config().library_settings["library-2"].providers == saved


def test_template_validation_keeps_submitted_sources_and_saved_config(library_client):
    client, _ = library_client
    response = client.post(
        "/libraries/library-2/settings", data=source_form(source_action="template_save", template_name="")
    )
    assert "The template could not be saved" in response.text
    assert 'data-source="bnf" data-source-selected="true"' in response.text
    assert config_store.get_config().source_templates == {}
    assert "library-2" not in config_store.get_config().library_settings


def test_type_defaults_only_affect_libraries_following_that_type(library_client):
    client, _ = library_client
    cfg = config_store.get_config().model_copy(deep=True)
    cfg.library_settings["other-ebook"] = LibraryConfig(name="Other", content_type="ebook")
    cfg.library_settings["custom-ebook"] = LibraryConfig(name="Custom", content_type="ebook", providers=[])
    config_store.save_config_to_db(cfg.model_dump())
    client.post("/libraries/library-2/settings", data=source_form(source_action="type_default"))
    cfg = config_store.get_config()
    assert [p.name for p in config_for_library(cfg, "other-ebook").providers] == ["bnf", "openlibrary"]
    assert config_for_library(cfg, "custom-ebook").providers == []
    assert [p.name for p in config_for_library(cfg, "library-1").providers] == ["anilist", "mangadex", "mangaupdates"]


def test_incompatible_sources_are_rejected_on_save_and_not_queried(app_config, library_client):
    client, _ = library_client
    response = client.post(
        "/libraries/library-2/settings", data={"section": "sources", "source_order": "anilist", "anilist_enabled": "1"}
    )
    assert "Some settings are invalid" in response.text
    app_config.library_settings["library-2"] = LibraryConfig(
        name="Ebooks", content_type="ebook", providers=[ProviderConfig(name="anilist")]
    )
    assert config_for_library(app_config, "library-2").providers == []
    assert app_config.library_settings["library-2"].providers[0].enabled
    with pytest.raises(ValidationError):
        SourceTemplate(name="Wrong", content_type="ebook", providers=[ProviderConfig(name="anilist")])
    with pytest.raises(ValueError):
        sources_patch(FormData([("source_order", "bnf"), ("source_order", "bnf")]), [])


def test_google_key_is_shared_preserved_and_never_copied_into_templates(library_client):
    client, _ = library_client
    client.post("/settings/services", data={"section": "metadata", "google_books_api_key": "test-only-secret"})
    assert config_store.get_config().google_books_api_key == "test-only-secret"
    assert "test-only-secret" not in client.get("/settings?tab=defaults").text
    client.post("/settings/defaults", data={})
    assert config_store.get_config().google_books_api_key == "test-only-secret"
    client.post(
        "/libraries/library-2/settings", data=source_form(source_action="template_save", template_name="Reusable")
    )
    assert "test-only-secret" not in json.dumps(
        {k: v.model_dump() for k, v in config_store.get_config().source_templates.items()}
    )
    client.post("/settings/services", data={"section": "metadata", "remove_google_books_key": "1"})
    assert config_store.get_config().google_books_api_key == ""


def test_builtin_templates_return_independent_copies():
    templates = builtin_templates()
    templates["manga"]["providers"][0]["enabled"] = False
    assert builtin_templates()["manga"]["providers"][0]["enabled"]
    assert builtin_templates()["ebooks-french"]["providers"][0]["name"] == "bnf"


def test_isbn_is_stronger_than_parent_language_and_wrong_isbn_is_rejected():
    query = BookQuery(title="Different title", isbn=ISBN, language="en")
    assert candidate_score(query, record()) == 100
    assert candidate_score(query, record().model_copy(update={"isbns": ["9780261102217"]})) is None


def test_title_only_ambiguous_editions_are_never_chosen(app_config):
    item = book("one")
    item.metadata.title = "Le petit prince"
    chain = chain_with([record(), record().model_copy(update={"external_id": "OL124M"})])
    match, state = find_book_metadata(item, chain, ebook_config(app_config))
    assert match is None and state == "ambiguous"
    chain.entries[0].provider.get_metadata.assert_not_called()


def test_same_title_wrong_author_is_not_a_match():
    assert candidate_score(BookQuery(title="Le petit prince", author="Someone Else"), record()) is None


def test_unlisted_isbn_falls_back_to_title_and_known_author(app_config):
    item = book("one")
    item.metadata.title = "Le petit prince"
    item.metadata.isbn = "9780261102217"
    item.metadata.authors = [{"name": "Antoine de Saint-Exupéry", "role": "writer"}]
    chain = chain_with(record(description="Matched by title"))
    provider = chain.entries[0].provider
    provider.search_book.side_effect = lambda query: [] if query.isbn else [record(description="Matched by title")]
    found, state = find_book_metadata(item, chain, ebook_config(app_config))
    assert found.description == "Matched by title" and state == "matched"
    queries = [call.args[0] for call in provider.search_book.call_args_list]
    assert [query.isbn for query in queries] == ["9780261102217", ""]
    assert queries[1].title == item.metadata.title and queries[1].author == "Antoine de Saint-Exupéry"


def test_isbn_service_failure_still_allows_title_search(app_config):
    item = book("one")
    item.metadata.title = "Le petit prince"
    item.metadata.isbn = ISBN
    chain = chain_with(record())
    chain.entries[0].provider.search_book.side_effect = [
        MetadataProviderError("ISBN lookup unavailable", status_code=503),
        [record()],
    ]
    found, state = find_book_metadata(item, chain, ebook_config(app_config))
    assert found is not None and state == "matched"
    assert chain.entries[0].provider.search_book.call_count == 2


def test_exact_isbn_in_later_source_wins_before_title_fallback(app_config):
    item = book("one")
    item.metadata.title = "Le petit prince"
    item.metadata.isbn = ISBN
    chain = chain_with(record(), record().model_copy(update={"provider": "bnf"}))
    chain.entries[0].provider.search_book.return_value = []
    found, state = find_book_metadata(item, chain, ebook_config(app_config))
    assert found.provider == "bnf" and state == "matched"
    assert all(entry.provider.search_book.call_count == 1 for entry in chain.entries)
    assert chain.entries[0].provider.search_book.call_args.args[0].isbn == ISBN


@pytest.mark.parametrize("reject", ["author", "language", "score", "ambiguity", "full_record"])
def test_title_fallback_keeps_matching_guards(app_config, reject):
    item = book("one")
    item.metadata.title = "Le petit prince"
    item.metadata.isbn = "9780261102217"
    item.metadata.authors = [{"name": "Antoine de Saint-Exupéry", "role": "writer"}]
    candidate = record()
    candidates = [candidate]
    if reject == "author":
        candidate.author_names = ["Unrelated writer"]
    elif reject == "language":
        candidate.language = "en"
    elif reject == "score":
        candidate.titles = ["Le grand voyage"]
    elif reject == "ambiguity":
        candidates.append(candidate.model_copy(update={"external_id": "OL124M"}))
    chain = chain_with(record())
    provider = chain.entries[0].provider
    provider.search_book.side_effect = lambda query: [] if query.isbn else candidates
    if reject == "full_record":
        provider.get_metadata.side_effect = lambda candidate: candidate.model_copy(update={"titles": ["Other book"]})
    found, state = find_book_metadata(item, chain, ebook_config(app_config), "fr")
    assert found is None
    assert state == ("ambiguous" if reject == "ambiguity" else "not_found")


def test_title_fuzzy_matching_uses_configured_score_without_known_author(app_config):
    item = book("one")
    item.metadata.title = "Le petit princes"
    item.metadata.isbn = ""
    item.metadata.authors = []
    chain = chain_with(record())
    chain.entries[0].config.min_score = 80
    assert find_book_metadata(item, chain, ebook_config(app_config))[1] == "matched"
    chain.entries[0].config.min_score = 100
    assert find_book_metadata(item, chain, ebook_config(app_config)) == (None, "not_found")


@pytest.mark.parametrize("pinned", [False, True])
def test_title_match_to_different_edition_preserves_known_isbn_and_date(series, app_config, pinned):
    series.metadata.language = "fr"
    cfg = ebook_config(app_config)
    cfg.system.dry_run = False
    cfg.processing.overwrite_existing = True
    cfg.processing.update_fields.isbn = True
    cfg.processing.update_fields.release_date = True
    item = book("one")
    item.metadata.title = "Le petit prince"
    item.metadata.isbn = "9780261102217"
    item.metadata.release_date = "1990-01-01"
    item.metadata.summary = ""
    edition = record(description="Useful summary", publication_date="2007-02-01")
    chain = chain_with(edition)
    if pinned:
        cfg.ebook_matches[item.id] = EbookMatch(provider="openlibrary", external_id=edition.external_id)
    client = Mock()
    client.get_books_in_series.return_value = [item]
    process_ebook_series(series, cfg, client, chain)
    payload = client.update_book_metadata.call_args.args[1]
    assert payload["summary"] == "Useful summary"
    if pinned:
        assert payload["isbn"] == ISBN and payload["releaseDate"] == "2007-02-01"
    else:
        assert "isbn" not in payload and "releaseDate" not in payload


def test_fallback_cannot_mix_editions(app_config):
    item = book("one")
    item.metadata.title = "Le petit prince"
    item.metadata.isbn = ISBN
    first = record(description=None)
    other = record(description="Wrong edition").model_copy(
        update={"provider": "googlebooks", "isbns": ["9780261102217"]}
    )
    chain = chain_with(first, other)
    found, _ = find_book_metadata(item, chain, ebook_config(app_config))
    assert found.description is None
    other.isbns = [ISBN]
    found, _ = find_book_metadata(item, chain, ebook_config(app_config))
    assert found.description == "Wrong edition"


def test_ebook_writes_only_target_book_and_respects_locks(series, app_config):
    cfg = ebook_config(app_config)
    cfg.system.dry_run = False
    cfg.processing.update_fields.isbn = True
    cfg.processing.update_fields.release_date = True
    first, second = book("one"), book("two")
    first.metadata.isbn = ISBN
    first.metadata.summary = "Keep me"
    first.metadata.summary_lock = True
    first.metadata.authors_lock = True
    first.metadata.release_date_lock = True
    source = record(
        description="New summary",
        publication_date="2007-02-01",
        creators=[MetadataCreator(name="Writer", role="writer")],
    )
    client = Mock()
    client.get_books_in_series.return_value = [first, second]
    process_ebook_series(series, cfg, client, chain_with(source), book_ids=["one"])
    client.update_series_metadata.assert_not_called()
    client.update_book_metadata.assert_not_called()
    cfg.processing.force_unlock = True
    cfg.processing.overwrite_existing = True
    process_ebook_series(series, cfg, client, chain_with(source), book_ids=["one"])
    assert all(call.args[0] == "one" for call in client.update_book_metadata.call_args_list)
    payloads = [call.args[1] for call in client.update_book_metadata.call_args_list]
    assert any(payload.get("summary") == "New summary" and payload.get("summaryLock") is False for payload in payloads)
    assert any(payload.get("releaseDate") == "2007-02-01" for payload in payloads)


def test_simulation_does_not_write_metadata_covers_or_match_status(series, app_config):
    cfg = ebook_config(app_config)
    cfg.processing.update_fields.cover_image = True
    item = book("one")
    item.metadata.isbn = ISBN
    client = Mock()
    client.get_books_in_series.return_value = [item]
    source = record(description="Summary", cover_urls=["https://images.test/cover.jpg"])
    with patch("modules.ebook_metadata.match_status") as status:
        changes = process_ebook_series(series, cfg, client, chain_with(source))
    assert changes
    client.update_book_metadata.assert_not_called()
    status.assert_not_called()
    assert client.update_book_poster.call_args.args[-1] is True


def test_manual_selection_is_reused_and_disabled_source_is_not_called(app_config):
    item = book("one")
    cfg = ebook_config(app_config)
    cfg.ebook_matches[item.id] = EbookMatch(provider="openlibrary", external_id="OL123M")
    chain = chain_with(record())
    found, state = find_book_metadata(item, chain, cfg)
    assert found.external_id == "OL123M" and state == "selected"
    chain.entries[0].provider.search_book.assert_not_called()
    assert find_book_metadata(item, ProviderChain([]), cfg) == (None, "source_disabled")


def test_openlibrary_search_retains_editions_and_cache_identity(tmp_path):
    provider = OpenlibraryProvider(tmp_path, 24)
    provider._get = Mock(
        return_value={
            "docs": [
                {
                    "title": "Example",
                    "author_name": ["Writer"],
                    "editions": {
                        "docs": [{"key": "/books/OL123M", "title": "Example", "language": ["fre"], "isbn": [ISBN]}]
                    },
                }
            ]
        }
    )
    candidates = provider.search_book(BookQuery(title="Example", author="Writer", language="fr"))
    assert candidates[0].external_id == "OL123M" and candidates[0].language == "fr"
    provider.search_book(BookQuery(title="Example", author="Writer", language="fr"))
    assert provider._get.call_count == 1
    provider.search_book(BookQuery(title="Example", author="Different writer", language="fr"))
    assert provider._get.call_count == 2


def test_openlibrary_full_record_has_edition_identity_and_work_summary(tmp_path):
    provider = OpenlibraryProvider(tmp_path, 24)
    provider._get = Mock(
        side_effect=[
            {
                "key": "/books/OL123M",
                "title": "Example",
                "isbn_13": [ISBN],
                "works": [{"key": "/works/OL1W"}],
                "publishers": ["Publisher"],
                "languages": [{"key": "/languages/fre"}],
                "covers": [4],
            },
            {"description": {"value": "Summary"}, "authors": [{"author": {"key": "/authors/OL1A"}}]},
            {"name": "Writer"},
        ]
    )
    found = provider.get_by_id("OL123M")
    assert found.description == "Summary" and found.creators[0].name == "Writer"
    assert found.publisher == "Publisher" and found.isbns == [ISBN]


def test_googlebooks_key_missing_and_network_errors_are_safe(tmp_path, caplog):
    provider = GooglebooksProvider(tmp_path, 24)
    with pytest.raises(MetadataProviderError, match="API key"):
        provider.search_book(BookQuery(title="Example"))
    provider.api_key = "never-log-this-key"
    provider.session.request = Mock(side_effect=requests.ConnectionError("connection failed"))
    with pytest.raises(MetadataProviderError) as error:
        provider.search_book(BookQuery(title="Example"))
    assert provider.api_key not in str(error.value) and provider.api_key not in caplog.text


def test_googlebooks_normalizes_metadata(tmp_path):
    provider = GooglebooksProvider(tmp_path, 24, api_key="test-key")
    provider._request_json = Mock(
        return_value={
            "items": [
                {
                    "id": "volume-1",
                    "volumeInfo": {
                        "title": "Example",
                        "authors": ["Writer"],
                        "publisher": "Publisher",
                        "language": "fr",
                        "publishedDate": "2020-01-02",
                        "industryIdentifiers": [{"identifier": ISBN}],
                        "imageLinks": {"thumbnail": "http://images.test/cover.jpg"},
                        "description": "Summary",
                    },
                }
            ]
        }
    )
    candidate = provider.search_book(BookQuery(title="Example", isbn=ISBN))[0]
    assert candidate.isbns == [ISBN] and candidate.publication_date == "2020-01-02"
    assert provider._request_json.call_args.kwargs["params"]["q"] == f"isbn:{ISBN}"
    assert provider._request_json.call_args.kwargs["headers"]["X-Goog-Api-Key"] == "test-key"


BNF_XML = b"""<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<srw:records><srw:record><srw:recordData><dc:dc>
<dc:identifier>http://catalogue.bnf.fr/ark:/12148/cb41023439w</dc:identifier><dc:identifier>ISBN 9782070612758</dc:identifier>
<dc:title>Le petit prince / Antoine de Saint-Exupery</dc:title><dc:creator>Saint-Exupery, Antoine de (1900-1944). Auteur du texte</dc:creator>
<dc:language>fre</dc:language><dc:publisher>Gallimard</dc:publisher><dc:description>Collection : Folio junior</dc:description>
<dc:date>2007</dc:date></dc:dc></srw:recordData></srw:record></srw:records></srw:searchRetrieveResponse>"""


def test_bnf_sru_normalization_and_diagnostics(tmp_path):
    provider = BnfProvider(tmp_path, 24)
    provider.session.get = Mock(return_value=Mock(content=BNF_XML))
    found = provider.search_book(BookQuery(title="Le petit prince", isbn=ISBN))[0]
    assert found.external_id == "cb41023439w" and found.titles == ["Le petit prince"]
    assert found.language == "fr" and found.isbns == [ISBN] and found.description is None
    assert found.author_names == ["Saint-Exupery, Antoine de"]
    provider.session.get.return_value.content = (
        b'<r xmlns:d="http://www.loc.gov/zing/srw/diagnostic/"><d:diagnostic/></r>'
    )
    with pytest.raises(MetadataProviderError):
        provider.search_book(BookQuery(title="Another"))


def test_match_gui_search_selection_clear_and_membership(library_client, tmp_path):
    client, remote = library_client
    ebook_series = remote.get_series_in_library.return_value[0].model_copy(update={"library_id": "library-2"})
    remote.get_series_in_library.return_value = [ebook_series]
    source = record()
    chain = chain_with(source)
    with (
        patch("modules.webui.routes.ebook_matches.KomgaClient", return_value=remote),
        patch("modules.webui.routes.ebook_matches.get_providers", return_value=chain),
    ):
        base = "/libraries/library-2/match?series_id=series-1&book_id=book-1"
        page = client.get(base)
        assert page.status_code == 200 and "Search editions" in page.text
        chain.entries[0].provider.search_book.assert_not_called()
        page = client.get(base + "&q=Le+petit+prince")
        assert "Le petit prince" in page.text and "Use this edition" in page.text
        response = client.post(
            "/libraries/library-2/match",
            data={"series_id": "series-1", "book_id": "book-1", "provider": "openlibrary", "external_id": "OL123M"},
        )
        assert response.status_code == 303
        assert config_store.get_config().library_settings["library-2"].ebook_matches["book-1"].external_id == "OL123M"
        remote.update_book_metadata.assert_not_called()
        client.post(
            "/libraries/library-2/match", data={"series_id": "series-1", "book_id": "book-1", "action": "clear"}
        )
        assert config_store.get_config().library_settings["library-2"].ebook_matches == {}
        assert client.get(base.replace("book-1", "foreign-book")).status_code == 404
        assert client.get(base.replace("library-2", "library-1")).status_code == 404


@pytest.mark.parametrize("configured", [False, True])
def test_ebook_collect_stages_book_changes_for_review_without_remote_writes(library_client, tmp_path, configured):
    from modules.workflow import run_workflow

    client, remote = library_client
    cfg = config_store.get_config().model_copy(deep=True)
    cfg.komga.libraries = ["Ebooks"]
    cfg.system.workflow = "collect"
    cfg.system.dry_run = False
    if configured:
        cfg.library_settings["library-2"] = LibraryConfig(name="Ebooks", content_type="ebook")
    cfg.processing.update_fields.cover_image = False
    cfg.processing.update_fields.isbn = True
    cfg.processing.update_fields.release_date = True
    series = remote.get_series_in_library.return_value[0].model_copy(update={"library_id": "library-2"})
    remote.get_series_in_library.return_value = [series]
    items = remote.get_books_in_series.return_value
    items[0].metadata.isbn = ISBN
    config_store.save_config_to_db(cfg.model_dump(mode="json"))
    source = record(
        description="Ebook summary",
        publication_date="2007-02-01",
        creators=[MetadataCreator(name="Writer", role="writer")],
    )
    with (
        patch("modules.workflow.KomgaClient", return_value=remote),
        patch("modules.processor.get_providers", return_value=chain_with(source)),
        patch("modules.processor.Path", return_value=tmp_path),
    ):
        result = run_workflow(cfg, series_ids=[series.id], book_ids=["book-1"])
    assert result.success
    remote.update_series_metadata.assert_not_called()
    remote.update_book_metadata.assert_not_called()
    store = LocalCatalogue(remote.base_url)
    pending = json.loads(store.get("books", "book-1")["pending"])
    assert pending["summary"] == "Ebook summary" and pending["releaseDate"] == "2007-02-01"
    assert json.loads(store.get("books", "book-2")["pending"]) == {}
    assert json.loads(store.get("series", series.id)["pending"]) == {}
    assert "Ebook summary" in client.get("/review?library=library-2").text
    assert match_status(remote.base_url, "book-1")["state"] == "matched"


def test_ebook_links_merge_without_replacing_existing_values(series, app_config):
    cfg = ebook_config(app_config)
    cfg.system.dry_run = False
    cfg.processing.update_fields.link = True
    item = book("one")
    item.metadata.isbn = ISBN
    item.metadata.links = [{"label": "Official", "url": "https://official.test"}]
    client = Mock()
    client.get_books_in_series.return_value = [item]
    process_ebook_series(series, cfg, client, chain_with(record(site_url="https://openlibrary.org/books/OL123M")))
    payload = client.update_book_metadata.call_args.args[1]
    assert payload["links"][0] == item.metadata.links[0]
    assert payload["links"][1]["label"] == "Open Library"
    item.metadata.links_lock = True
    client.reset_mock()
    process_ebook_series(series, cfg, client, chain_with(record(site_url="https://openlibrary.org/books/OL123M")))
    client.update_book_metadata.assert_not_called()


def test_partial_dates_are_preserved_and_clear_rules_work_without_sources(series, app_config):
    cfg = ebook_config(app_config)
    cfg.system.dry_run = False
    cfg.processing.update_fields.release_date = True
    item = book("one")
    item.metadata.isbn = ISBN
    client = Mock()
    client.get_books_in_series.return_value = [item]
    process_ebook_series(series, cfg, client, chain_with(record(publication_date="2007")))
    client.update_book_metadata.assert_not_called()
    cfg.processing.update_fields.summary = False
    cfg.processing.update_fields.authors.writers = False
    cfg.processing.update_fields.release_date = False
    cfg.processing.remove_fields.summary = True
    item.metadata.summary = "Clear this"
    process_ebook_series(series, cfg, client, ProviderChain([]))
    client.update_book_metadata.assert_called_once_with("one", {"summary": ""})


def test_ebook_source_failures_continue_and_report_total_failure(app_config):
    cfg = ebook_config(app_config)
    item = book("one")
    item.metadata.isbn = ISBN
    chain = chain_with(record(), record(description="Fallback").model_copy(update={"provider": "bnf"}))
    chain.entries[0].provider.search_book.side_effect = MetadataProviderError("temporary failure")
    found, state = find_book_metadata(item, chain, cfg)
    assert found.description == "Fallback" and state == "matched"
    chain.entries[1].provider.search_book.side_effect = MetadataProviderError("temporary failure")
    with pytest.raises(MetadataProviderError, match="All ebook sources failed"):
        find_book_metadata(item, chain, cfg)


def test_template_update_does_not_propagate_to_another_library(library_client):
    client, _ = library_client
    client.post(
        "/libraries/library-2/settings", data=source_form(source_action="template_save", template_name="Personal")
    )
    cfg = config_store.get_config().model_copy(deep=True)
    key = next(iter(cfg.source_templates))
    cfg.library_settings["copy"] = LibraryConfig(
        name="Copy", content_type="ebook", providers=cfg.source_templates[key].providers
    )
    config_store.save_config_to_db(cfg.model_dump(mode="json"))
    form = {
        "section": "sources",
        "source_order": "openlibrary",
        "openlibrary_enabled": "1",
        "source_template": key,
        "source_action": "template_update",
        "template_name": "Renamed",
    }
    assert client.post("/libraries/library-2/settings", data=form).status_code == 303
    cfg = config_store.get_config()
    assert cfg.source_templates[key].name == "Renamed"
    assert [p.name for p in cfg.source_templates[key].providers] == ["openlibrary"]
    assert [p.name for p in cfg.library_settings["copy"].providers] == ["bnf", "openlibrary"]


def test_publish_book_cover_removal_uses_book_endpoint(library_client):
    from modules.workflow import push_metadata

    _, remote = library_client
    cfg = config_store.get_config().model_copy(deep=True)
    cfg.system.dry_run = False
    local = LocalKomgaClient(remote)
    local.get_libraries()
    local.get_series_in_library("library-1", "Manga")
    local.get_books_in_series("series-1", "Example Manga")
    local.store.save_cover("books", "book-1", None)
    with patch("modules.workflow.KomgaClient", return_value=remote):
        result = push_metadata(cfg, series_ids=["series-1"], book_ids=["book-1"])
    assert result.success
    remote.remove_uploaded_book_posters.assert_called_once_with("book-1")
    remote.remove_uploaded_series_posters.assert_not_called()


def test_match_validation_and_connection_errors_preserve_search(library_client):
    client, remote = library_client
    cfg = config_store.get_config().model_copy(deep=True)
    cfg.library_settings["library-1"] = LibraryConfig(name="Manga", content_type="ebook")
    config_store.save_config_to_db(cfg.model_dump(mode="json"))
    chain = chain_with(record())
    with (
        patch("modules.webui.routes.ebook_matches.KomgaClient", return_value=remote),
        patch("modules.webui.routes.ebook_matches.get_providers", return_value=chain),
    ):
        page = client.get("/libraries/library-1/match?series_id=series-1&book_id=book-1&q=Preserve+title&isbn=123")
        assert "This ISBN is invalid" in page.text and 'value="123"' in page.text
        chain.entries[0].provider.search_book.assert_not_called()
        chain.entries[0].provider.get_by_id.side_effect = RuntimeError("private diagnostic")
        response = client.post(
            "/libraries/library-1/match",
            data={
                "series_id": "series-1",
                "book_id": "book-1",
                "q": "Preserve title",
                "author": "Preserve author",
                "provider": "openlibrary",
                "external_id": "OL123M",
            },
        )
        assert response.status_code == 502
        assert 'value="Preserve title"' in response.text and 'value="Preserve author"' in response.text
        assert "private diagnostic" not in response.text


def test_known_adult_candidates_follow_source_settings(app_config):
    cfg = ebook_config(app_config)
    item = book("one")
    item.metadata.isbn = ISBN
    adult = record().model_copy(update={"adult": True})
    chain = chain_with(adult)
    assert find_book_metadata(item, chain, cfg)[0] is None
    chain.entries[0].provider.get_metadata.assert_not_called()
    chain.entries[0].config.allow_adult = True
    assert find_book_metadata(item, chain, cfg)[0].adult


def test_googlebooks_maturity_is_preserved_in_cached_candidates(tmp_path):
    provider = GooglebooksProvider(tmp_path, 24, api_key="fixture-key")
    provider._request_json = Mock(
        return_value={
            "items": [
                {
                    "id": "mature-1",
                    "volumeInfo": {"title": "Example", "maturityRating": "MATURE", "publisher": "Publisher"},
                }
            ]
        }
    )
    query = BookQuery(title="Example")
    assert provider.search_book(query)[0].adult
    cached = provider.search_book(query)[0]
    assert cached.adult and cached.publisher == "Publisher"
    provider._request_json.assert_called_once()


@pytest.mark.parametrize(
    ("status", "reason", "message"),
    [
        (503, "backendFailed", "temporarily unavailable"),
        (500, "backendError", "temporarily unavailable"),
        (429, "rateLimitExceeded", "quota or rate limit"),
        (403, "dailyLimitExceeded", "quota or rate limit"),
        (403, "accessNotConfigured", "denied access"),
        (400, "API_KEY_INVALID", "rejected the API key"),
        (401, None, "rejected the API key"),
        (404, "notFound", "edition was not found"),
    ],
)
def test_googlebooks_http_errors_are_actionable_and_never_expose_credentials(tmp_path, caplog, status, reason, message):
    provider = GooglebooksProvider(tmp_path, 24, api_key="never-expose-key")
    response = requests.Response()
    response.status_code = status
    response.url = "https://www.googleapis.com/books/v1/volumes?key=never-expose-key"
    response._content = json.dumps({"error": {"message": "never-expose-key", "errors": [{"reason": reason}]}}).encode()
    provider.session.request = Mock(return_value=response)
    with pytest.raises(MetadataProviderError, match=message) as error:
        provider.search_book(BookQuery(title="Example"))
    assert error.value.status_code == status and error.value.reason == reason
    assert "never-expose-key" not in str(error.value) and "never-expose-key" not in caplog.text
    if status == 503:
        assert "API key" not in str(error.value)
    assert provider.session.get_adapter("https://").max_retries.raise_on_status is False


def test_googlebooks_isbn_lookup_does_not_filter_out_other_languages(tmp_path):
    provider = GooglebooksProvider(tmp_path, 24, api_key="fixture-key")
    provider._request_json = Mock(return_value={"items": []})
    provider.search_book(BookQuery(title="Le petit prince", isbn=ISBN, language="en"))
    assert "langRestrict" not in provider._request_json.call_args.kwargs["params"]
    provider.search_book(BookQuery(title="Le petit prince", language="fr"))
    assert provider._request_json.call_args.kwargs["params"]["langRestrict"] == "fr"


def test_googlebooks_transient_failures_are_not_cached_as_missing_books(tmp_path):
    provider = GooglebooksProvider(tmp_path, 24, api_key="fixture-key")
    provider._request_json = Mock(side_effect=[MetadataProviderError("Unavailable", status_code=503), {"items": []}])
    query = BookQuery(title="Example")
    with patch("modules.providers.ebooks.time.monotonic", return_value=100) as clock:
        with pytest.raises(MetadataProviderError, match="temporarily unavailable"):
            provider.search_book(query)
        with pytest.raises(MetadataProviderError, match="temporarily paused"):
            provider.search_book(query)
        assert provider._request_json.call_count == 1
        clock.return_value = 161
        assert provider.search_book(query) == []
    assert provider._request_json.call_count == 2


def test_googlebooks_outage_keeps_cached_editions_available(tmp_path):
    provider = GooglebooksProvider(tmp_path, 24, api_key="fixture-key")
    provider._request_json = Mock(
        side_effect=[
            {"id": "cached-volume", "volumeInfo": {"title": "Cached edition"}},
            MetadataProviderError("Unavailable", status_code=503),
        ]
    )
    cached = provider.get_by_id("cached-volume")
    with pytest.raises(MetadataProviderError):
        provider.search_book(BookQuery(title="Uncached edition"))
    assert provider.get_by_id("cached-volume") == cached
    with pytest.raises(MetadataProviderError) as failure:
        provider.get_by_id("another-volume")
    assert failure.value.reason == "service_cooldown"
    assert failure.value.status_code == 503
    assert provider._request_json.call_count == 2


def test_googlebooks_cooldown_continues_openlibrary_for_each_book(tmp_path, app_config, caplog):
    cfg = ebook_config(app_config)
    google = GooglebooksProvider(tmp_path, 24, api_key="fixture-key")
    google._request_json = Mock(side_effect=MetadataProviderError("Unavailable", status_code=503))
    chain = chain_with(record(description="Open Library fallback"))
    chain.entries.insert(0, ConfiguredProvider(ProviderConfig(name="googlebooks"), google))
    for book_id in ["one", "two"]:
        item = book(book_id)
        item.metadata.isbn = ISBN
        found, state = find_book_metadata(item, chain, cfg)
        assert found.description == "Open Library fallback" and state == "matched"
    google._request_json.assert_called_once()
    assert chain.entries[1].provider.search_book.call_count == 2
    assert caplog.text.count("Ebook source googlebooks failed") == 1


def test_ebook_fetch_uses_known_series_language_before_source_preference(series, app_config):
    cfg = ebook_config(app_config)
    cfg.system.dry_run = False
    cfg.processing.overwrite_existing = True
    item = book("one")
    item.metadata.title = "Le petit prince"
    item.metadata.isbn = ""
    item.metadata.summary = ""
    series.metadata.language = "fr-FR"
    chain = chain_with(record(description="Résumé français"))
    chain.entries[0].config.preferred_language = "en"
    client = Mock()
    client.get_books_in_series.return_value = [item]
    process_ebook_series(series, cfg, client, chain)
    assert chain.entries[0].provider.search_book.call_args.args[0].language == "fr"
    assert client.update_book_metadata.call_args.args[1]["summary"] == "Résumé français"


def test_ebook_outage_message_suggests_retry_instead_of_manual_match(series, app_config, caplog):
    cfg = ebook_config(app_config)
    item = book("one")
    chain = chain_with(record(), [record()])
    chain.entries[0].provider.search_book.side_effect = MetadataProviderError("Unavailable", status_code=503)
    chain.entries[1].provider.search_book.return_value = []
    client = Mock()
    client.get_books_in_series.return_value = [item]
    process_ebook_series(series, cfg, client, chain)
    assert "retry Fetch later" in caplog.text
    assert "Choose an edition" not in caplog.text
