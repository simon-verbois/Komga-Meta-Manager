# -*- coding: utf-8 -*-
"""
Main entry point for the Komga Meta Manager.

Startup sequence:
  1. Init database (SQLite at /config/webui.db)
  2. Install execution log buffer handler
  3. Load config from DB (may be None on first run)
  4. Setup logging level
  5. Start Web UI server in a daemon thread (port 8765)
  6. If config is ready: start scheduler / watcher as before
  7. Block on the continuous loop (or wait for config via Web UI)
"""
import logging
import os
import platform
import signal
import threading
import time
import psutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from modules.webui import log_buffer as _log_buffer
from modules.webui.routes.dashboard import get_job_state

from modules.webui.db import init_db
from modules.webui.config_store import (
    load_config_from_db,
    get_config,
)
from modules.config import AppConfig
from modules.processor import ProcessingResult, process_libraries, watch_for_new_series
from modules.komga_client import KomgaClient
from modules.providers import get_providers
from modules.translators import get_translator
from modules.scheduler import Scheduler
from modules.utils import FrameFormatter, log_frame
from modules.version import get_version

PROCESSING_LOCK = threading.RLock()
logger = logging.getLogger(__name__)
READINESS_FILE = Path("/tmp/kmm-ready")
SHUTDOWN_EVENT = threading.Event()
# Fired when a config reload should restart scheduler/watcher
CONFIG_RELOAD_EVENT = threading.Event()


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(debug: bool = False) -> None:
    """Configures the root logger and installs the Web UI buffer handler."""
    level = logging.DEBUG if debug else logging.INFO
    if debug:
        formatter = FrameFormatter(
            '%(asctime)s [%(filename)s:%(lineno)d] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
    else:
        formatter = FrameFormatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
    logging.getLogger().setLevel(level)
    logging.basicConfig(
        level=level,
        handlers=[logging.StreamHandler()],
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    handler = logging.getLogger().handlers[0]
    handler.setFormatter(formatter)

    # Install the Web UI circular buffer handler
    _log_buffer.install_handler()

    if not debug:
        logging.getLogger("gql").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.INFO)
        logging.getLogger("deepl").setLevel(logging.WARNING)
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("fastapi").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Header display
# ---------------------------------------------------------------------------

def display_header() -> None:
    """Displays ASCII header information in log format."""
    version = get_version()

    docker_str = ' (Docker)' if os.path.exists('/.dockerenv') else ''
    platform_str = platform.platform()

    try:
        total_mem = int(psutil.virtual_memory().total / (1024 ** 3))
        avail_mem = int(psutil.virtual_memory().available / (1024 ** 3))
        nice = psutil.Process().nice()
        prio_str = 'high' if nice < 0 else ('low' if nice > 0 else 'normal')
    except (ImportError, AttributeError):
        total_mem = avail_mem = 0
        prio_str = 'unknown'

    logging.info("|====================================================================================================|")
    logging.info("|                                                                                                    |")
    logging.info("|                         _  __                      __  __     _                                    |")
    logging.info(r"|                         | |/ /___ _ __  __ _ __ _  |  \/  |___| |_ __ _                            |")
    logging.info(r"|                         | ' \/ _ \ '  \/ _` / _` | | |\/| / -_)  _/ _` |                           |")
    logging.info(r"|                         |_|\_\___/_|_|_\__, \__,_| |_|  |_\___|\_\_\__,_|                           |")
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
    log_frame("Web UI available at http://0.0.0.0:8765", 'center')
    logging.info("|====================================================================================================|")


# ---------------------------------------------------------------------------
# Web UI server thread
# ---------------------------------------------------------------------------

def start_webui_thread(run_job_fn) -> threading.Thread:
    """Start the FastAPI/uvicorn server in a daemon thread."""
    from modules.webui.app import create_app
    import uvicorn

    def _reload_callback(new_cfg: AppConfig) -> None:
        """Called by config_store whenever the config is saved from the Web UI."""
        setup_logging(new_cfg.system.debug)
        logger.info("Config reloaded from Web UI — signalling restart.")
        CONFIG_RELOAD_EVENT.set()

    app = create_app(run_job_fn=run_job_fn, reload_callback=_reload_callback)

    def _serve():
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8765,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.run()

    t = threading.Thread(target=_serve, daemon=True, name="webui-server")
    t.start()
    logger.info("Web UI server started on port 8765.")
    return t


# ---------------------------------------------------------------------------
# Job helpers (unchanged from original)
# ---------------------------------------------------------------------------

def run_job_and_save_cache(config: AppConfig) -> ProcessingResult:
    """Wrapper that ensures the translator cache is saved after execution."""
    with PROCESSING_LOCK:
        state = get_job_state()
        state.start()
        result: Optional[ProcessingResult] = None
        try:
            result = process_libraries(config, stop_event=SHUTDOWN_EVENT)
            return result
        finally:
            try:
                translator = result.translator if result else None
                if translator and hasattr(translator, 'save_cache_to_disk'):
                    translator.save_cache_to_disk()
            finally:
                state.finish(bool(result and result.success))


def initialize_watcher_series(komga_client: 'KomgaClient', target_libraries: dict) -> dict:
    """Initialize the watcher: scan existing series in all target libraries."""
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


def initialize_scheduler(config: AppConfig) -> Optional[Scheduler]:
    """Initialize the scheduler if enabled. Returns Scheduler instance or None."""
    if not config.system.scheduler.enabled:
        return None

    run_time = config.system.scheduler.run_at
    logging.info(f"Scheduler is enabled. Job will run every day at {run_time}.")

    scheduler = Scheduler(config, run_job_and_save_cache)

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
    initialized: bool = False


def initialize_watcher(config: AppConfig) -> WatcherComponents:
    """Initialize the watcher if enabled. Returns WatcherComponents."""
    components = WatcherComponents()

    if not config.system.watcher.enabled or not config.komga.libraries:
        return components

    logging.info("Watcher is enabled. New series will be processed automatically.")

    cache_dir = Path("/config/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    components.metadata_provider = get_providers(config.providers, cache_dir)
    if not components.metadata_provider:
        logging.error("Failed to initialize provider for watcher. Watcher will be disabled.")
        return components

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
                return WatcherComponents()

    components.komga_client = KomgaClient(config.komga)
    all_libraries = components.komga_client.get_libraries()
    if not all_libraries:
        logging.error("Could not retrieve libraries from Komga for watcher initialization.")
        return WatcherComponents()

    components.target_libraries = {
        lib.name: lib.id for lib in all_libraries if lib.name in config.komga.libraries
    }
    if not components.target_libraries:
        logging.warning("No matching libraries found for watcher. Watcher will be disabled.")
        return WatcherComponents()

    components.known_series = initialize_watcher_series(
        components.komga_client, components.target_libraries
    )
    logging.info(f"Next watcher poll in {config.system.watcher.polling_interval_minutes} minutes.")

    logger.info("Watcher: Performing initial series check...")
    has_processed = _watch_exclusively(
        config, components.komga_client, components.target_libraries,
        components.known_series, components.metadata_provider, components.translator,
    )
    components.last_poll_time = time.monotonic()
    components.initialized = True

    if has_processed:
        logging.info("|                                                                                                    |")
        logging.info("|====================================================================================================|")
        log_frame("Watcher", 'center')
        logging.info("|====================================================================================================|")
        logger.info(f"Watcher: Monitoring resumed, next check in {config.system.watcher.polling_interval_minutes} minutes.")

    return components


def _watch_exclusively(*args, **kwargs):
    with PROCESSING_LOCK:
        return watch_for_new_series(*args, **kwargs)


def watcher_poll_function(config: AppConfig, watcher_components: WatcherComponents) -> bool:
    """Wrapper function for watcher polling."""
    if watcher_components.known_series is None:
        return False

    logger.debug("Watcher: Checking for new series...")
    has_processed = _watch_exclusively(
        config, watcher_components.komga_client,
        watcher_components.target_libraries, watcher_components.known_series,
        watcher_components.metadata_provider, watcher_components.translator,
    )

    if has_processed:
        logging.info("|                                                                                                    |")
        logging.info("|====================================================================================================|")
        log_frame("Watcher", 'center')
        logging.info("|====================================================================================================|")
        logger.info(f"Watcher: Monitoring resumed, next check in {config.system.watcher.polling_interval_minutes} minutes.")

    return has_processed


def run_continuous_loop(
    config: AppConfig,
    scheduler: Optional[Scheduler],
    watcher_components: WatcherComponents,
    stop_event: threading.Event,
) -> None:
    """Run the main continuous loop for scheduler and/or watcher."""
    try:
        if scheduler:
            watcher_func = None
            if config.system.watcher.enabled and watcher_components.initialized:
                def watcher_func():
                    return watcher_poll_function(config, watcher_components)

            scheduler.run(watcher_func, stop_event=stop_event)
        else:
            logger.info("Only watcher enabled, running in legacy mode.")
            while not stop_event.is_set():
                if (config.system.watcher.enabled and
                        watcher_components.known_series is not None):

                    current_time = time.monotonic()
                    poll_interval = config.system.watcher.polling_interval_minutes * 60
                    if current_time - watcher_components.last_poll_time >= poll_interval:
                        try:
                            watcher_poll_function(config, watcher_components)
                        except Exception as e:
                            logger.error(f"Watcher poll failed: {e}", exc_info=config.system.debug)
                        finally:
                            watcher_components.last_poll_time = time.monotonic()

                stop_event.wait(60)

    except KeyboardInterrupt:
        logging.info("Shutdown signal received. Exiting gracefully.")


def initialize_application() -> Optional[AppConfig]:
    """Initialize the application: load config, setup logging, display header."""
    init_db()
    app_config = load_config_from_db()
    debug = app_config.system.debug if app_config else False
    setup_logging(debug)
    display_header()
    if app_config:
        log_frame("Configuration loaded from database.", 'left')
        if app_config.system.dry_run:
            logging.warning("Dry-run mode is enabled. No changes will be made to Komga.")
    else:
        log_frame("No configuration found — complete setup at http://0.0.0.0:8765", 'left')
    return app_config


def run_once_mode(config: AppConfig) -> int:
    """Execute the application in run-once mode."""
    logging.info("Scheduler and watcher disabled. Running the job once.")
    result = run_job_and_save_cache(config=config)
    logging.info("|                                                                                                    |")
    logging.info("|====================================================================================================|")
    log_frame("Komga Meta Manager Finished", 'center')
    logging.info("|====================================================================================================|")
    return 0 if result.success else 1


# ---------------------------------------------------------------------------
# Wait for first config (when DB has no config yet)
# ---------------------------------------------------------------------------

def wait_for_config(stop_event: threading.Event) -> Optional[AppConfig]:
    """
    Block until the user completes the setup wizard and saves a config,
    or until a shutdown signal is received.
    """
    logger.info("No configuration found in database. Waiting for Web UI setup…")
    while not stop_event.is_set():
        cfg = get_config()
        if cfg is not None:
            logger.info("Configuration received from Web UI. Starting application.")
            return cfg
        stop_event.wait(0.5)
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Main function to run Komga Meta Manager with integrated Web UI."""
    try:
        READINESS_FILE.unlink(missing_ok=True)
        SHUTDOWN_EVENT.clear()
        CONFIG_RELOAD_EVENT.clear()

        app_config = initialize_application()

        # --- Signal handlers ---
        def request_shutdown(signum, _frame):
            logging.info(f"Shutdown signal {signum} received.")
            SHUTDOWN_EVENT.set()
            CONFIG_RELOAD_EVENT.set()

        signal.signal(signal.SIGTERM, request_shutdown)
        signal.signal(signal.SIGINT, request_shutdown)

        start_webui_thread(run_job_and_save_cache)

        # --- Wait for config if not yet configured ---
        if app_config is None:
            app_config = wait_for_config(SHUTDOWN_EVENT)
            if app_config is None:
                logger.info("Shutdown requested before setup was completed.")
                return 0
            setup_logging(app_config.system.debug)

        # --- Main application loop with hot-reload support ---
        while not SHUTDOWN_EVENT.is_set():
            CONFIG_RELOAD_EVENT.clear()

            continuous_mode = (
                app_config.system.scheduler.enabled or
                app_config.system.watcher.enabled
            )

            if not continuous_mode:
                logger.info("Scheduler and watcher disabled. Waiting for a manual run or configuration change.")
                while not SHUTDOWN_EVENT.is_set() and not CONFIG_RELOAD_EVENT.wait(0.5):
                    pass
                new_cfg = get_config()
                if new_cfg is not None:
                    app_config = new_cfg
                continue

            # --- Continuous mode ---
            scheduler = initialize_scheduler(app_config)
            try:
                watcher_components = initialize_watcher(app_config)
            except Exception as e:
                logging.error(f"Watcher initialization failed: {e}", exc_info=app_config.system.debug)
                watcher_components = WatcherComponents()

            if (app_config.system.watcher.enabled and
                    app_config.komga.libraries and
                    not watcher_components.initialized and
                    scheduler is None):
                logging.error("Watcher is the only enabled mode and could not initialize.")
                # Don't hard-exit — wait for config change via Web UI
                while not SHUTDOWN_EVENT.is_set() and not CONFIG_RELOAD_EVENT.wait(0.5):
                    pass
                if SHUTDOWN_EVENT.is_set():
                    break
                app_config = get_config()
                continue

            READINESS_FILE.write_text("ready\n", encoding="utf-8")
            try:
                loop_stop = threading.Event()

                def _listen_reload():
                    while not loop_stop.is_set():
                        if SHUTDOWN_EVENT.is_set() or CONFIG_RELOAD_EVENT.is_set():
                            loop_stop.set()
                            break
                        time.sleep(0.2)

                listen_thread = threading.Thread(target=_listen_reload, daemon=True)
                listen_thread.start()

                run_continuous_loop(app_config, scheduler, watcher_components, loop_stop)
                loop_stop.set()
            finally:
                READINESS_FILE.unlink(missing_ok=True)
                translator = watcher_components.translator
                if translator and hasattr(translator, 'save_cache_to_disk'):
                    watcher_components.translator.save_cache_to_disk()

            if SHUTDOWN_EVENT.is_set():
                break

            # Hot reload: grab the new config and restart
            new_cfg = get_config()
            if new_cfg is not None:
                app_config = new_cfg
                setup_logging(app_config.system.debug)
                logger.info("Hot reload: restarting with new configuration.")

        return 0

    except Exception as e:
        logging.error(f"A critical error occurred during setup: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
