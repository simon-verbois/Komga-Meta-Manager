# -*- coding: utf-8 -*-
"""
Minimal i18n system.

Usage in Jinja2 templates:
    {{ t('nav.dashboard') }}

To add a new language, add a key to TRANSLATIONS and use a translator
bound to that locale. English remains the default and fallback.
"""
from typing import Callable

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "common.configure": "Configure →",
        "common.general": "General",
        "nav.tools": "Tools",
        "account.title": "Change Password",
        "account.current": "Current Password",
        "account.new": "New Password",
        "account.confirm": "Confirm New Password",
        "account.submit": "Update Password",
        "account.success": "Password updated successfully.",
        "account.error.current": "Current password is incorrect.",
        "account.error.short": "New password must be at least 8 characters.",
        "account.error.match": "New passwords do not match.",
        "account.error.long": "Password must be at most 72 UTF-8 bytes.",
        "dashboard.controls": "Manual Controls",
        "dashboard.libraries": "Libraries",
        "dashboard.libraries.none": "None enabled",
        "dashboard.url": "URL",
        "dashboard.scheduler.error": "Invalid scheduler settings. Enter a time in HH:MM format.",
        "config.translation.google": "Google Translate (free)",
        "config.translation.language.help": "DeepL: use EN-US / EN-GB. Google: use en.",
        "config.processing.remove.help": "These operations are destructive and take priority over update fields.",
        "config.processing.exclude.placeholder": "My Excluded Series",
        "setup.password.placeholder": "Min. 8 characters",
        "setup.confirm.placeholder": "Repeat password",
        "logs.audit.previous": "← Prev",
        "logs.audit.next": "Next →",
        "logs.audit.page": "Page {page} / {total}",
        "field.summary": "Summary",
        "field.publisher": "Publisher",
        "field.genres": "Genres",
        "field.status": "Status",
        "field.cover_image": "Cover Image",
        "field.link": "Provider Links",
        "field.writers": "Authors: Writers",
        "field.pencillers": "Authors: Pencillers",
        "field.score": "Tags: Score",
        "field.language": "Language",
        "field.reading_direction": "Reading Direction",
        "dashboard.scheduler.daily": "Runs daily at {time}",
        "dashboard.no_config": "No configuration",
        # Navigation
        "nav.dashboard": "Dashboard",
        "nav.config": "Configuration",
        "nav.logs": "Logs",
        "nav.logout": "Logout",
        # Setup
        "setup.title": "Welcome to Komga Meta Manager",
        "setup.subtitle": "Create your administrator account to get started.",
        "setup.username": "Username",
        "setup.password": "Password",
        "setup.password_confirm": "Confirm Password",
        "setup.submit": "Create Account & Continue",
        "setup.error.match": "Passwords do not match.",
        "setup.error.short": "Password must be at least 8 characters.",
        "setup.error.username_empty": "Username cannot be empty.",
        # Login
        "login.title": "Sign In",
        "login.username": "Username",
        "login.password": "Password",
        "login.submit": "Sign In",
        "login.error": "Invalid username or password.",
        # Dashboard
        "dashboard.title": "Dashboard",
        "dashboard.scheduler.title": "Scheduler",
        "dashboard.scheduler.enabled": "Enabled",
        "dashboard.scheduler.disabled": "Disabled",
        "dashboard.scheduler.next_run": "Next run",
        "dashboard.watcher.title": "Watcher",
        "dashboard.watcher.interval": "Polls every {n} min",
        "dashboard.dry_run.title": "Dry-Run Mode",
        "dashboard.dry_run.on": "ON — no changes written",
        "dashboard.dry_run.off": "OFF — changes WILL be written",
        "dashboard.dry_run.toggle": "Toggle Dry-Run",
        "dashboard.dry_run.execute": "Dry Run",
        "setup.error.long": "Password must be at most 72 UTF-8 bytes.",
        "dashboard.run_now": "Run Now",
        "dashboard.run_now.running": "Running…",
        "dashboard.status.idle": "Idle",
        "dashboard.status.running": "Running",
        "dashboard.status.last_run": "Last run",
        "dashboard.status.success": "Success",
        "dashboard.status.failed": "Failed",
        # Config sections
        "config.title": "Configuration",
        "config.nav.system": "System",
        "config.nav.komga": "Komga",
        "config.nav.providers": "Providers",
        "config.nav.processing": "Processing",
        "config.nav.translation": "Translation",
        "config.save": "Save",
        "config.saved": "Configuration saved.",
        "config.error": "Validation error — see details below.",
        # System config
        "config.system.dry_run": "Dry-Run Mode",
        "config.system.dry_run.help": "Simulate changes without writing to Komga.",
        "config.system.debug": "Debug Logging",
        "config.system.debug.help": "Enable verbose log output.",
        "config.system.scheduler": "Scheduler",
        "config.system.scheduler.enabled": "Enable daily scheduler",
        "config.system.scheduler.run_at": "Run at (HH:MM)",
        "config.system.watcher": "Watcher",
        "config.system.watcher.enabled": "Enable new-series watcher",
        "config.system.watcher.interval": "Polling interval (minutes)",
        # Komga config
        "config.komga.url": "Komga URL",
        "config.komga.api_key": "API Key",
        "config.komga.libraries": "Libraries",
        "config.komga.libraries.help": "Only checked libraries can be modified by manual runs, the scheduler and the watcher. New libraries are disabled by default. Save to apply your choices; uncheck all to disable processing.",
        "config.komga.libraries.refresh": "Refresh libraries",
        "config.komga.libraries.connection": "Enter the Komga URL and API key to load libraries automatically.",
        "config.komga.libraries.loading": "Loading libraries from Komga…",
        "config.komga.libraries.loaded": "Libraries loaded. Save to apply your selection.",
        "config.komga.libraries.empty": "Komga returned no libraries.",
        "config.komga.libraries.error": "Could not load libraries. Check the URL, API key and SSL settings, then retry. Your selection has been kept.",
        "config.komga.libraries.unavailable": "Unavailable on Komga",
        "config.komga.libraries.javascript": "Enable JavaScript to discover libraries from Komga.",
        "config.komga.verify_ssl": "Verify SSL",
        # Providers config
        "config.providers.priority": "Priority",
        "config.providers.min_score": "Min. Match Score",
        "config.providers.allow_adult": "Allow Adult",
        "config.providers.language": "Preferred Language",
        "config.providers.cache_ttl": "Cache TTL (hours)",
        # Processing config
        "config.processing.overwrite": "Overwrite Existing",
        "config.processing.force_unlock": "Force Unlock",
        "config.processing.exclude": "Excluded Series",
        "config.processing.exclude.help": "One series title per line.",
        "config.processing.update_fields": "Fields to Update",
        "config.processing.remove_fields": "Fields to Remove",
        "config.processing.warning": "Remove fields take priority over update fields.",
        # Translation config
        "config.translation.enabled": "Enable Translation",
        "config.translation.provider": "Provider",
        "config.translation.language": "Target Language",
        "config.translation.deepl_key": "DeepL API Key",
        # Logs
        "logs.title": "Logs",
        "logs.exec.title": "Execution Log",
        "logs.audit.title": "Audit Log",
        "logs.exec.debug": "Show Debug",
        "logs.exec.clear": "Clear",
        "logs.exec.empty": "No log entries yet.",
        "logs.audit.empty": "No audit entries yet.",
        "logs.audit.action": "Action",
        "logs.audit.detail": "Detail",
        "logs.audit.time": "Time",
        # Common
        "common.yes": "Yes",
        "common.no": "No",
        "common.enabled": "Enabled",
        "common.disabled": "Disabled",
        "common.save": "Save",
        "common.cancel": "Cancel",
        "common.show": "Show",
        "common.hide": "Hide",
    }
}

_current_locale: str = "en"


def set_locale(locale: str) -> None:
    """Set the active locale (falls back to 'en' if unknown)."""
    global _current_locale
    _current_locale = locale if locale in TRANSLATIONS else "en"


def t(key: str, *, locale: str | None = None, **kwargs) -> str:
    """
    Translate *key* using the current locale.

    Falls back to English, then to the raw key if not found.
    Supports simple format substitutions: t('dashboard.watcher.interval', n=5)
    """
    locale_dict = TRANSLATIONS.get(locale or _current_locale, {})
    en_dict = TRANSLATIONS.get("en", {})
    template = locale_dict.get(key) or en_dict.get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError:
            return template
    return template


def make_translator(locale: str = "en") -> Callable[..., str]:
    """Return a simple ``t(key)`` callable for use in Jinja2 globals."""
    return lambda key, **kwargs: t(key, locale=locale, **kwargs)
