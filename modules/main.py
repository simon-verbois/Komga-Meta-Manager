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
from pathlib import Path
from modules.config import load_config, AppConfig
from modules.processor import process_libraries, watch_for_new_series
from modules.komga_client import KomgaClient
from modules.providers import get_provider
from modules.translators import get_translator
from modules.utils import FrameFormatter, log_frame

logger = logging.getLogger(__name__)

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

def initialize_watcher_series(komga_client: 'KomgaClient', target_libraries: dict) -> dict:
    """
    Initialize the known series for the watcher.
    Returns a dict mapping lib_id to set of series_ids.
    """
    known_series = {}
    logging.info("|                                                                                                    |")
    logging.info("|====================================================================================================|")
    log_frame("Watcher", 'center')
    logging.info("|====================================================================================================|")
    logger.info("Initializing watcher: scanning existing series...")
    for lib_name, lib_id in target_libraries.items():
        series_list = komga_client.get_series_in_library(lib_id, lib_name)
        known_series[lib_id] = {s.id for s in series_list}
        logger.info(f"Initialized {len(known_series[lib_id])} series for library '{lib_name}'")
    logger.info("Watcher initialization complete.")
    return known_series

def main():
    """Main function to run the Manga Manager."""
    try:
        app_config = load_config()
        setup_logging(app_config.system.debug)
        display_header()
        log_frame("Configuration loaded successfully.", 'left')
        if app_config.system.dry_run:
            logging.warning("Dry-run mode is enabled. No changes will be made to Komga.")

        # Determine if we need continuous running (scheduler or watcher)
        continuous_mode = app_config.system.scheduler.enabled or app_config.system.watcher.enabled

        if not continuous_mode:
            # "Run once" mode
            logging.info("Scheduler and watcher disabled. Running the job once.")
            run_job_and_save_cache(config=app_config)
            logging.info("|                                                                                                    |")
            logging.info("|====================================================================================================|")
            log_frame("Komga Meta Manager Finished", 'center')
            logging.info("|====================================================================================================|")
            return

        # Continuous mode: setup scheduler and/or watcher
        komga_client = None
        metadata_provider = None
        translator = None
        known_series = None
        target_libraries = None
        last_poll_time = 0

        if app_config.system.scheduler.enabled:
            run_time = app_config.system.scheduler.run_at
            logging.info(f"Scheduler is enabled. Job will run every day at {run_time}.")
            schedule.every().day.at(run_time).do(run_job_and_save_cache, config=app_config)
            next_run = get_next_run_time()
            if next_run:
                 logging.info(f"Initial next scheduled run at: {next_run}")

        if app_config.system.watcher.enabled:
            logging.info("Watcher is enabled. New series will be processed automatically.")
            # Initialize components for watcher (only once)
            cache_dir = Path("/config/cache")
            cache_dir.mkdir(exist_ok=True)

            metadata_provider = get_provider(app_config.provider, cache_dir)
            if not metadata_provider:
                logging.error("Failed to initialize provider for watcher. Watcher will be disabled.")
            else:
                if app_config.translation and app_config.translation.enabled:
                    translator_provider = app_config.translation.provider.lower()
                    translator_kwargs = {}
                    if translator_provider == 'deepl':
                        if app_config.translation.deepl:
                            translator_kwargs['config'] = app_config.translation.deepl
                        else:
                            logging.error("DeepL provider selected but config missing.")
                            translator_provider = None
                    if translator_provider:
                        translator = get_translator(translator_provider, **translator_kwargs)
                        if translator:
                            logger.info("Watcher translation initialized.")
                        else:
                            logger.error("Failed to initialize translator for watcher.")

                komga_client = KomgaClient(app_config.komga)
                # Get target libraries for watcher initialization
                all_libraries = komga_client.get_libraries()
                if not all_libraries:
                    logging.error("Could not retrieve libraries from Komga for watcher initialization. Aborting watcher.")
                    return
                target_libraries = {lib.name: lib.id for lib in all_libraries if lib.name in app_config.komga.libraries}
                if not target_libraries:
                    logging.warning("No matching libraries found for watcher. Watcher will be disabled.")
                else:
                    known_series = initialize_watcher_series(komga_client, target_libraries)
                    logging.info(f"Next watcher poll in {app_config.system.watcher.polling_interval_minutes} minutes.")

                    # Perform immediate first check to catch any series added during initialization
                    logger.info("Watcher: Performing initial series check...")
                    has_processed = watch_for_new_series(app_config, komga_client, target_libraries, known_series, metadata_provider, translator)
                    last_poll_time = time.time()  # Set after first check
                    if has_processed:
                        logging.info("|                                                                                                    |")
                        logging.info("|====================================================================================================|")
                        log_frame("Watcher", 'center')
                        logging.info("|====================================================================================================|")
                        logger.info(f"Watcher: Monitoring resumed, next check in {app_config.system.watcher.polling_interval_minutes} minutes.")

        # Main continuous loop
        try:
            while True:
                schedule.run_pending()

                # Check for watcher polling
                if app_config.system.watcher.enabled and known_series is not None:
                    current_time = time.time()
                    poll_interval = app_config.system.watcher.polling_interval_minutes * 60
                    if current_time - last_poll_time >= poll_interval:
                        logger.debug("Watcher: Checking for new series...")
                        has_processed = watch_for_new_series(app_config, komga_client, target_libraries, known_series, metadata_provider, translator)
                        last_poll_time = current_time
                        if has_processed:
                            logging.info("|                                                                                                    |")
                            logging.info("|====================================================================================================|")
                            log_frame("Watcher", 'center')
                            logging.info("|====================================================================================================|")
                            logger.info(f"Watcher: Monitoring resumed, next check in {app_config.system.watcher.polling_interval_minutes} minutes.")

                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            logging.info("Shutdown signal received. Exiting gracefully.")

    except Exception as e:
        logging.error(f"A critical error occurred during setup: {e}", exc_info=True)

if __name__ == "__main__":
    main()
