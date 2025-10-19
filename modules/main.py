# -*- coding: utf-8 -*-
"""
Main entry point for the Manga Manager application.
"""
import logging
import os
import platform
import time
import schedule
import psutil
from modules.config import load_config, AppConfig
from modules.processor import process_libraries
from modules.utils import FrameFormatter, log_frame

def display_header():
    """Displays header information in log format."""
    # Read version
    with open('VERSION', 'r') as f:
        version = f.read().strip()

    # Check Docker
    docker_str = ' (Docker)' if os.path.exists('/.dockerenv') else ''

    # Platform
    platform_str = platform.platform()

    # Memory
    total_mem = int(psutil.virtual_memory().total / (1024**3))  # GB
    avail_mem = int(psutil.virtual_memory().available / (1024**3))  # GB

    # Process priority
    nice = psutil.Process().nice()
    if nice < 0:
        prio_str = 'high'
    elif nice > 0:
        prio_str = 'low'
    else:
        prio_str = 'normal'

    logging.info("|====================================================================================================|")
    logging.info("|                                                                                                    |")
    logging.info("|                         _  __                      __  __     _                                    |")
    logging.info(r"|                         | |/ /___ _ __  __ _ __ _  |  \/  |___| |_ __ _                            |")
    logging.info(r"|                         | ' </ _ \ '  \/ _` / _` | | |\/| / -_)  _/ _` |                           |")
    logging.info(r"|                         |_|\_\___/_|_|_\__, \__,_| |_|  |_\___|\__\__,_|                           |")
    logging.info("|                                         |___/                                                      |")
    logging.info("|                                         M  A  N  A  G  E  R                                        |")
    logging.info("|                                                                                                    |")
    log_frame("Version: {}{}".format(version, docker_str), 'left')
    log_frame("Platform: {}".format(platform_str), 'left')
    log_frame("Total Memory: {} GB".format(total_mem), 'left')
    log_frame("Available Memory: {} GB".format(avail_mem), 'left')
    log_frame("Process Priority: {}".format(prio_str), 'left')
    logging.info("|                                                                                                    |")
    logging.info("|====================================================================================================|")
    log_frame("Global Configurations", 'center')
    logging.info("|====================================================================================================|")

def setup_logging(debug: bool = False):
    """Configures the root logger."""
    level = logging.DEBUG if debug else logging.INFO
    if debug:
        formatter = FrameFormatter(
            '%(asctime)s [%(filename)s:%(lineno)d] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        formatter = FrameFormatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    logging.basicConfig(
        level=level,
        handlers=[logging.StreamHandler()],
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Apply the formatter to the root logger's handler
    handler = logging.getLogger().handlers[0]
    handler.setFormatter(formatter)
    if not debug:
        logging.getLogger("gql").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.INFO)
        logging.getLogger("schedule").setLevel(logging.INFO)
        logging.getLogger("deepl").setLevel(logging.WARNING)

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
    translator_instance = None
    try:
        translator_instance = process_libraries(config)
    except Exception as e:
        logging.error(f"An unexpected error occurred during the scheduled run: {e}", exc_info=True)
    finally:
        if translator_instance and hasattr(translator_instance, 'save_cache_to_disk'):
            translator_instance.save_cache_to_disk()

def main():
    """Main function to run the Manga Manager."""
    try:
        app_config = load_config()
        setup_logging(app_config.system.debug)
        display_header()
        log_frame("Configuration loaded successfully.", 'left')
        if app_config.system.dry_run:
            logging.warning("Dry-run mode is enabled. No changes will be made to Komga.")

        if not app_config.system.scheduler.enabled:
            # "Run once" mode
            logging.info("Scheduler is disabled. Running the job once.")
            run_job_and_save_cache(config=app_config)
            logging.info("|                                                                                                    |")
            logging.info("|====================================================================================================|")
            log_frame("Komga Meta Manager Finished", 'center')
            logging.info("|====================================================================================================|")
        else:
            # "Schedule" mode
            run_time = app_config.system.scheduler.run_at
            logging.info(f"Scheduler is enabled. Job will run every day at {run_time}.")

            # We pass the new wrapper function to the scheduler
            schedule.every().day.at(run_time).do(run_job_and_save_cache, config=app_config)

            next_run = get_next_run_time()
            if next_run:
                 logging.info(f"Initial next scheduled run at: {next_run}")
            
            # Main scheduling loop with graceful exit handling
            try:
                while True:
                    schedule.run_pending()
                    time.sleep(60)
            except KeyboardInterrupt:
                logging.info("Shutdown signal received. Exiting gracefully.")

    except Exception as e:
        logging.error(f"A critical error occurred during setup: {e}", exc_info=True)

if __name__ == "__main__":
    main()
