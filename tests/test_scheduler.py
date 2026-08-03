import time
from unittest.mock import Mock

from modules.scheduler import Scheduler


def test_failed_watcher_poll_is_deferred(app_config) -> None:
    app_config.system.watcher.enabled = True
    scheduler = Scheduler(app_config, Mock())
    scheduler.state.last_watcher_poll = 0
    scheduler.run_watcher_poll(Mock(side_effect=RuntimeError("offline")))
    assert scheduler.state.last_watcher_poll > 0
    assert scheduler.calculate_watcher_wait_seconds() > 0


def test_missing_watcher_callback_disables_watcher(app_config) -> None:
    app_config.system.scheduler.enabled = True
    app_config.system.watcher.enabled = True
    scheduler = Scheduler(app_config, Mock())
    stop_event = Mock()
    stop_event.is_set.return_value = True
    scheduler.run(None, stop_event=stop_event)
    assert scheduler.watcher_enabled is False


def test_watcher_wait_never_truncates_positive_delay_to_zero(app_config) -> None:
    app_config.system.watcher.enabled = True
    app_config.system.watcher.polling_interval_minutes = 1
    scheduler = Scheduler(app_config, Mock())
    scheduler.state.last_watcher_poll = time.monotonic() - 59.5
    assert scheduler.calculate_watcher_wait_seconds() == 1

