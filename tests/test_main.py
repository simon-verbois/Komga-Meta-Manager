from unittest.mock import Mock, patch

from modules.main import SHUTDOWN_EVENT, WatcherComponents, main, run_job_and_save_cache, run_once_mode
from modules.processor import ProcessingResult


def test_job_saves_translation_cache(app_config) -> None:
    translator = Mock()
    result = ProcessingResult(translator=translator)
    with patch("modules.main.run_workflow", return_value=result):
        assert run_job_and_save_cache(app_config) is result
    translator.save_cache_to_disk.assert_called_once()


def test_run_once_returns_result_status(app_config) -> None:
    with patch("modules.main.run_job_and_save_cache", return_value=ProcessingResult(success=True)):
        assert run_once_mode(app_config) == 0
    with patch("modules.main.run_job_and_save_cache", return_value=ProcessingResult(success=False)):
        assert run_once_mode(app_config) == 1


def test_main_idle_does_not_run_automatically(tmp_path, app_config) -> None:
    app_config.system.scheduler.enabled = False
    app_config.system.watcher.enabled = False

    def stop_waiting(*_):
        SHUTDOWN_EVENT.set()
        return True

    with (
        patch("modules.main.READINESS_FILE", tmp_path / "ready"),
        patch("modules.main.initialize_application", return_value=app_config),
        patch("modules.main.start_webui_thread"),
        patch("modules.main.run_once_mode") as run_once,
        patch("modules.main.CONFIG_RELOAD_EVENT.wait", side_effect=stop_waiting),
        patch("modules.main.signal.signal"),
    ):
        assert main() == 0
    run_once.assert_not_called()


def test_main_watcher_failure_keeps_ui_alive(tmp_path, app_config) -> None:
    app_config.system.scheduler.enabled = False
    app_config.system.watcher.enabled = True

    def stop_waiting(*_):
        SHUTDOWN_EVENT.set()
        return True

    with (
        patch("modules.main.READINESS_FILE", tmp_path / "ready"),
        patch("modules.main.initialize_application", return_value=app_config),
        patch("modules.main.start_webui_thread"),
        patch("modules.main.initialize_watcher", return_value=WatcherComponents()),
        patch("modules.main.CONFIG_RELOAD_EVENT.wait", side_effect=stop_waiting),
        patch("modules.main.signal.signal"),
    ):
        assert main() == 0


def test_main_scheduler_continues_without_failed_watcher(tmp_path, app_config) -> None:
    app_config.system.scheduler.enabled = True
    app_config.system.watcher.enabled = True
    scheduler = Mock()
    with (
        patch("modules.main.READINESS_FILE", tmp_path / "ready"),
        patch("modules.main.initialize_application", return_value=app_config),
        patch("modules.main.initialize_scheduler", return_value=scheduler),
        patch("modules.main.initialize_watcher", side_effect=RuntimeError("offline")),
        patch("modules.main.start_webui_thread"),
        patch("modules.main.run_continuous_loop", side_effect=lambda *_: SHUTDOWN_EVENT.set()) as loop,
        patch("modules.main.signal.signal"),
    ):
        assert main() == 0
    loop.assert_called_once()
    assert not (tmp_path / "ready").exists()


def test_main_hot_reload_starts_scheduler_without_automatic_job(tmp_path, app_config):
    from modules.main import CONFIG_RELOAD_EVENT

    initial = app_config.model_copy(deep=True)
    initial.system.scheduler.enabled = False
    initial.system.watcher.enabled = False
    updated = initial.model_copy(deep=True)
    updated.system.scheduler.enabled = True
    updated.system.scheduler.run_at = "22:45"

    def reload_config(*_):
        CONFIG_RELOAD_EVENT.set()
        return True

    with (
        patch("modules.main.READINESS_FILE", tmp_path / "ready"),
        patch("modules.main.initialize_application", return_value=initial),
        patch("modules.main.start_webui_thread"),
        patch("modules.main.signal.signal"),
        patch("modules.main.get_config", return_value=updated),
        patch("modules.main.CONFIG_RELOAD_EVENT.wait", side_effect=reload_config),
        patch("modules.main.initialize_scheduler", return_value=Mock()) as scheduler,
        patch("modules.main.initialize_watcher", return_value=WatcherComponents()),
        patch("modules.main.run_continuous_loop", side_effect=lambda *_: SHUTDOWN_EVENT.set()),
        patch("modules.main.run_job_and_save_cache") as job,
    ):
        assert main() == 0
    scheduler.assert_called_once_with(updated)
    job.assert_not_called()

def test_scheduler_queues_jobs_instead_of_processing_inline(app_config):
    from modules.main import initialize_scheduler

    app_config.system.scheduler.enabled = True
    with patch("modules.main.get_job_queue") as get_queue, patch("modules.main.run_workflow") as process:
        scheduler = initialize_scheduler(app_config)
        scheduler.run_job()
    get_queue.return_value.enqueue.assert_called_once()
    snapshot = get_queue.return_value.enqueue.call_args.args[0]
    assert get_queue.return_value.enqueue.call_args.kwargs == {"source": "scheduler"}
    # Automatic runs only fetch into KMM unless automatic publishing was allowed.
    assert snapshot.system.workflow == "collect"
    assert snapshot.system.dry_run is False
    assert snapshot.system.overwrite_local is False
    assert app_config.system.dry_run is True
    process.assert_not_called()


def test_scheduler_publishes_only_when_auto_publish_is_enabled(app_config):
    from modules.main import initialize_scheduler

    app_config.system.scheduler.enabled = True
    app_config.system.auto_publish = True
    with patch("modules.main.get_job_queue") as get_queue, patch("modules.main.run_workflow"):
        initialize_scheduler(app_config).run_job()
    snapshot = get_queue.return_value.enqueue.call_args.args[0]
    assert snapshot.system.workflow == "both"
    assert snapshot.system.dry_run is False


def test_startup_logs_are_plain_and_diagnostics_use_debug(caplog):
    import logging
    from modules.main import display_header

    with caplog.at_level(logging.DEBUG, logger="modules.main"):
        display_header()
    info = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    assert len(info) == 2
    assert info[0].startswith("Komga Meta Manager")
    assert info[1] == "Web UI available at http://0.0.0.0:8765"
    assert all(not record.getMessage().startswith(("|", "left:", "center:")) for record in caplog.records)
    assert any(record.levelno == logging.DEBUG and "Platform:" in record.getMessage() for record in caplog.records)
