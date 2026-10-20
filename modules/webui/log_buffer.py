# -*- coding: utf-8 -*-
"""
In-memory circular log buffer for the execution log viewer.

A custom ``logging.Handler`` appends structured records to a ``deque``
(capped at MAX_LINES).  The Web UI polls /logs/exec/lines via HTMX and
reads from this buffer.
"""
import logging
import threading
from collections import deque
from collections.abc import Collection
from datetime import datetime, timezone
from enum import Enum

MAX_LINES = 500


class LogLevel(str, Enum):
    """Levels exposed by the execution log filters."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


LOG_LEVELS = tuple(level.value for level in LogLevel)
DEFAULT_LOG_LEVELS = LOG_LEVELS[1:]

_lock = threading.RLock()
_buffer: deque = deque(maxlen=MAX_LINES)


class BufferHandler(logging.Handler):
    """Logging handler that appends to the in-memory buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            entry = {
                "ts": datetime.fromtimestamp(record.created, timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "level": record.levelname,
                "msg": message,
            }
            with _lock:
                _buffer.append(entry)
        except Exception:  # noqa: BLE001
            self.handleError(record)


def install_handler() -> BufferHandler:
    """
    Attach a BufferHandler to the root logger and return it.
    Should be called once, early in startup.
    """
    for existing in logging.getLogger().handlers:
        if isinstance(existing, BufferHandler):
            return existing
    handler = BufferHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def get_lines(levels: Collection[str] | None = None) -> list[dict]:
    """Return entries matching the selected levels; an empty selection shows none."""
    selected = set(DEFAULT_LOG_LEVELS if levels is None else levels)
    with _lock:
        return [entry for entry in _buffer if entry["level"] in selected]


def clear_buffer() -> None:
    """Remove all entries from the buffer."""
    with _lock:
        _buffer.clear()
