from unittest.mock import Mock, patch

from modules.main import WatcherComponents, main, run_job_and_save_cache, run_once_mode
from modules.processor import ProcessingResult


def test_job_saves_translation_cache(app_config) -> None:
    translator = Mock()
    result = ProcessingResult(translator=translator)
    with patch("modules.main.process_libraries", return_value=result):
        assert run_job_and_save_cache(app_config) is result
    translator.save_cache_to_disk.assert_called_once()


def test_run_once_returns_result_status(app_config) -> None:
    with patch("modules.main.run_job_and_save_cache", return_value=ProcessingResult(success=True)):
        assert run_once_mode(app_config) == 0
    with patch("modules.main.run_job_and_save_cache", return_value=ProcessingResult(success=False)):
        assert run_once_mode(app_config) == 1


def test_main_run_once_propagates_success(tmp_path, app_config) -> None:
    app_config.system.scheduler.enabled = False
    app_config.system.watcher.enabled = False
    with (
        patch("modules.main.READINESS_FILE", tmp_path / "ready"),
        patch("modules.main.initialize_application", return_value=app_config),
        patch("modules.main.run_once_mode", return_value=0),
        patch("modules.main.signal.signal"),
    ):
        assert main() == 0


def test_main_watcher_only_initialization_failure_returns_error(tmp_path, app_config) -> None:
    app_config.system.scheduler.enabled = False
    app_config.system.watcher.enabled = True
    with (
        patch("modules.main.READINESS_FILE", tmp_path / "ready"),
        patch("modules.main.initialize_application", return_value=app_config),
        patch("modules.main.initialize_watcher", return_value=WatcherComponents()),
        patch("modules.main.signal.signal"),
    ):
        assert main() == 1


def test_main_scheduler_continues_without_failed_watcher(tmp_path, app_config) -> None:
    app_config.system.scheduler.enabled = True
    app_config.system.watcher.enabled = True
    scheduler = Mock()
    with (
        patch("modules.main.READINESS_FILE", tmp_path / "ready"),
        patch("modules.main.initialize_application", return_value=app_config),
        patch("modules.main.initialize_scheduler", return_value=scheduler),
        patch("modules.main.initialize_watcher", side_effect=RuntimeError("offline")),
        patch("modules.main.run_continuous_loop") as loop,
        patch("modules.main.signal.signal"),
    ):
        assert main() == 0
    loop.assert_called_once()
    assert not (tmp_path / "ready").exists()
