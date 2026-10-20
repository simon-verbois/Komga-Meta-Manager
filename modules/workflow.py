"""Run collection, publication, or both using the same persisted local catalogue."""

import base64
import json
import logging

from modules.config import config_for_library
from modules.komga_client import KomgaClient
from modules.local_metadata import LocalCatalogue, LocalKomgaClient, local_edit_lock
from modules.processor import ProcessingResult, process_libraries
from modules.webui.db import get_db

logger = logging.getLogger(__name__)


def push_metadata(config, stop_event=None, series_ids=None, progress_callback=None, book_ids=None, store=None):
    """Publish pending fields only, checking current membership and remote locks."""
    result = ProcessingResult()
    client = KomgaClient(config.komga)
    store = store or LocalCatalogue(client.base_url)
    try:
        libraries = [library for library in client.get_libraries() if library.name in config.komga.libraries]
        if not libraries:
            logger.error("No enabled libraries are available in Komga; local changes are kept.")
            result.success = False
            return result
        for library in libraries:
            effective = config_for_library(config, library.id)
            remote_series = {
                s.id: s for s in client.get_series_in_library(library.id, library.name) if s.library_id == library.id
            }
            for series_id, series in remote_series.items():
                if series_ids is not None and series_id not in series_ids:
                    continue
                if stop_event and stop_event.is_set():
                    return result
                if series.name in effective.processing.exclude_series:
                    result.skipped += 1
                    continue
                try:
                    books = {
                        b.id: b for b in client.get_books_in_series(series_id, series.name) if b.series_id == series_id
                    }
                    targets = [
                        ("series", series),
                        *(("books", b) for b in books.values() if book_ids is None or b.id in book_ids),
                    ]
                    for entity, item in targets:
                        row = store.get(entity, item.id)
                        if not row or row["library_id"] != library.id or row["series_id"] != series_id:
                            continue
                        pending = json.loads(row["pending"])
                        current = item.metadata.model_dump(mode="json", by_alias=True)
                        baseline = json.loads(row["remote"]) if row["remote"] else {}
                        manual = set(json.loads(row["manual"]))
                        # Explicit edits may change a known locked value while keeping it
                        # locked. A value or lock changed in Komga since Fetch still blocks.
                        confirmed_manual = {
                            key for key in manual
                            if pending.get(f"{key}Lock") is True
                            and key in baseline and baseline[key] == current.get(key)
                            and baseline.get(f"{key}Lock") == current.get(f"{key}Lock")
                        }
                        blocked = [
                            key
                            for key in pending
                            if not key.endswith("Lock")
                            and current.get(f"{key}Lock")
                            and current.get(key) != pending[key]
                            and key not in confirmed_manual
                            and not effective.processing.force_unlock
                        ]
                        if blocked:
                            raise ValueError(
                                f"Locked fields on {entity} {item.id}: {', '.join(blocked)}. Pending changes kept; review Force Unlock."
                            )
                        patch = {key: value for key, value in pending.items() if current.get(key) != value}
                        logger.info(
                            "Push %s %s: %s%s",
                            entity,
                            item.id,
                            list(patch),
                            " (simulation)" if config.system.dry_run else "",
                        )
                        if config.system.dry_run:
                            if row["cover_pending"] and row["cover"]:
                                logger.info("Would publish local cover for %s %s", entity, item.id)
                            continue
                        if patch:
                            update = client.update_book_metadata if entity == "books" else client.update_series_metadata
                            if not update(item.id, patch):
                                raise RuntimeError(f"Komga rejected {entity} {item.id}; pending changes kept")
                        if row["cover_pending"] and row["cover"] == "remove":
                            client.remove_uploaded_series_posters(item.id)
                        elif row["cover_pending"] and row["cover"]:
                            client.upload_custom_cover(entity, item.id, base64.b64decode(row["cover"]))
                        with get_db() as conn:
                            conn.execute(
                                "UPDATE local_metadata SET pending='{}', cover_pending=0, remote=? WHERE server=? AND entity=? AND id=? AND pending=? AND cover IS ?",
                                (json.dumps({**current, **pending}), store.server, entity, item.id, row["pending"], row["cover"]),
                            )
                    result.processed += 1
                except Exception:
                    result.failed += 1
                    result.success = False
                    logger.exception("Could not publish series %s. Remaining local changes are kept.", series_id)
                if progress_callback:
                    progress_callback(result)
    finally:
        client.session.close()
    return result


def job_snapshot(config, action: str):
    """Prepare a job that fetches into KMM, publishes to Komga, or does both, always for real."""
    snapshot = config.model_copy(deep=True)
    snapshot.system.workflow = {"fetch": "collect", "publish": "push", "fetch_publish": "both"}[action]
    snapshot.system.dry_run = False
    snapshot.system.overwrite_local = False
    return snapshot


def automation_snapshot(config):
    """Scheduled and watcher runs fetch into KMM and publish only when the user allowed it."""
    return job_snapshot(config, "fetch_publish" if config.system.auto_publish else "fetch")


def run_workflow(config, stop_event=None, series_ids=None, progress_callback=None, book_ids=None):
    """Complete phase one before allowing phase two; never push a failed collection."""
    from modules.webui.db import init_db

    if not config.komga.libraries:
        logger.info("No libraries enabled. Nothing to process.")
        return ProcessingResult()
    init_db()
    with local_edit_lock():
        if config.system.workflow == "push":
            logger.info("Phase 2: publishing saved KMM metadata to Komga.")
            return push_metadata(config, stop_event, series_ids, progress_callback, book_ids)
        logger.info("Phase 1: collecting catalogue and source metadata locally in KMM.")
        collecting = config.model_copy(deep=True)
        # Execute into an in-memory overlay for previews, including cover planning.
        collecting.system.dry_run = False
        preview_store = LocalCatalogue(str(config.komga.url), preview=True) if config.system.dry_run else None
        if preview_store:
            logger.info("Simulation: planning in memory; no metadata will be saved or published.")
        result = process_libraries(
            collecting,
            stop_event,
            series_ids,
            progress_callback,
            book_ids,
            client_factory=lambda cfg: LocalKomgaClient(
                KomgaClient(cfg.komga),
                exclude_series=cfg.processing.exclude_series,
                replace=config.system.overwrite_local,
                preview=config.system.dry_run,
                series_ids=series_ids,
                book_ids=book_ids,
                store=preview_store,
            ),
        )
        if config.system.workflow == "both" and result.success and not (stop_event and stop_event.is_set()):
            logger.info(
                "Phase 2: publishing collected KMM metadata to Komga%s.",
                " (simulation)" if config.system.dry_run else "",
            )
            pushed = push_metadata(config, stop_event, series_ids, progress_callback, book_ids, store=preview_store)
            result.success = pushed.success
            result.failed += pushed.failed
        return result
