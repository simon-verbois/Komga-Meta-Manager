"""Queue lifecycle tests use real children without contacting Komga."""

import json
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from modules.job_queue import JobQueue, QueueFullError, launch_worker
from modules.webui import db, log_buffer


@pytest.fixture
def queue_db(tmp_path):
    db.init_db(tmp_path / "queue.db")
    return db.DB_PATH


def wait_for(queue, job_id, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = next(j for j in queue.snapshot()["jobs"] if j["id"] == job_id)
        if predicate(job):
            return job
        time.sleep(0.01)
    raise AssertionError(queue.snapshot())


def child_factory(program):
    def launch(payload):
        return subprocess.Popen(
            [sys.executable, "-u", "-c", program],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    return launch


PROGRESS = 'print(\'{"type":"progress","processed":1,"failed":0,"skipped":0}\', flush=True)'


def test_fifo_serial_execution_and_snapshots(queue_db, app_config):
    launches = []
    process_factory = child_factory("import time; " + PROGRESS + "; time.sleep(0.2)")

    def launch(payload):
        launches.append(payload)
        return process_factory(payload)

    queue = JobQueue(launch)
    first = queue.enqueue(app_config)
    app_config.system.dry_run = False
    second = queue.enqueue(app_config, "scheduler")
    app_config.komga.libraries = ["Changed afterwards"]
    queue.start()
    try:
        wait_for(queue, first, lambda j: j["processed"] == 1)
        assert len(launches) == 1
        assert next(j for j in queue.snapshot()["jobs"] if j["id"] == second)["status"] == "queued"
        wait_for(queue, second, lambda j: j["status"] == "succeeded")
        assert [p["config"]["system"]["dry_run"] for p in launches] == [True, False]
        assert all(p["config"]["komga"]["libraries"] == ["Manga"] for p in launches)
        first_job = next(j for j in queue.snapshot()["jobs"] if j["id"] == first)
        assert first_job["finished_at"]
        assert first_job["processed"] == 1
    finally:
        queue.close()


def test_cancel_queued_job_never_starts_and_retry_uses_original_snapshot(queue_db, app_config):
    launch = Mock(side_effect=AssertionError("Cancelled job must not launch"))
    queue = JobQueue(launch)
    job_id = queue.enqueue(app_config, "watcher", ["series-1"])
    assert queue.cancel(job_id)
    assert not queue.cancel(job_id)
    assert not queue.cancel(job_id, force=True)
    assert queue._execute_next() is False
    launch.assert_not_called()
    app_config.komga.libraries = ["Other"]
    retried = queue.retry(job_id)
    pending = next(j for j in queue.snapshot()["jobs"] if j["id"] == retried)
    assert pending["libraries"] == ["Manga"]
    assert pending["series_count"] == 1
    assert pending["source"] == "retry"
    assert pending["dry_run"] is True
    assert queue.retry(retried) is None
    assert queue.retry(999) is None
    assert not queue.cancel(999)


def test_graceful_stop_waits_for_worker_and_advances_queue(queue_db, app_config):
    program = (
        "import signal, time\n"
        "stopped = False\n"
        "def stop(*args):\n    global stopped\n    stopped = True\n"
        "signal.signal(signal.SIGTERM, stop)\n" + PROGRESS + "\n"
        "while not stopped:\n    time.sleep(0.01)\n"
        "time.sleep(0.1)\n"
    )
    queue = JobQueue(child_factory(program))
    job_id = queue.enqueue(app_config)
    pending = queue.enqueue(app_config)
    queue.start()
    try:
        wait_for(queue, job_id, lambda j: j["processed"] == 1)
        assert queue.cancel(job_id)
        assert next(j for j in queue.snapshot()["jobs"] if j["id"] == job_id)["status"] == "stopping"
        assert not queue.cancel(job_id)
        wait_for(queue, job_id, lambda j: j["status"] == "cancelled")
        wait_for(queue, pending, lambda j: j["processed"] == 1)
        assert queue.cancel(pending, force=True)
        wait_for(queue, pending, lambda j: j["status"] == "killed")
    finally:
        queue.close()


def test_force_stop_kills_unresponsive_child_and_retains_partial_progress(queue_db, app_config):
    queue = JobQueue(
        child_factory(
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); " + PROGRESS + "; time.sleep(60)",
        )
    )
    job_id = queue.enqueue(app_config)
    queue.start()
    try:
        wait_for(queue, job_id, lambda j: j["processed"] == 1)
        assert queue.cancel(job_id)
        assert queue.snapshot()["running"]
        assert queue.cancel(job_id, force=True)
        job = wait_for(queue, job_id, lambda j: j["status"] == "killed")
        assert job["processed"] == 1
        assert not queue.snapshot()["running"]
    finally:
        queue.close()


def test_spawn_failure_and_nonzero_exit_do_not_block_following_jobs(queue_db, app_config):
    calls = 0

    def launch(payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("Cannot launch")
        return child_factory("raise SystemExit(1 if " + str(calls) + " == 2 else 0)")(payload)

    queue = JobQueue(launch)
    ids = [queue.enqueue(app_config) for _ in range(3)]
    queue.start()
    try:
        wait_for(queue, ids[-1], lambda j: j["status"] == "succeeded")
        outcomes = {j["id"]: j["status"] for j in queue.snapshot()["jobs"]}
        assert [outcomes[i] for i in ids] == ["failed", "failed", "succeeded"]
    finally:
        queue.close()


def test_restart_marks_running_interrupted_and_keeps_queued_snapshot(queue_db, app_config):
    queue = JobQueue()
    interrupted = queue.enqueue(app_config)
    pending = queue.enqueue(app_config)
    with db.get_db() as conn:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (interrupted,))
    resumed = JobQueue(child_factory("pass"))
    resumed.start()
    try:
        wait_for(resumed, pending, lambda j: j["status"] == "succeeded")
        job = next(j for j in resumed.snapshot()["jobs"] if j["id"] == interrupted)
        assert job["status"] == "interrupted"
        assert job["finished_at"]
    finally:
        resumed.close()


def test_shutdown_leaves_waiting_jobs_persistent(queue_db, app_config):
    queue = JobQueue(child_factory("import time; " + PROGRESS + "; time.sleep(60)"))
    active = queue.enqueue(app_config)
    pending = queue.enqueue(app_config)
    queue.start()
    wait_for(queue, active, lambda j: j["processed"] == 1)
    queue.close()
    jobs = {j["id"]: j for j in JobQueue().snapshot()["jobs"]}
    assert jobs[active]["status"] == "interrupted"
    assert jobs[pending]["status"] == "queued"


def test_concurrent_enqueue_and_cancel_are_atomic(queue_db, app_config):
    queue = JobQueue()
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: queue.enqueue(app_config), range(20)))
        cancelled = list(pool.map(queue.cancel, [ids[0]] * 8))
    assert len(set(ids)) == 20
    assert sum(cancelled) == 1
    assert queue.snapshot()["pending"] == 19


