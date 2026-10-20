"""Isolated job entry point; stdin carries settings, stdout carries events."""

import json
import logging
import signal
import sys
import threading

from modules.config import AppConfig
from modules.processor import ProcessingResult
from modules.workflow import run_workflow


class EventHandler(logging.Handler):
    """Forward worker logs to the parent UI and container log stream."""

    def emit(self, record: logging.LogRecord) -> None:
        print(json.dumps({"type": "log", "level": record.levelno, "message": self.format(record)}), flush=True)


def report_progress(result: ProcessingResult) -> None:
    """Publish processing counters without serializing live provider objects."""
    print(
        json.dumps(
            {
                "type": "progress",
                "processed": result.processed,
                "failed": result.failed,
                "skipped": result.skipped,
            }
        ),
        flush=True,
    )


def main() -> int:
    """Execute one snapshot, stopping between series when SIGTERM is received."""
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logging.basicConfig(level=logging.INFO, handlers=[EventHandler()], format="%(message)s", force=True)
    payload = json.load(sys.stdin)
    config = AppConfig.model_validate(payload["config"])
    logging.getLogger().setLevel(logging.DEBUG if config.system.debug else logging.INFO)
    logging.getLogger("modules").setLevel(logging.DEBUG)
    logging.getLogger("modules.job_worker").debug(
        "Processing job with %s enabled libraries (dry_run=%s).", len(config.komga.libraries), config.system.dry_run,
    )
    result = None
    try:
        result = run_workflow(
            config,
            stop_event=stop,
            series_ids=payload.get("series_ids"),
            progress_callback=report_progress,
            book_ids=payload.get("book_ids"),
        )
        report_progress(result)
        return 2 if stop.is_set() else (0 if result.success else 1)
    except Exception:
        logging.exception("Job failed. Check the connection and saved processing settings before retrying.")
        return 1
    finally:
        translator = result.translator if result else None
        if translator and hasattr(translator, "save_cache_to_disk"):
            translator.save_cache_to_disk()


if __name__ == "__main__":
    raise SystemExit(main())
