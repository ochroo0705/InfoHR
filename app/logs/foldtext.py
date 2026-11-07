"""The folded plain-text copy of a log entry's changes, stored on the row (`change_text`) so search can match it.

`fold` is the matching rule of the Ctrl+K palette (`employees.palette._fold` imports it from here: the rule lives
here because `employees.models` needs it and `employees.palette` imports `employees.models`, which would be a cycle).
`change_text` joins the field label, old and new value of every change; `backfill` fills the rows written before the
column existed. Both log tables use it: ActivityEntry and SystemLogEntry.
"""

from typing import Any

from django.db import transaction
from django.db.models import Model

CHANGE_TEXT_LIMIT = 20000  # characters of the folded text kept on a row (Firebird: blob; PostgreSQL: text)
BACKFILL_BATCH = 500  # rows per transaction in `backfill`


def fold(text: str) -> str:
    """Case-folded text with Mongolian ө read as о and ү as у, so the letters match with or without them."""
    return text.casefold().replace("ө", "о").replace("ү", "у")


def change_text(changes: object, limit: int = CHANGE_TEXT_LIMIT) -> str:
    """Field label, old and new value of each change, folded, joined by single spaces and cut to `limit`.
    A missing key or None reads as nothing; numbers read as their digits. A `changes` value that is not a list
    gives no text, and an entry that is not a dict is skipped: a bad stored value must never stop a backfill."""
    if not isinstance(changes, list):
        return ""
    pieces: list[str] = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        for key in ("field", "old", "new"):
            value = change.get(key)
            if value is not None and str(value):
                pieces.append(str(value))
    return fold(" ".join(pieces))[:limit]


def backfill(model: type[Model], batch: int = BACKFILL_BATCH) -> int:
    """Fill `change_text` on the rows where it is still blank, by primary key, `batch` rows per transaction.

    Writes through `_base_manager`, a plain manager: the append-only querysets refuse `.update`, and the historical
    model a migration passes has no custom queryset. Only `change_text` is written; `changes` is never touched.
    Rows with no changes have no text and are left as they are. Returns the number of rows written.
    """
    manager = model._base_manager
    last_pk = 0
    written = 0
    while True:
        rows: list[tuple[int, Any]] = list(
            manager.filter(pk__gt=last_pk, change_text="").order_by("pk").values_list("pk", "changes")[:batch]
        )
        if not rows:
            return written
        with transaction.atomic(using=manager.db):
            for pk, changes in rows:
                text = change_text(changes)
                if text:
                    manager.filter(pk=pk).update(change_text=text)
                    written += 1
        last_pk = rows[-1][0]
