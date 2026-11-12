"""Small-group protection: a money figure over too few rows is one person's figure, so it is not shown."""

from collections.abc import Sized

from django.conf import settings

from reports.types import Column


def min_group() -> int:
    """The smallest bucket whose money figure is shown; read at call time so tests and installs can change it."""
    return int(getattr(settings, "REPORTS_MIN_GROUP", 3))


def masked(value: tuple[Column | None, str], rows: Sized) -> bool:
    """True when this bucket's figure must be hidden: the value is an aggregate (not the count) of a money column
    and the bucket has at least one row but fewer than min_group()."""
    column, agg = value
    if column is None or agg == "count" or not column.money:
        return False
    size = len(rows)
    return 0 < size < min_group()


def masked_note(group: int) -> str:
    """The note under a chart or pivot that hid a figure; the same text as reports/print.html and chart.html."""
    return f"{group}-ээс цөөн мөртэй бүлгийн мөнгөн дүнг нуусан («—»)."
