"""Plan displayed book titles independently of external metadata sources."""

import re
from string import Formatter

from modules.config import BookTitleConfig
from modules.models import KomgaBook, KomgaSeries


def book_title(book: KomgaBook, series: KomgaSeries, settings: BookTitleConfig) -> str | None:
    """Render a stable title, skipping missing data rather than guessing a book number."""
    if settings.mode == "off":
        return None
    template = {
        "volume": "Volume {number}",
        "chapter": "Chapter {number}",
        "series": "{series}",
        "custom": settings.template,
    }[settings.mode]
    fields = {field for _, field, _, _ in Formatter().parse(template) if field}
    number = str(book.metadata.number).strip()
    title = series.metadata.title.strip()
    if ("number" in fields and not number) or ("series" in fields and not title):
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", number):
        integer, separator, fraction = number.partition(".")
        number = str(int(integer)).zfill(settings.padding) + separator + fraction
    return template.format(series=title, number=number).strip() or None
