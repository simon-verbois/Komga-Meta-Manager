# -*- coding: utf-8 -*-
"""
Optimized scheduler for Komga-Meta-Manager that calculates precise wait times
and sleeps exactly until the next execution, eliminating unnecessary polling.
"""
import logging
import time
from datetime import datetime, date, timedelta
from typing import Callable, Optional, Any
from dataclasses import dataclass

from .config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class SchedulerState:
    """Tracks the state of scheduler and watcher."""
    last_scheduler_run: Optional[date] = None
    last_watcher_poll: float = 0.0


class Scheduler:
    """Handles optimized scheduling and main processing loop."""

    def __init__(self, config: AppConfig, job_function: Callable[[AppConfig], Any]):
        self.config = config
        self.job_function = job_function
        self.start_hour, self.start_minute = self._parse_run_time(config.system.scheduler.run_at)
        self.state = SchedulerState()
        self.watcher_enabled = config.system.watcher.enabled
        if self.watcher_enabled:
            self.watcher_interval_seconds = config.system.watcher.polling_interval_minutes * 60

    def _parse_run_time(self, run_at: str) -> tuple[int, int]:
        """Parse HH:MM format into hour and minute integers."""
        hour, minute = map(int, run_at.split(':'))
        return hour, minute

    def should_run_job_now(self) -> bool:
        """Determine if the scheduled job should run at the current time."""
        now = datetime.now()

        if (now.hour > self.start_hour or
            (now.hour == self.start_hour and now.minute >= self.start_minute)) and \
           (self.state.last_scheduler_run is None or self.state.last_scheduler_run < now.date()):
            logger.info(f"Current time {now.hour}:{now.minute:02d} is after start time "
                       f"{self.start_hour}:{self.start_minute:02d}. Starting scheduled job...")
            self.state.last_scheduler_run = now.date()
            return True

        logger.debug(f"Scheduler check: current={now.hour}:{now.minute:02d}, "
                    f"start={self.start_hour}:{self.start_minute:02d}, last_run={self.state.last_scheduler_run}")
        return False

    def should_poll_watcher_now(self) -> bool:
        """Determine if the watcher should poll now."""
        if not self.watcher_enabled:
            return False

        current_time = time.time()
        return current_time - self.state.last_watcher_poll >= self.watcher_interval_seconds

    def calculate_job_wait_seconds(self) -> int:
        """Calculate seconds to wait until next scheduled job execution."""
        now = datetime.now()
        start_time_today = now.replace(hour=self.start_hour, minute=self.start_minute, second=0, microsecond=0)

        if now < start_time_today:
            # Wait until start time today
            wait_seconds = int((start_time_today - now).total_seconds())
        else:
            # Start time has passed today, wait until tomorrow
            tomorrow = now + timedelta(days=1)
            start_time_tomorrow = tomorrow.replace(hour=self.start_hour, minute=self.start_minute, second=0, microsecond=0)
            wait_seconds = int((start_time_tomorrow - now).total_seconds())

        return wait_seconds

    def calculate_watcher_wait_seconds(self) -> Optional[int]:
        """Calculate seconds to wait until next watcher poll."""
        if not self.watcher_enabled:
            return None

        current_time = time.time()
        time_since_last_poll = current_time - self.state.last_watcher_poll
        if time_since_last_poll >= self.watcher_interval_seconds:
            return 0  # Poll immediately

        wait_seconds = int(self.watcher_interval_seconds - time_since_last_poll)
        return wait_seconds

    def calculate_next_wait_seconds(self) -> tuple[int, bool, bool]:
        """
        Calculate the next wait time and what should happen after waking up.

        Returns:
            tuple: (wait_seconds, should_run_job, should_poll_watcher)
        """
        job_wait = self.calculate_job_wait_seconds()
        watcher_wait = self.calculate_watcher_wait_seconds()

        if watcher_wait is None:
            # Only scheduler
            return job_wait, True, False
        else:
            # Both scheduler and watcher - wait for the earliest event
            if job_wait <= watcher_wait:
                return job_wait, True, False
            else:
                return watcher_wait, False, True

    def run_job(self) -> None:
        """Execute the scheduled job."""
        try:
            self.job_function(self.config)
        except Exception as e:
            logger.error(f"An error occurred during scheduled job execution: {e}", exc_info=True)

    def run_watcher_poll(self, watcher_function: Callable[[], bool]) -> None:
        """Execute the watcher poll."""
        try:
            has_processed = watcher_function()
            self.state.last_watcher_poll = time.time()

            if has_processed:
                logger.info(f"Watcher: Monitoring resumed, next check in {self.config.system.watcher.polling_interval_minutes} minutes.")
        except Exception as e:
            logger.error(f"An error occurred during watcher poll: {e}", exc_info=True)

    def run(self, watcher_function: Optional[Callable[[], bool]] = None) -> None:
        """Main processing loop - waits precisely until next execution time."""
        logger.info("Starting optimized scheduler...")
        logger.debug(f"Scheduler configuration: run_at={self.start_hour}:{self.start_minute:02d}, "
                    f"watcher_enabled={self.watcher_enabled}")

        # Initialize watcher poll time if enabled
        if self.watcher_enabled:
            self.state.last_watcher_poll = time.time()
            logger.info(f"Watcher: Initial poll completed, next check in {self.config.system.watcher.polling_interval_minutes} minutes.")

        while True:
            # Calculate what to do next
            wait_seconds, should_run_job, should_poll_watcher = self.calculate_next_wait_seconds()

            if wait_seconds > 0:
                if should_run_job:
                    logger.info(f"Waiting for scheduled job at {self.start_hour}:{self.start_minute:02d} "
                               f"({wait_seconds} seconds)...")
                elif should_poll_watcher:
                    logger.info(f"Waiting for watcher poll ({wait_seconds} seconds)...")
                time.sleep(wait_seconds)

            # Execute scheduled job if it's time
            if should_run_job and self.should_run_job_now():
                self.run_job()

            # Execute watcher poll if it's time
            if should_poll_watcher and watcher_function is not None:
                self.run_watcher_poll(watcher_function)
