# -*- coding: utf-8 -*-
"""
Main entry point for the Manga Manager application.
"""
import logging
import os
import platform
import time
import psutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from modules.config import load_config, AppConfig
from modules.processor import process_libraries, watch_for_new_series
from modules.komga_client import KomgaClient
from modules.providers import get_provider
from modules.translators import get_translator
from modules.scheduler import Scheduler
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

    # Memory and process info (optional)
    try:
        total_mem = int(psutil.virtual_memory().total / (1024**3))  # GB
        avail_mem = int(psutil.virtual_memory().available / (1024**3))  # GB

        nice = psutil.Process().nice()
        if nice < 0:
            prio_str = 'high'
        elif nice > 0:
            prio_str = 'low'
        else:
            prio_str = 'normal'
    except (ImportError, AttributeError):
        total_mem = avail_mem = 0
        prio_str = 'unknown'

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
        logging.getLogger("deepl").setLevel(logging.WARNING)

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

def initialize_application() -> AppConfig:
    """Initialize the application: load config, setup logging, display header."""
    app_config = load_config()
    setup_logging(app_config.system.debug)
    display_header()
    log_frame("Configuration loaded successfully.", 'left')
    if app_config.system.dry_run:
        logging.warning("Dry-run mode is enabled. No changes will be made to Komga.")
    return app_config

def run_once_mode(config: AppConfig):
    """Execute the application in run-once mode."""
    logging.info("Scheduler and watcher disabled. Running the job once.")
    run_job_and_save_cache(config=config)
    logging.info("|                                                                                                    |")
    logging.info("|====================================================================================================|")
    log_frame("Komga Meta Manager Finished", 'center')
    logging.info("|====================================================================================================|")

def initialize_scheduler(config: AppConfig) -> Optional[Scheduler]:
    """Initialize the scheduler if enabled. Returns Scheduler instance or None."""
    if not config.system.scheduler.enabled:
        return None

    run_time = config.system.scheduler.run_at
    logging.info(f"Scheduler is enabled. Job will run every day at {run_time}.")

    # Create the optimized scheduler
    scheduler = Scheduler(config, run_job_and_save_cache)

    # Calculate and log next run time
    next_wait = scheduler.calculate_job_wait_seconds()
    next_run_datetime = datetime.now() + timedelta(seconds=next_wait)
    logging.info(f"Initial next scheduled run at: {next_run_datetime}")

    return scheduler

@dataclass
class WatcherComponents:
    """Container for watcher-related components."""
    komga_client: Optional[KomgaClient] = None
    metadata_provider: Optional[object] = None
    translator: Optional[object] = None
    known_series: Optional[dict] = None
    target_libraries: Optional[dict] = None
    last_poll_time: float = 0

