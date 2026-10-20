"""Guided edition selection for one verified ebook, saved for subsequent fetches."""

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from modules.config import EbookMatch, LibraryConfig, config_for_library
from modules.ebook_metadata import book_query, match_status
from modules.komga_client import KomgaClient
from modules.local_metadata import LocalKomgaClient
from modules.manual_metadata import ManualEditError, load_target
from modules.providers import get_providers
from modules.providers.base import MetadataProviderError
from modules.providers.ebooks import BookQuery, normalize_isbn
from modules.source_catalogue import SOURCE_CATALOGUE
from modules.webui.config_store import get_config, save_config_to_db
from modules.webui.db import add_audit_entry
from modules.webui.routes.dashboard import library_type
from modules.webui.routes.guards import get_current_user


def setup_routes(templates) -> APIRouter:
    """Offer searches and explicit selections without publishing book metadata."""
    router = APIRouter(prefix="/libraries")

    def execute(cfg, library_id, series_id, book_id, operation):
        remote = KomgaClient(cfg.komga)
        client = LocalKomgaClient(remote, refresh=False)
        try:
            target = load_target(client, library_id, series_id, book_id)
            library = next(lib for lib in client.get_libraries() if lib.id == library_id)
            if not target.book or library_type(cfg, library) != "ebook":
                raise ManualEditError("manual.missing", 404)
            scoped = cfg.model_copy(deep=True)
            if library_id not in scoped.library_settings:
                scoped.library_settings[library_id] = LibraryConfig(name=library.name, content_type="ebook")
            effective = config_for_library(scoped, library_id)
            chain = get_providers(effective.providers, Path("/config/cache"), cfg.google_books_api_key)
            try:
                return operation(target, library, effective, chain)
            finally:
                if chain:
                    chain.save_cache()
                    for entry in chain.entries:
                        entry.provider.session.close()
        finally:
            client.session.close()

    @router.get("/{library_id}/match")
    async def page(
        request: Request,
        library_id: str,
        series_id: str,
        book_id: str,
        q: str | None = None,
        author: str = "",
        isbn: str = "",
        source: str = "",
    ):
        if not get_current_user(request):
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if not cfg:
            return RedirectResponse("/settings?tab=connection", status_code=302)

        def search(target, library, effective, chain):
            query = (
                BookQuery(title=q[:300], author=author[:200], isbn=isbn.strip())
                if q is not None
                else book_query(target.book, target.series.metadata.language)
            )
            candidates, errors = [], []
            invalid_isbn = bool(query.isbn and not normalize_isbn(query.isbn))
            if q is not None and not invalid_isbn:
                for entry in chain.entries:
                    if source and source != entry.config.name:
                        continue
                    try:
                        candidates.extend(entry.provider.search_book(query))
                    except MetadataProviderError:
                        errors.append(SOURCE_CATALOGUE[entry.config.name]["display"])
            return {
                "library": library,
                "target": target,
                "query": query,
                "candidates": candidates,
                "source": source,
                "source_errors": errors,
                "searched": q is not None and not invalid_isbn,
                "error": "matches.invalid_isbn" if invalid_isbn else None,
                "sources": [entry.config.name for entry in chain.entries],
                "selected_match": effective.ebook_matches.get(book_id),
                "source_names": SOURCE_CATALOGUE,
            }

        try:
            context = await run_in_threadpool(execute, cfg, library_id, series_id, book_id, search)
        except ManualEditError as exc:
            return Response(status_code=exc.status)
        except Exception:
            context = {
                "error": "matches.connection",
                "query": BookQuery(title=q or "", author=author, isbn=isbn),
                "candidates": [],
                "library_id": library_id,
                "series_id": series_id,
                "book_id": book_id,
            }
        return templates.TemplateResponse(
            request=request,
            name="ebook_match.html",
            context={
                **context,
                "username": get_current_user(request),
                "library_id": library_id,
                "series_id": series_id,
                "book_id": book_id,
                "saved": bool(request.query_params.get("saved")),
            },
        )

    @router.post("/{library_id}/match")
    async def select(request: Request, library_id: str):
        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=302)
        cfg = get_config()
        if not cfg:
            return RedirectResponse("/settings?tab=connection", status_code=302)
        form = await request.form()
        series_id, book_id = form.get("series_id", ""), form.get("book_id", "")

        def save(target, library, effective, chain):
            raw = cfg.model_dump(mode="json")
            profile = raw["library_settings"].setdefault(
                library_id, LibraryConfig(name=library.name, content_type="ebook").model_dump()
            )
            matches = profile.setdefault("ebook_matches", {})
            if form.get("action") == "clear":
                matches.pop(book_id, None)
            else:
                entry = next((entry for entry in chain.entries if entry.config.name == form.get("provider")), None)
                if not entry:
                    raise ValueError("Source is disabled")
                record = entry.provider.get_by_id(form.get("external_id", ""))
                matches[book_id] = EbookMatch(
                    provider=record.provider, external_id=record.external_id, title=record.display_title
                ).model_dump()
            save_config_to_db(raw)
            match_status(
                str(cfg.komga.url),
                book_id,
                "selected" if book_id in matches else "",
                matches.get(book_id, {}).get("title", ""),
            )
            add_audit_entry(
                "EBOOK_MATCH", f"Edition selection saved for {book_id} in library {library_id} by {username}."
            )

        try:
            await run_in_threadpool(execute, cfg, library_id, series_id, book_id, save)
        except ManualEditError as exc:
            return Response(status_code=exc.status)
        except Exception as exc:
            return templates.TemplateResponse(
                request=request,
                name="ebook_match.html",
                status_code=422 if isinstance(exc, (MetadataProviderError, ValueError)) else 502,
                context={
                    "username": username,
                    "library_id": library_id,
                    "series_id": series_id,
                    "book_id": book_id,
                    "error": "matches.save_failed",
                    "query": BookQuery(
                        title=form.get("q", ""), author=form.get("author", ""), isbn=form.get("isbn", "")
                    ),
                },
            )
        query = urlencode({"series_id": series_id, "book_id": book_id, "saved": 1})
        return RedirectResponse(f"/libraries/{library_id}/match?{query}", status_code=303)

    return router
