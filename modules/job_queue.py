"""Persistent FIFO queue with one isolated metadata worker at a time."""

import json
import logging
import subprocess
import sys
import threading
from datetime import datetime, timezone
from typing import Callable

from modules.config import AppConfig
from modules.webui.db import add_audit_entry, append_job_log, get_db

logger = logging.getLogger(__name__)
RETRY_STATUSES = ("failed", "cancelled", "killed", "interrupted")
MAX_PENDING = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def launch_worker(payload: dict) -> subprocess.Popen:
    """Pass secrets through stdin, never through command-line arguments."""
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "modules.job_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
    except Exception:
        process.kill()
        process.wait()
        raise
    return process


def job_kind(saved: dict) -> dict:
    """Describe a saved job snapshot in user terms: what it does and whether it only simulated."""
    system = saved.get("system", {})
    action = {"collect": "fetch", "push": "publish", "both": "fetch_publish"}.get(system.get("workflow", "both"), "fetch_publish")
    return {"action": action, "simulated": bool(system.get("dry_run", False))}


class QueueFullError(ValueError):
    """The queue cannot accept more pending work."""


class JobQueue:
    """Serialize execution, persist state, and signal only the active child."""

    def __init__(self, process_factory: Callable = launch_worker) -> None:
        self._process_factory = process_factory
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None
        self._active_id: int | None = None
        self._killed = False

    def start(self) -> None:
        """Recover unfinished jobs and resume pending jobs after a restart."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            with get_db() as conn:
                conn.execute(
                    "UPDATE jobs SET status='interrupted', finished_at=? WHERE status IN ('running', 'stopping')",
                    (_now(),),
                )
            self._shutdown.clear()
            self._thread = threading.Thread(target=self._work, daemon=True, name="job-queue")
            self._thread.start()

    def close(self) -> None:
        """Stop the active child and preserve pending work for the next start."""
        self._shutdown.set()
        self._wake.set()
        with self._lock:
            process = self._process
            if process and process.poll() is None:
                process.terminate()
        if self._thread:
            self._thread.join(timeout=5)
            with self._lock:
                if self._process and self._process.poll() is None:
                    self._process.kill()
            self._thread.join(timeout=5)

    def enqueue(
        self,
        config: AppConfig,
        source: str = "manual",
        series_ids: list[str] | None = None,
        book_ids: list[str] | None = None,
    ) -> int:
        """Save an immutable settings and library snapshot before waking the worker."""
        if not config.komga.libraries:
            raise ValueError("No libraries enabled")
        with self._lock, get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pending = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
            if pending >= MAX_PENDING:
                raise QueueFullError("Queue full")
            cursor = conn.execute(
                "INSERT INTO jobs (source, config, series_ids, created_at, book_ids) VALUES (?, ?, ?, ?, ?)",
                (source, config.model_dump_json(), json.dumps(series_ids), _now(), json.dumps(book_ids)),
            )
            job_id = cursor.lastrowid
        self._wake.set()
        return job_id

    def snapshot(self) -> dict:
        """Return active jobs and the last 20 outcomes without exposing secrets."""
        with get_db() as conn:
            # Both lists must see the same state if a job finishes during polling.
            conn.execute("BEGIN")
            active = conn.execute(
                "SELECT * FROM jobs WHERE status IN ('queued', 'running', 'stopping') ORDER BY id",
            ).fetchall()
            history = conn.execute(
                "SELECT * FROM jobs WHERE status NOT IN ('queued', 'running', 'stopping') ORDER BY id DESC LIMIT 20",
            ).fetchall()
        jobs = []
        position = 0
        for row in [*active, *history]:
            job = dict(row)
            config = json.loads(job.pop("config"))
            job.pop("book_ids", None)
            job["libraries"] = config["komga"]["libraries"]
            job["dry_run"] = config["system"]["dry_run"]
            job["workflow"] = config["system"].get("workflow", "both")
            job.update(job_kind(config))
            ids = json.loads(job.pop("series_ids"))
            job["series_count"] = len(ids) if ids is not None else None
            if job["status"] == "queued":
                position += 1
            job["position"] = position if job["status"] == "queued" else None
            jobs.append(job)
        return {
            "jobs": jobs,
            "active": [job for job in jobs if job["status"] in ("queued", "running", "stopping")],
            "pending": position,
            "running": any(j["status"] in ("running", "stopping") for j in jobs),
        }

    def cancel(self, job_id: int, force: bool = False) -> bool:
        """Cancel pending work, request a graceful stop, or kill a blocked worker."""
        with self._lock, get_db() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return False
            status = row["status"]
            if status == "queued" and not force:
                conn.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=?", (_now(), job_id))
            elif (
                status in ("running", "stopping")
                and self._active_id == job_id
                and self._process
                and self._process.poll() is None
            ):
                if force:
                    self._process.kill()
                elif status == "running":
                    self._process.terminate()
                else:
                    return False
                # Keep the worker occupied until wait() confirms the child exited.
                conn.execute("UPDATE jobs SET status=? WHERE id=?", ("stopping", job_id))
                if force:
                    self._killed = True
            else:
                return False
        add_audit_entry("JOB_KILL" if force else "JOB_CANCEL", f"Job #{job_id}")
        return True

    def retry(self, job_id: int) -> int | None:
        """Create a new job from a failed or stopped job's saved snapshot."""
        with self._lock:
            with get_db() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] not in RETRY_STATUSES:
                return None
            new_id = self.enqueue(AppConfig.model_validate_json(row["config"]), "retry", json.loads(row["series_ids"]), json.loads(row["book_ids"] or "null"))
            add_audit_entry("JOB_RETRY", f"Job #{job_id} retried as #{new_id}")
            return new_id

    def _work(self) -> None:
        while not self._shutdown.is_set():
            try:
                if self._execute_next():
                    continue
            except Exception:
                logger.exception("Queue worker failed; pending jobs remain saved.")
            self._wake.wait(1)
            self._wake.clear()

    def _execute_next(self) -> bool:
        with self._lock:
            if self._shutdown.is_set():
                return False
            with get_db() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
                if not row:
                    return False
                job_id = row["id"]
                conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?", (_now(), job_id))
            self._active_id = job_id
            self._killed = False
            try:
                self._process = self._process_factory(
                    {
                        "config": json.loads(row["config"]),
                        "series_ids": json.loads(row["series_ids"]),
                        "book_ids": json.loads(row["book_ids"] or "null"),
                    }
                )
            except Exception:
                append_job_log(job_id, "ERROR", "Could not start the job worker. Check server resources before retrying.")
                logger.exception("Could not start job #%s.", job_id)
                self._finish(job_id, "failed")
                return True
            process = self._process
        append_job_log(job_id, "INFO", f"Starting job #{job_id} ({row['source']}).")
        logger.info("Starting job #%s (%s).", job_id, row["source"])
        try:
            for line in process.stdout:
                self._read_output(job_id, line)
            code = process.wait()
            with self._lock:
                with get_db() as conn:
                    status = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
                outcome = "succeeded" if code == 0 else "failed"
                if status == "stopping":
                    outcome = "killed" if self._killed else "cancelled"
                if self._shutdown.is_set():
                    outcome = "interrupted"
                self._finish(job_id, outcome)
        except Exception:
            process.kill()
            process.wait()
            with self._lock:
                self._finish(job_id, "failed")
            raise
        finally:
            process.stdout.close()
        return True

    def _finish(self, job_id: int, status: str) -> None:
        with get_db() as conn:
            conn.execute("UPDATE jobs SET status=?, finished_at=? WHERE id=?", (status, _now(), job_id))
        self._process = None
        self._active_id = None
        add_audit_entry("JOB_FINISHED", f"Job #{job_id}: {status}")
        append_job_log(job_id, "INFO", f"Job #{job_id}: {status}.")
        logger.info("Job #%s: %s.", job_id, status)

    def _read_output(self, job_id: int, line: str) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            append_job_log(job_id, "INFO", line.rstrip())
            logger.info("[Job #%s] %s", job_id, line.rstrip())
            return
        if isinstance(message, dict) and message.get("type") == "progress":
            with get_db() as conn:
                conn.execute(
                    "UPDATE jobs SET processed=?, failed=?, skipped=? WHERE id=?",
                    (message["processed"], message["failed"], message["skipped"], job_id),
                )
        elif isinstance(message, dict) and message.get("type") == "log":
            append_job_log(job_id, logging.getLevelName(message["level"]), message["message"])
            logger.log(message["level"], "[Job #%s] %s", job_id, message["message"])
        else:
            append_job_log(job_id, "INFO", line.rstrip())
            logger.info("[Job #%s] %s", job_id, line.rstrip())


_queue = JobQueue()


def get_job_queue() -> JobQueue:
    """Return the process-wide queue shared by the UI, scheduler, and watcher."""
    return _queue
