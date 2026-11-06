"""The one place that reads or writes a job or salary period. A period is stored as two dates: `start_date`
(first day) and `end_date` (the first day after it; None = open-ended). The internals can change without
touching the callers."""

from datetime import date
from typing import Any, NamedTuple

from django.db import IntegrityError, transaction
from django.db.models import F, Q

OVERLAP_MESSAGE = "Энэ хугацаа өөр бичлэгтэй давхцаж байна."
LOCK_BUSY_MESSAGE = "Өөр хэрэглэгч энэ ажилтны түүхийг засаж байна. Дахин оролдоно уу."


class Span(NamedTuple):
    """A period as plain dates: `lower` is the first day, `upper` the first day after it (None = open-ended)."""

    lower: date
    upper: date | None

    def __contains__(self, day: object) -> bool:
        if not isinstance(day, date):
            return False
        return self.lower <= day and (self.upper is None or day < self.upper)

    def __str__(self) -> str:
        return f"[{self.lower},{'' if self.upper is None else self.upper})"


def on(day: date) -> Q:
    """Rows whose period contains `day`."""
    return Q(start_date__lte=day) & (Q(end_date__isnull=True) | Q(end_date__gt=day))


def starts_after(day: date) -> Q:
    """Rows that start strictly after `day`."""
    return Q(start_date__gt=day)


def ends_on(day: date) -> Q:
    """Rows whose end is exactly `day`."""
    return Q(end_date=day)


def overlapping(start: date, end: date | None) -> Q:
    """Rows overlapping [start, end); a None end is open-ended."""
    q = Q(end_date__isnull=True) | Q(end_date__gt=start)
    if end is not None:
        q &= Q(start_date__lt=end)
    return q


def span_kwargs(start: date, end: date | None) -> dict[str, Any]:
    """Keyword arguments for Model(...) or Model.objects.create(...)."""
    return {"start_date": start, "end_date": end}


def set_span(record: Any, start: date, end: date | None) -> None:
    """Assign a new span to an unsaved or changed record. Save with update_fields=SPAN_FIELDS."""
    record.start_date, record.end_date = start, end


def get_span(record: Any) -> Span:
    return Span(record.start_date, record.end_date)


SPAN_FIELDS: list[str] = ["start_date", "end_date"]
# Ordering by start_date alone is enough: a start is unique per employee, so the old end-date tie-break cannot
# matter. Do not use ORDER across several employees and expect end-date order.
ORDER: list[str] = ["start_date"]
ORDER_DESC: list[str] = ["-start_date"]


def lock_employee(employee_id: int) -> None:
    """Take the employee's history lock: the first statement of every history write, inside its transaction.

    Bumps the counter of the employee's HistoryLock row (creating the row on first use). A second writer waits on
    or is refused by this UPDATE until the first writer ends its transaction
    (see docs/migration/overlap-guard-spike.md).

    If the row does not exist yet and another writer creates it first, this writer is refused with HistoryError.
    It must not retry the UPDATE: on Firebird the retry would succeed without holding the lock.
    """
    from employees.models import HistoryLock  # local: models imports this module
    from employees.services.history import HistoryError  # local: services.history imports this module

    with transaction.atomic():
        if HistoryLock.objects.filter(employee_id=employee_id).update(counter=F("counter") + 1):
            return
        try:
            with transaction.atomic():  # savepoint: the IntegrityError must not poison the outer transaction
                HistoryLock.objects.create(employee_id=employee_id, counter=1)
        except IntegrityError as exc:  # another writer created the row first
            raise HistoryError(LOCK_BUSY_MESSAGE) from exc


def ensure_free(
    model: type[Any], employee_id: int, start: date, end: date | None, exclude_pk: int | None = None
) -> None:
    """Refuse a period [start, end) that overlaps another period of the same employee. The caller holds the lock.

    `exclude_pk` is the record being moved, which must not count against itself.
    """
    from employees.services.history import HistoryError  # local: services.history imports this module

    if end is not None and end <= start:
        raise HistoryError(OVERLAP_MESSAGE)
    others = model.objects.filter(employee_id=employee_id).filter(overlapping(start, end))
    if exclude_pk is not None:
        others = others.exclude(pk=exclude_pk)
    if others.exists():
        raise HistoryError(OVERLAP_MESSAGE)
