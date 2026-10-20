"""Small presentation helpers shared by every page: counts, plurals and readable history."""

import json

from modules.webui.config_store import get_config
from modules.webui.i18n import t


def nav_pending() -> int:
    """Series with unpublished changes, shown next to Review in the navigation."""
    try:
        cfg = get_config()
        if cfg is None:
            return 0
        from modules.local_metadata import LocalCatalogue

        return sum(LocalCatalogue(str(cfg.komga.url).rstrip("/")).pending_counts().values())
    except Exception:
        return 0


def plural(n, one: str, many: str) -> str:
    """Pick the singular or plural translation key and fill in the count."""
    return t(one if n == 1 else many, n=n)


def audit_text(entry: dict) -> dict:
    """Turn a stored audit entry into a readable action name and sentence."""
    action, detail = entry.get("action", ""), entry.get("detail") or ""
    label = t(f"audit.{action}")
    if label == f"audit.{action}":
        label = action.replace("_", " ").capitalize()
    if action.startswith("MANUAL_EDIT"):
        try:
            data = json.loads(detail)

            def names(items):
                found = []
                for item in items or []:
                    found += item.get("fields", []) if isinstance(item, dict) else [str(item)]
                return ", ".join(dict.fromkeys(found))

            detail = t("audit.manual_detail", user=data.get("user", ""), fields=names(data.get("applied")) or "—")
            if data.get("failed"):
                detail += " " + t("audit.manual_failed", fields=names(data["failed"]))
        except (ValueError, TypeError, AttributeError):
            pass
    # Older entries recorded technical flags; show them in words.
    detail = detail.replace("(dry_run=True)", "(simulation)").replace("(dry_run=False)", "")
    detail = detail.replace("dry_run set to True", "simulation turned on").replace(
        "dry_run set to False", "simulation turned off"
    )
    return {"label": label, "detail": detail.strip() or "—"}
