"""Plan explicit, series-scoped numbering overrides for the local catalogue."""

import hashlib
import json
import re
from decimal import Decimal

from modules.book_titles import book_title
from modules.config import BookTitleConfig
from modules.manual_metadata import ManualEditError
from modules.models import KomgaBook, KomgaSeries


def numbering_version(series: KomgaSeries, books: list[KomgaBook], settings: BookTitleConfig) -> str:
    """Fingerprint the editing baseline, including membership, locks and naming rules."""
    data = [series.model_dump(mode="json"), [book.model_dump(mode="json") for book in books], settings.model_dump()]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def plan_numbering(
    series: KomgaSeries, books: list[KomgaBook], settings: BookTitleConfig, numbers: dict[str, str],
) -> list[dict]:
    """Change only explicitly edited numbers, ordering and their configured titles.

    Unchanged labels (including specials) are preserved. Decimal chapters and
    volume zero are supported. Every changed field is a protected manual edit.
    """
    if set(numbers) != {book.id for book in books}:
        raise ManualEditError("numbering.conflict", 409)
    patches = []
    for book in books:
        if not isinstance(numbers[book.id], str):
            raise ManualEditError("numbering.invalid")
        number = numbers[book.id].strip()
        if number == str(book.metadata.number):
            continue
        if not re.fullmatch(r"\d{1,6}(?:\.\d{1,3})?", number) or Decimal(number) > 999999:
            raise ManualEditError("numbering.invalid")
        updated = book.model_copy(deep=True)
        updated.metadata.number = number
        payload = {
            "number": number, "numberLock": True,
            "numberSort": float(Decimal(number)), "numberSortLock": True,
        }
        title = book_title(updated, series, settings)
        if title is not None and title != book.metadata.title:
            payload.update(title=title, titleLock=True)
        patches.append({"entity": "books", "id": book.id, "payload": payload})
    return patches


def plan_book_order(
    series: KomgaSeries, books: list[KomgaBook], settings: BookTitleConfig, order: list[str],
) -> list[dict]:
    """Assign existing number slots to an explicitly reordered subset of books.

    Books absent from Review keep their numbers. Repeated or special number
    labels require the numbering editor rather than silently inventing values.
    """
    by_id = {book.id: book for book in books}
    if len(order) != len(set(order)) or not set(order) <= by_id.keys():
        raise ManualEditError("numbering.conflict", 409)
    selected_ids = set(order)
    selected = sorted((book for book in books if book.id in selected_ids),
                      key=lambda book: (book.metadata.number_sort, book.id))
    slots = [str(book.metadata.number) for book in selected]
    if (any(not re.fullmatch(r"\d{1,6}(?:\.\d{1,3})?", number) for number in slots)
            or len({Decimal(number) for number in slots}) != len(slots)):
        raise ManualEditError("numbering.order_invalid")
    numbers = {book.id: str(book.metadata.number) for book in books}
    numbers.update(zip(order, slots))
    return plan_numbering(series, books, settings, numbers)
