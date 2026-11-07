"""The kind of a column: text, number or date. Sorting and filters use it."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from reports.types import Column

KINDS = ("text", "number", "date")

SAMPLE_SIZE = 200  # how many values are looked at when the kind is worked out


def column_kind(column: Column, rows: Sequence[Any]) -> str:
    """The column's kind: its own `kind`, then its flags, then the values in the first rows."""
    if column.kind in KINDS:
        return column.kind
    if column.numeric or column.money:
        return "number"
    values = []
    for row in rows:
        value = column.value(row)
        if value is not None:
            values.append(value)
            if len(values) == SAMPLE_SIZE:
                break
    if not values:
        return "text"
    if all(isinstance(v, date) for v in values):
        return "date"
    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in values):
        return "number"
    return "text"
