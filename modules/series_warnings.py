"""Detect suspicious book numbering without changing metadata or publication."""

import re
from collections import defaultdict
from decimal import Decimal


# Only explicit volume/chapter labels followed by optional release tags count.
# Ignore years, arbitrary digits, ranges and omnibus titles rather than guessing.
TITLE_NUMBER = re.compile(
    r"(?<!\w)(?:t(?:ome)?|vol(?:ume)?|ch(?:apter)?|chapitre)\.?\s*(\d+(?:\.\d+)?)"
    r"\s*(?:(?:\([^()]*\)|\[[^\[\]]*\])\s*)*$",
    re.IGNORECASE,
)


def _number(value: object) -> Decimal | None:
    text = str(value if value is not None else "").strip()
    return Decimal(text) if re.fullmatch(r"\d+(?:\.\d+)?", text) else None


def numbering_warnings(books: list[dict]) -> list[dict]:
    """Report duplicate explicit numbers and title/number conflicts in Komga values.

    Books contain an id and the last known remote metadata. Unknown baselines
    are omitted by the caller; pending titles must never hide existing issues.
    Repeated plain titles and gaps are allowed for ebooks, specials and chapters.
    """
    numbers, title_numbers = defaultdict(list), defaultdict(list)
    mismatches = []
    for book in books:
        metadata = book["metadata"]
        title = str(metadata.get("title") or "")
        number = _number(metadata.get("number"))
        match = TITLE_NUMBER.search(title)
        title_number = _number(match[1]) if match else None
        item = {"id": book["id"], "title": title, "number": metadata.get("number", "")}
        if number is not None:
            numbers[number].append(item)
        if title_number is not None:
            title_numbers[title_number].append(item)
        if number is not None and title_number is not None and number != title_number:
            mismatches.append(item)
    warnings = []
    for code, grouped in (("duplicate_number", numbers), ("duplicate_title_number", title_numbers)):
        for number, items in sorted(grouped.items()):
            if len(items) > 1:
                warnings.append({"code": code, "number": format(number.normalize(), "f"), "books": items})
    if mismatches:
        warnings.append({"code": "title_number_mismatch", "books": mismatches})
    return warnings
