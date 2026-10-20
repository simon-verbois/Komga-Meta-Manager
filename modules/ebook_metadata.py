"""Conservative edition matching and book-only enrichment for ebook libraries."""

import logging
import re
from datetime import date

from thefuzz import fuzz

from modules.models import MetadataRecord
from modules.providers.base import MetadataProviderError
from modules.providers.ebooks import BookQuery, iso_language, normalize_isbn
from modules.utils import clean_description
from modules.webui.db import get_db

logger = logging.getLogger(__name__)


def match_status(server: str, book_id: str, state: str | None = None, detail: str = "") -> dict:
    """Persist a readable match outcome separately from pending metadata edits."""
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS ebook_match_status (
            server TEXT, book_id TEXT, state TEXT, detail TEXT, PRIMARY KEY(server, book_id))""")
        if state is not None:
            conn.execute(
                "INSERT OR REPLACE INTO ebook_match_status VALUES (?, ?, ?, ?)",
                (server.rstrip("/"), book_id, state, detail),
            )
        row = conn.execute(
            "SELECT state, detail FROM ebook_match_status WHERE server=? AND book_id=?", (server.rstrip("/"), book_id)
        ).fetchone()
    return dict(row) if row else {"state": "", "detail": ""}


def book_query(book, language: str = "") -> BookQuery:
    """Use saved book metadata and a validated ISBN; never use the parent series title."""
    authors = [author.get("name", "") for author in book.metadata.authors if author.get("role") == "writer"]
    isbn = normalize_isbn(book.metadata.isbn)
    if not isbn:
        for value in re.findall(r"(?<!\d)(?:97[89][ -]?)?\d[\d -]{7,20}[\dXx](?!\d)", book.name):
            isbn = normalize_isbn(value)
            if isbn:
                break
    return BookQuery(
        title=book.metadata.title.strip() or book.name,
        author=next(iter(authors), ""),
        isbn=isbn,
        language=iso_language(language),
    )


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def candidate_score(query: BookQuery, candidate) -> int | None:
    """Require edition identity by ISBN, or corroborated title, author and language."""
    if query.isbn:
        return 100 if query.isbn in {normalize_isbn(value) for value in candidate.isbns} else None
    if query.language and candidate.language and iso_language(query.language) != iso_language(candidate.language):
        return None
    score = max((fuzz.ratio(_normalized(query.title), _normalized(title)) for title in candidate.titles), default=0)
    if query.author:

        def tokens(value):
            return " ".join(sorted(re.findall(r"\w+", value.casefold())))

        if (
            not candidate.author_names
            or max(fuzz.ratio(tokens(query.author), tokens(name)) for name in candidate.author_names) < 85
        ):
            return None
    return score


def find_book_metadata(book, chain, config, language: str = "") -> tuple[MetadataRecord | None, str]:
    """Prefer an exact ISBN, then rank title/author matches when no edition is found."""
    query = book_query(book, language)
    pinned = config.ebook_matches.get(book.id)
    entries = chain.entries
    if pinned:
        entry = next((item for item in entries if item.config.name == pinned.provider), None)
        if entry is None:
            return None, "source_disabled"
        return entry.provider.get_by_id(pinned.external_id), "selected"
    queries = [query]
    if query.isbn:
        queries.append(query.model_copy(update={"isbn": ""}))
    had_errors = False
    total_failures = 0
    state = "no_sources"
    for search_query in queries:
        try:
            record, state = _find_from_sources(search_query, entries)
        except MetadataProviderError:
            total_failures += 1
            had_errors = True
            continue
        if record is not None or state == "ambiguous":
            if record is not None and query.isbn and not search_query.isbn:
                logger.info("Ebook '%s': matched by title after ISBN lookup found no usable edition.", query.title)
            return record, state
        had_errors = had_errors or state == "error"
    if total_failures == len(queries):
        raise MetadataProviderError("All ebook sources failed; check source settings and retry")
    return None, "error" if had_errors else state


def _find_from_sources(query: BookQuery, entries) -> tuple[MetadataRecord | None, str]:
    """Rank one search pass and merge only records sharing an edition ISBN."""
    primary = None
    ambiguous = False
    failures = 0
    for entry in entries:
        try:
            source_query = query.model_copy(
                update={"language": query.language or iso_language(entry.config.preferred_language)}
            )
            candidates = entry.provider.search_book(source_query)
            ranked = [
                (score, candidate)
                for candidate in candidates
                if (not candidate.adult or entry.config.allow_adult)
                and (score := candidate_score(source_query, candidate)) is not None
                and score >= entry.config.min_score
            ]
            ranked.sort(key=lambda item: item[0], reverse=True)
            if not ranked:
                continue
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 5:
                ambiguous = True
                continue
            record = entry.provider.get_metadata(ranked[0][1])
            # Re-check full records before writing, including language and ISBN.
            full_score = candidate_score(source_query, record)
            if (
                full_score is None
                or full_score < entry.config.min_score
                or (record.adult and not entry.config.allow_adult)
            ):
                continue
            if primary is None:
                primary = record
                if not record.isbns:
                    break
                query = query.model_copy(update={"isbn": record.isbns[0]})
            else:
                from modules.processor import _merge_missing_metadata

                # Edition-specific fields must never cross ISBN boundaries.
                if set(primary.isbns) & set(record.isbns):
                    primary = _merge_missing_metadata(primary, record)
                    primary.publication_date = primary.publication_date or record.publication_date
        except MetadataProviderError as exc:
            failures += 1
            log = logger.debug if exc.reason == "service_cooldown" else logger.warning
            log("Ebook source %s failed: %s", entry.config.name, exc)
    if primary:
        return primary, "matched"
    if failures and failures == len(entries):
        raise MetadataProviderError("All ebook sources failed; check source settings and retry")
    return None, "no_sources" if not entries else ("ambiguous" if ambiguous else ("error" if failures else "not_found"))


def _release_date(value: str | None) -> str | None:
    if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    # Partial/locale dates do not justify inventing a day or month.
    return None


def process_ebook_series(series, config, client, chain, translator=None, book_ids=None, stop_event=None):
    """Enrich selected books without writing any parent series or sibling metadata."""
    from modules.processor import _remove_authors, _update_authors, should_update_field

    changes = []
    for book in client.get_books_in_series(series.id, series.name):
        if stop_event and stop_event.is_set():
            break
        if book.series_id != series.id or (book_ids is not None and book.id not in book_ids):
            continue
        local = getattr(client, "metadata_destination", None) == "KMM"
        preview = config.system.dry_run or (local and client.store.preview)
        update = config.processing.update_fields
        need_source = any(
            (update.summary, update.authors.writers, update.cover_image, update.link, update.isbn, update.release_date)
        )
        try:
            record, state = (
                find_book_metadata(book, chain, config, series.metadata.language) if need_source else (None, "")
            )
        except MetadataProviderError:
            if local and not preview:
                match_status(str(config.komga.url), book.id, "error")
            raise
        if local and not preview and state:
            match_status(str(config.komga.url), book.id, state, record.display_title if record else "")
        if record is None:
            if need_source:
                next_step = {
                    "error": "Some sources are unavailable and no compatible edition was found; retry Fetch later.",
                    "not_found": "No compatible edition found in the enabled sources. Try Find match in Libraries.",
                    "ambiguous": "Several editions match. Choose an edition from Find match in Libraries.",
                    "source_disabled": "The selected edition source is disabled; enable it or choose another edition.",
                    "no_sources": "Enable ebook sources in Libraries → Metadata sources.",
                }.get(state, "No source metadata was selected.")
                logger.warning(
                    "Ebook '%s': %s %s Existing metadata is kept unless explicitly configured for removal.",
                    book.metadata.title,
                    state,
                    next_step,
                )
            record = MetadataRecord(provider="openlibrary", external_id="", titles=[])
        payload = {}
        update = config.processing.update_fields
        remove = config.processing.remove_fields

        def plan(field, value, enabled, clear=False):
            current = getattr(book.metadata, field)
            locked = getattr(book.metadata, field + "_lock", False)
            if clear:
                allowed = not locked or config.processing.force_unlock
            else:
                allowed = (
                    enabled
                    and value
                    and (not locked or config.processing.force_unlock)
                    and (field == "links" or should_update_field(current, locked, config))
                )
            if allowed and value != current:
                key = {"release_date": "releaseDate"}.get(field, field)
                payload[key] = value
                if locked and config.processing.force_unlock:
                    payload[key + "Lock"] = False
                changes.append(f"Book {book.id}: {key} updated")

        summary = clean_description(record.description) if record.description else ""
        if summary and translator and config.translation:
            summary = translator.translate(
                summary, config.translation.target_language, source_language=record.description_language
            )
        plan("summary", "" if remove.summary else summary, update.summary, remove.summary)
        known_isbn = book_query(book).isbn
        same_edition = (
            not known_isbn
            or known_isbn in {normalize_isbn(value) for value in record.isbns}
            or book.id in config.ebook_matches
        )
        plan("isbn", "" if remove.isbn else next(iter(record.isbns), ""), update.isbn and same_edition, remove.isbn)
        plan(
            "release_date",
            None if remove.release_date else _release_date(record.publication_date),
            update.release_date and same_edition,
            remove.release_date,
        )
        links = list(book.metadata.links)
        if remove.link:
            from modules.source_catalogue import SOURCE_CATALOGUE

            links = [
                link
                for link in links
                if link.get("label", "").casefold()
                not in {name.casefold() for name in SOURCE_CATALOGUE}
                | {source["display"].casefold() for source in SOURCE_CATALOGUE.values()}
            ]
        elif update.link:
            from modules.processor import _provider_links
            from modules.source_catalogue import SOURCE_CATALOGUE

            for name, url in _provider_links(record).items():
                label = SOURCE_CATALOGUE[name]["display"]
                position = next(
                    (
                        i
                        for i, link in enumerate(links)
                        if link.get("label", "").casefold() in {name.casefold(), label.casefold()}
                    ),
                    None,
                )
                if position is not None:
                    if config.processing.overwrite_existing:
                        links[position] = {"label": label, "url": url}
                elif not any(link.get("url") == url for link in links):
                    links.append({"label": label, "url": url})
        plan("links", links, update.link, remove.link)
        if remove.authors.writers or remove.authors.pencillers:
            _remove_authors([book], config, changes, client, series.name)
        if record.creators and (update.authors.writers or update.authors.pencillers):
            _update_authors([book], record, config, changes, client)
        if remove.cover_image:
            removed = client.remove_uploaded_book_posters(book.id, dry_run=config.system.dry_run)
            if removed:
                changes.append(f"Book {book.id}: custom cover removed")
        elif update.cover_image:
            for url in record.cover_urls:
                try:
                    result = client.update_book_poster(
                        book.id, url, config.processing.overwrite_existing, config.system.dry_run
                    )
                    if result != "preserved":
                        changes.append(f"Book {book.id}: cover updated")
                    break
                except Exception:
                    logger.warning("Could not use ebook cover; trying the next available image")
        if payload and not config.system.dry_run and not client.update_book_metadata(book.id, payload):
            raise RuntimeError(f"Could not save ebook metadata for {book.id}")
    for change in changes:
        logger.info("%s%s", "[DRY-RUN] " if config.system.dry_run else "", change)
    return changes if config.system.dry_run else None
