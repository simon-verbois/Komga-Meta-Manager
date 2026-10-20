"""Provider capabilities and built-in source templates, independent of configuration storage."""

SOURCE_CATALOGUE = {
    "anilist": {
        "display": "AniList",
        "types": ("manga", "webtoon"),
        "fields": ("summary", "genres", "status", "authors", "cover", "score", "links"),
    },
    "mangadex": {
        "display": "MangaDex",
        "types": ("manga", "webtoon"),
        "fields": ("summary", "genres", "status", "authors", "cover", "links"),
    },
    "mangaupdates": {
        "display": "MangaUpdates",
        "types": ("manga", "webtoon"),
        "fields": ("summary", "publisher", "genres", "status", "authors", "cover", "score", "links"),
    },
    "openlibrary": {
        "display": "Open Library",
        "types": ("ebook",),
        "fields": ("summary", "publisher", "authors", "cover", "date", "isbn", "links"),
    },
    "googlebooks": {
        "display": "Google Books",
        "types": ("ebook",),
        "fields": ("summary", "publisher", "authors", "cover", "genres", "date", "isbn", "links"),
        "requires_key": True,
    },
    "bnf": {
        "display": "BnF",
        "types": ("ebook",),
        "fields": ("summary", "publisher", "authors", "date", "isbn", "links"),
    },
}
SUPPORTED_METADATA_PROVIDERS = tuple(SOURCE_CATALOGUE)
MANGA_PROVIDERS = ("anilist", "mangadex", "mangaupdates")
BUILTIN_TEMPLATES = {
    "manga": {"name": "Manga", "content_type": "manga", "names": MANGA_PROVIDERS},
    "webtoon": {"name": "Webtoon", "content_type": "webtoon", "names": MANGA_PROVIDERS},
    "ebooks-general": {"name": "Ebooks — General", "content_type": "ebook", "names": ("openlibrary", "googlebooks")},
    "ebooks-french": {
        "name": "Ebooks — French",
        "content_type": "ebook",
        "names": ("bnf", "openlibrary", "googlebooks"),
        "language": "fr",
    },
}


def compatible_sources(content_type: str) -> tuple[str, ...]:
    """Return providers supporting a library's content type."""
    return tuple(name for name, source in SOURCE_CATALOGUE.items() if content_type in source["types"])


def builtin_templates() -> dict[str, dict]:
    """Return fresh template copies; credentials never belong to templates."""
    return {
        key: {
            "name": value["name"],
            "content_type": value["content_type"],
            "providers": [
                {"name": name, "priority": index, "enabled": True, "preferred_language": value.get("language", "en")}
                for index, name in enumerate(value["names"], 1)
            ],
        }
        for key, value in BUILTIN_TEMPLATES.items()
    }