def test_queue_capacity_and_empty_scope(queue_db, app_config, monkeypatch):
    monkeypatch.setattr("modules.job_queue.MAX_PENDING", 1)
    queue = JobQueue()
    first = queue.enqueue(app_config)
    with pytest.raises(QueueFullError):
        queue.enqueue(app_config)
    queue.cancel(first)
    assert queue.enqueue(app_config) > first
    app_config.komga.libraries = []
    with pytest.raises(ValueError, match="No libraries enabled"):
        queue.enqueue(app_config)


def test_snapshot_keeps_secrets_private_and_limits_history(queue_db, app_config):
    queue = JobQueue()
    for _ in range(25):
        queue.cancel(queue.enqueue(app_config))
    pending = queue.enqueue(app_config)
    snapshot = queue.snapshot()
    assert len(snapshot["jobs"]) == 21
    assert snapshot["jobs"][0]["id"] == pending
    assert "secret" not in json.dumps(snapshot)
    assert "config" not in snapshot["jobs"][0]


def test_worker_launches_with_stdin_snapshot_and_no_network(app_config):
    app_config.komga.libraries = []
    process = launch_worker({"config": app_config.model_dump(mode="json"), "series_ids": None})
    try:
        output = process.stdout.read()
        assert process.wait(timeout=5) == 0
        assert '"type": "progress"' in output
        events = [json.loads(line) for line in output.splitlines()]
        logs = [event for event in events if event["type"] == "log"]
        assert any(event["message"] == "No libraries enabled. Nothing to process." and event["level"] == logging.INFO for event in logs)
        assert any(event["level"] == logging.DEBUG and "enabled libraries" in event["message"] for event in logs)
        assert app_config.komga.api_key not in str(process.args)
        assert app_config.komga.api_key not in output
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def test_worker_logs_are_visible_with_job_number(queue_db, app_config, caplog):
    caplog.set_level(logging.DEBUG, logger="modules")
    queue = JobQueue(child_factory(
        'print(\'{"type":"log","level":30,"message":"Example warning"}\'); '
        'print(\'{"type":"log","level":10,"message":"Example debug"}\')'
    ))
    handler = log_buffer.install_handler()
    log_buffer.clear_buffer()
    job_id = queue.enqueue(app_config)
    queue.start()
    try:
        wait_for(queue, job_id, lambda j: j["status"] == "succeeded")
        assert any(f"[Job #{job_id}] Example warning" in line["msg"] for line in log_buffer.get_lines())
        assert any(f"[Job #{job_id}] Example debug" in line["msg"] for line in log_buffer.get_lines(levels=["DEBUG"]))
        assert not any("Example debug" in line["msg"] for line in log_buffer.get_lines())
    finally:
        queue.close()
        logging.getLogger().removeHandler(handler)


def test_snapshot_does_not_duplicate_a_job_finishing_between_queries(queue_db, app_config, monkeypatch):
    from contextlib import contextmanager

    queue = JobQueue()
    job_id = queue.enqueue(app_config)

    class ConnectionProxy:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, *args):
            if sql.startswith("SELECT * FROM jobs WHERE status NOT IN"):
                with db.get_db() as writer:
                    writer.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (job_id,))
            return self.connection.execute(sql, *args)

    @contextmanager
    def racing_connection():
        with db.get_db() as conn:
            yield ConnectionProxy(conn)

    monkeypatch.setattr("modules.job_queue.get_db", racing_connection)
    snapshot = queue.snapshot()
    assert len(snapshot["jobs"]) == 1
    assert snapshot["jobs"][0]["id"] == job_id