def initialize_watcher(config: AppConfig) -> WatcherComponents:
    """Initialize the watcher if enabled. Returns WatcherComponents."""
    components = WatcherComponents()

    if not config.system.watcher.enabled:
        return components

    logging.info("Watcher is enabled. New series will be processed automatically.")

    # Initialize components for watcher
    cache_dir = Path("/config/cache")
    cache_dir.mkdir(exist_ok=True)

    components.metadata_provider = get_provider(config.provider, cache_dir)
    if not components.metadata_provider:
        logging.error("Failed to initialize provider for watcher. Watcher will be disabled.")
        return components

    # Initialize translator for watcher
    if config.translation and config.translation.enabled:
        translator_provider = config.translation.provider.lower()
        translator_kwargs = {}
        if translator_provider == 'deepl':
            if config.translation.deepl:
                translator_kwargs['config'] = config.translation.deepl
            else:
                logging.error("DeepL provider selected but config missing.")
                translator_provider = None
        if translator_provider:
            components.translator = get_translator(translator_provider, **translator_kwargs)
            if components.translator:
                logger.info("Watcher translation initialized.")
            else:
                logger.error("Failed to initialize translator for watcher.")

    # Initialize Komga client and libraries
    components.komga_client = KomgaClient(config.komga)
    all_libraries = components.komga_client.get_libraries()
    if not all_libraries:
        logging.error("Could not retrieve libraries from Komga for watcher initialization. Aborting watcher.")
        return WatcherComponents()  # Return empty components

    components.target_libraries = {lib.name: lib.id for lib in all_libraries if lib.name in config.komga.libraries}
    if not components.target_libraries:
        logging.warning("No matching libraries found for watcher. Watcher will be disabled.")
        return WatcherComponents()  # Return empty components

    # Initialize known series
    components.known_series = initialize_watcher_series(components.komga_client, components.target_libraries)
    logging.info(f"Next watcher poll in {config.system.watcher.polling_interval_minutes} minutes.")

    # Perform immediate first check
    logger.info("Watcher: Performing initial series check...")
    has_processed = watch_for_new_series(
        config, components.komga_client, components.target_libraries,
        components.known_series, components.metadata_provider, components.translator
    )
    components.last_poll_time = time.time()  # Set after first check

    if has_processed:
        logging.info("|                                                                                                    |")
        logging.info("|====================================================================================================|")
        log_frame("Watcher", 'center')
        logging.info("|====================================================================================================|")
        logger.info(f"Watcher: Monitoring resumed, next check in {config.system.watcher.polling_interval_minutes} minutes.")

    return components

def watcher_poll_function(config: AppConfig, watcher_components: WatcherComponents) -> bool:
    """Wrapper function for watcher polling that returns whether processing occurred."""
    if not watcher_components.known_series:
        return False

    logger.debug("Watcher: Checking for new series...")
    has_processed = watch_for_new_series(
        config, watcher_components.komga_client,
        watcher_components.target_libraries, watcher_components.known_series,
        watcher_components.metadata_provider, watcher_components.translator
    )

    if has_processed:
        logging.info("|                                                                                                    |")
        logging.info("|====================================================================================================|")
        log_frame("Watcher", 'center')
        logging.info("|====================================================================================================|")
        logger.info(f"Watcher: Monitoring resumed, next check in {config.system.watcher.polling_interval_minutes} minutes.")

    return has_processed

def run_continuous_loop(config: AppConfig, scheduler: Optional[Scheduler], watcher_components: WatcherComponents):
    """Run the main continuous loop for scheduler and/or watcher."""
    try:
        if scheduler:
            # Use the optimized scheduler that handles both scheduler and watcher
            watcher_func = None
            if config.system.watcher.enabled and watcher_components.known_series:
                watcher_func = lambda: watcher_poll_function(config, watcher_components)

            scheduler.run(watcher_func)
        else:
            # Fallback: only watcher enabled, no scheduler
            logger.info("Only watcher enabled, running in legacy mode.")
            while True:
                if (config.system.watcher.enabled and
                    watcher_components.known_series is not None):

                    current_time = time.time()
                    poll_interval = config.system.watcher.polling_interval_minutes * 60
                    if current_time - watcher_components.last_poll_time >= poll_interval:
                        watcher_poll_function(config, watcher_components)
                        watcher_components.last_poll_time = current_time

                time.sleep(60)  # Check every minute

    except KeyboardInterrupt:
        logging.info("Shutdown signal received. Exiting gracefully.")

def main():
    """Main function to run the Manga Manager."""
    try:
        app_config = initialize_application()

        # Determine if we need continuous running (scheduler or watcher)
        continuous_mode = app_config.system.scheduler.enabled or app_config.system.watcher.enabled

        if not continuous_mode:
            run_once_mode(app_config)
            return

        # Continuous mode: setup scheduler and watcher
        scheduler = initialize_scheduler(app_config)
        watcher_components = initialize_watcher(app_config)

        # Run the continuous loop
        run_continuous_loop(app_config, scheduler, watcher_components)

    except Exception as e:
        logging.error(f"A critical error occurred during setup: {e}", exc_info=True)

if __name__ == "__main__":
    main()
