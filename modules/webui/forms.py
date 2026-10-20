"""Translate guided form controls to configuration values and back, shared by defaults and libraries."""

from modules.config import SUPPORTED_METADATA_PROVIDERS

# (form name, config path, can be filled from sources)
RULE_FIELDS = (
    ("summary", ("summary",), True),
    ("publisher", ("publisher",), True),
    ("genres", ("genres",), True),
    ("status", ("status",), True),
    ("cover_image", ("cover_image",), True),
    ("link", ("link",), True),
    ("writers", ("authors", "writers"), True),
    ("pencillers", ("authors", "pencillers"), True),
    ("score", ("tags", "score"), True),
    ("language", ("language",), False),
    ("reading_direction", ("reading_direction",), False),
)
RULE_CHOICES = ("keep", "fill", "remove")
SOURCE_NAMES = {"anilist": "AniList", "mangadex": "MangaDex", "mangaupdates": "MangaUpdates"}

# Codes are normalized per translation service by the configuration model.
LANGUAGES = (
    ("en-us", "English"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
    ("it", "Italian"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
)
SOURCE_LANGUAGES = (("en", "English"), ("ja", "Japanese"), ("fr", "French"), ("es", "Spanish"), ("de", "German"))


def _get(flags: dict, path: tuple, default=False):
    value = flags or {}
    for key in path:
        value = (value or {}).get(key, default if key == path[-1] else {})
    return bool(value)


def rule_choices(processing: dict) -> dict:
    """Return the per-field choice (keep, fill or remove) for a processing configuration."""
    update, remove = processing.get("update_fields", {}), processing.get("remove_fields", {})
    defaults = {"summary", "publisher", "genres", "status", "cover_image", "writers", "pencillers"}
    choices = {}
    for name, path, fillable in RULE_FIELDS:
        if _get(remove, path):
            choices[name] = "remove"
        elif fillable and _get(update, path, name in defaults):
            choices[name] = "fill"
        else:
            choices[name] = "keep"
    return choices


def processing_patch(form, existing: dict | None = None) -> dict:
    """Read guided rule controls; exclusions are managed separately and preserved."""
    existing = existing or {}
    patch = {
        "book_titles": dict(existing.get("book_titles", {})),
        "overwrite_existing": form.get("existing_values") == "replace",
        "force_unlock": form.get("locked_fields") == "change",
        "exclude_series": list(existing.get("exclude_series", [])),
        "update_fields": {"authors": {}, "tags": {}},
        "remove_fields": {"authors": {}, "tags": {}},
    }
    if "book_title_mode" in form:
        patch["book_titles"] = {
            "mode": form.get("book_title_mode"),
            "template": form.get("book_title_template", ""),
            "padding": form.get("book_title_padding", "0"),
        }
    for name, path, fillable in RULE_FIELDS:
        choice = form.get(f"rule_{name}", "keep")
        if choice not in RULE_CHOICES or (choice == "fill" and not fillable):
            choice = "keep"
        for group, active in (("update_fields", choice == "fill"), ("remove_fields", choice == "remove")):
            if group == "update_fields" and not fillable:
                continue
            target = patch[group]
            for key in path[:-1]:
                target = target.setdefault(key, {})
            target[path[-1]] = active
    return patch


def ordered_sources(providers: list[dict]) -> list[dict]:
    """List every supported source in priority order, with display names."""
    known = {source["name"]: source for source in providers}
    rows = sorted(
        (known.get(name, {"name": name, "enabled": False, "priority": 99}) for name in SUPPORTED_METADATA_PROVIDERS),
        key=lambda source: source.get("priority", 99),
    )
    return [{**source, "display": SOURCE_NAMES[source["name"]]} for source in rows]


def sources_patch(form, existing: list[dict]) -> list[dict]:
    """Read source order and options; priority follows the order chosen in the form."""
    known = {source["name"]: source for source in existing}
    order = [name for name in form.getlist("source_order") if name in SUPPORTED_METADATA_PROVIDERS]
    order = list(dict.fromkeys(order + [s["name"] for s in ordered_sources(existing)]))
    sources = []
    for priority, name in enumerate(order, start=1):
        source = dict(known.get(name, {"name": name}))
        source.update(
            {
                "name": name,
                "enabled": f"{name}_enabled" in form,
                "priority": priority,
                "min_score": form.get(f"{name}_min_score", source.get("min_score", 80)),
                "preferred_language": form.get(f"{name}_preferred_language", source.get("preferred_language", "en")),
                "allow_adult": f"{name}_allow_adult" in form,
                "cache": {"ttl_hours": form.get(f"{name}_cache_ttl", (source.get("cache") or {}).get("ttl_hours", 168))},
            }
        )
        sources.append(source)
    return sources


def language_options(current: str | None, choices=LANGUAGES) -> list[tuple[str, str]]:
    """Offer the common languages and keep an unlisted saved value selectable."""
    options = list(choices)
    value = language_value(current, choices)
    if value and value not in {code for code, _ in options}:
        options.append((value, value))
    return options


def language_value(current: str | None, choices=LANGUAGES) -> str:
    """Select the listed option matching a saved code (EN-US, en and en-us are the same choice)."""
    normalized = (current or "en-us").lower()
    normalized = {"en": "en-us", "en-gb": "en-us"}.get(normalized, normalized)
    if choices is SOURCE_LANGUAGES:
        normalized = normalized.split("-")[0]
    return normalized if normalized in {code for code, _ in choices} else (current or "")
