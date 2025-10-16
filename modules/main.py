# -*- coding: utf-8 -*-
"""
Main entry point for the Manga Manager application.
"""
import logging
import time
import schedule
from modules.config import load_config, AppConfig
from modules.processor import process_libraries
from modules.output import get_output_manager, OutputVerbosity, set_output_manager

def setup_logging(debug: bool = False):
    """Configures the root logger and output manager."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    if not debug:
        logging.getLogger("gql").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.INFO)
        logging.getLogger("schedule").setLevel(logging.INFO)
        logging.getLogger("deepl").setLevel(logging.WARNING)

    # Configure output manager
    output_manager = get_output_manager()
    if debug:
        output_manager.set_verbosity(OutputVerbosity.VERBOSE)
    else:
        output_manager.set_verbosity(OutputVerbosity.NORMAL)

def get_next_run_time():
    """
    Safely gets the next run time from the schedule library.
    """
    try:
        next_run_attr = schedule.next_run
        if callable(next_run_attr):
            return next_run_attr()
        return next_run_attr
    except Exception:
        return None

def run_job_and_save_cache(config: AppConfig):
    """
    Wrapper for the main job that ensures the translator cache is saved after execution.
    """
    output_manager = get_output_manager()
    translator_instance = None
    try:
        translator_instance = process_libraries(config)
    except Exception as e:
        output_manager.error(f"An unexpected error occurred during the scheduled run: {e}", "error")
        output_manager.debug(f"Exception: {e}")
    finally:
        if translator_instance and hasattr(translator_instance, 'save_cache_to_disk'):
            translator_instance.save_cache_to_disk()

def main():
    """Main function to run the Manga Manager."""
    output_manager = get_output_manager()

    try:
        app_config = load_config()
        setup_logging(app_config.system.debug)

        output_manager.success("Configuration loaded successfully.")

        if app_config.system.dry_run:
            output_manager.warning("Dry-run mode is enabled. No changes will be made to Komga.", "warning")

        if not app_config.system.scheduler.enabled:
            # "Run once" mode
            output_manager.info("Scheduler is disabled. Running the job once.")
            run_job_and_save_cache(config=app_config)
            output_manager.success("--- Komga Meta Manager Finished ---")
        else:
            # "Schedule" mode
            run_time = app_config.system.scheduler.run_at
            output_manager.info(f"Scheduler is enabled. Job will run every day at {run_time}.")

            # We pass the new wrapper function to the scheduler
            schedule.every().day.at(run_time).do(run_job_and_save_cache, config=app_config)

            next_run = get_next_run_time()
            if next_run:
                 output_manager.info(f"Initial next scheduled run at: {next_run}")

            # Main scheduling loop with graceful exit handling
            try:
                while True:
                    schedule.run_pending()
                    time.sleep(60)
            except KeyboardInterrupt:
                output_manager.info("Shutdown signal received. Exiting gracefully.")

    except Exception as e:
        output_manager.error(f"A critical error occurred during setup: {e}", "error")
        output_manager.debug(f"Setup exception: {e}")

if __name__ == "__main__":
    main()
