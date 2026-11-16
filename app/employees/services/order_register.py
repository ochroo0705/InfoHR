"""The order register: MACS Human Capital orders plus MACS's own order rows, for the people a user may see."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from accounts.models import User
from django.db.models import F, QuerySet
from macs.dialect import search_match
from macs.models import Command

from employees import access
from employees.models import HrOrder

LEGACY = "legacy"
# The sortable columns and the database fields each one orders by (ascending; a leading "-" reverses).
SORTS = {
    "date": ("date",),
    "number": ("number",),
    "employee": ("employee__family_name", "employee__given_name"),
}
DEFAULT_SORT = "-date"


@dataclass
class RegisterRow:
    number: str
    date: date | None
    employee_id: int
    employee_code: str
    employee_name: str
    department: str
    department_id: int | None
    position: str
    summary: str
    issued_by: str
    register_no: str
    gender: str
    age: int | None
    state: str
    state_label: str
    order_type: int | None
    order_id: int | None = None
    command_id: int | None = None
    awaiting: bool = False  # the change behind the order waits for the signed order (shown as a chip)


def age_on(birth: date | None, today: date) -> int | None:
    if birth is None:
        return None
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _row(emp: Any, today: date, **own: Any) -> RegisterRow:
    return RegisterRow(
        employee_id=emp.pk,
        employee_code=emp.code or "",
        employee_name=f"{emp.family_name or ''} {emp.given_name or ''}".strip(),
        department=emp.department.name if emp.department and emp.department.name else "",
        department_id=emp.department_id,
        position=emp.position.name if emp.position else "",
        register_no=emp.register_no or "",
        gender=emp.get_gender_display() if emp.gender else "",
        age=age_on(emp.birth_date, today),
        **own,
    )


def _matching(rows: QuerySet[Any], words: list[str]) -> QuerySet[Any]:
    """Every word must be part of the order number or the employee's name or code (case does not matter)."""
    for word in words:
        rows = rows.filter(
            search_match(word, "number", "employee__family_name", "employee__given_name", "employee__code", icase=True)
        )
    return rows


def clean_sort(sort: str) -> str:
    """The register's sort: a `SORTS` column, with a leading "-" for descending; anything else is `DEFAULT_SORT`."""
    name = sort[1:] if sort.startswith("-") else sort
    return sort if name in SORTS else DEFAULT_SORT


def sort_heads(sort: str) -> dict[str, dict[str, str]]:
    """Per sortable header: the `sort` a click sends (a second click reverses it), the arrow and the aria-sort value."""
    sort = clean_sort(sort)
    heads: dict[str, dict[str, str]] = {}
    for column in SORTS:
        if sort == column:
            heads[column] = {"next": "-" + column, "arrow": "↑", "aria": "ascending"}
        elif sort == "-" + column:
            heads[column] = {"next": column, "arrow": "↓", "aria": "descending"}
        else:
            heads[column] = {"next": column, "arrow": "", "aria": ""}
    return heads


def _ordering(sort: str) -> tuple[Any, ...]:
    """The database ORDER BY for `sort`; the primary key breaks ties in the same direction."""
    desc = sort.startswith("-")
    column = sort[1:] if desc else sort
    tie = "-pk" if desc else "pk"
    if column == "date":
        return (F("date").desc(nulls_last=True) if desc else F("date").asc(nulls_last=True), tie)
    prefix = "-" if desc else ""
    return (*(prefix + field for field in SORTS[column]), tie)


def _sources(
    user: User,
    *,
    year: int | None,
    order_type: int | None,
    department_id: int | None,
    state: str | None,
    q: str,
    sort: str = DEFAULT_SORT,
) -> tuple[QuerySet[HrOrder] | None, QuerySet[Command] | None]:
    """The two filtered, sorted sources of the register (None when the filters leave a source out).

    Everything is filtered and sorted by the database, so a page can read just the rows it shows."""
    people = access.visible_employees(user)
    if department_id is not None:
        people = people.filter(department_id=department_id)
    words = q.casefold().split()
    ours: QuerySet[HrOrder] | None = None
    legacy: QuerySet[Command] | None = None
    ordering = _ordering(clean_sort(sort))
    if state != LEGACY:
        ours = HrOrder.objects.filter(employee__in=people).select_related(
            "event", "employee__department", "employee__position"
        )
        if year is not None:
            ours = ours.filter(date__year=year)
        if order_type is not None:
            ours = ours.filter(order_type=order_type)
        if state:
            ours = ours.filter(state=state)
        ours = _matching(ours, words).order_by(*ordering)
    if not state or state == LEGACY:
        taken = HrOrder.objects.exclude(command_id=None).values("command_id")
        legacy = (
            Command.objects.filter(employee__in=people)
            .exclude(pk__in=taken)
            .select_related("employee__department", "employee__position")
        )
        if year is not None:
            legacy = legacy.filter(date__year=year)
        if order_type is not None:
            legacy = legacy.filter(order_type=order_type)
        legacy = _matching(legacy, words).order_by(*ordering)
    return ours, legacy


def _ours(o: HrOrder, today: date) -> RegisterRow:
    return _row(
        o.employee,
        today,
        number=o.number,
        date=o.date,
        summary=o.summary,
        issued_by=o.issued_by,
        state=o.state,
        state_label=o.get_state_display(),
        order_type=o.order_type,
        order_id=o.pk,
        awaiting=o.event is not None and o.event.applied_at is None and o.event.cancelled_at is None,
    )


def _legacy(c: Command, today: date) -> RegisterRow:
    return _row(
        c.employee,
        today,
        number=c.number or "",
        date=c.date,
        summary=c.summary or "",
        issued_by=c.issued_by or "",
        state=LEGACY,
        state_label="MACS",
        order_type=c.order_type,
        command_id=c.pk,
    )


def _natural(text: str) -> tuple[tuple[int, int | str], ...]:
    """Order numbers by their digit runs as numbers and the rest as case-folded text (type-tagged so they compare)."""
    parts = (part for part in re.split(r"(\d+)", text) if part)
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in parts)


def _sort_key(sort: str) -> Callable[[RegisterRow], tuple[Any, ...]]:
    """The Python sort key that matches `_ordering` for the merged rows.

    For "-date" it is exactly the old newest-first key: by date, an MACS Human Capital order before an old-program
    order of the same day, then the later record. Undated rows go last in both directions, as nulls_last does in SQL."""
    desc = sort.startswith("-")
    column = sort[1:] if desc else sort

    def key(row: RegisterRow) -> tuple[Any, ...]:
        if column == "date":
            primary: Any = (row.date or date.min) if desc else (row.date is None, row.date or date.min)
        elif column == "number":
            primary = _natural(row.number or "")  # «2/2026» before «10/2026», as a person reads it
        else:
            primary = row.employee_name.casefold()  # «ДД Оюука» among the Д names, not before them
        return primary, row.order_id is not None, row.order_id or row.command_id or 0

    return key


def register_rows(
    user: User,
    *,
    year: int | None,
    order_type: int | None,
    department_id: int | None,
    state: str | None,
    today: date | None = None,
    q: str = "",
    sort: str = DEFAULT_SORT,
) -> list[RegisterRow]:
    """Every matching row in the chosen order (the print view and the report: they need the whole register)."""
    today = today or date.today()
    sort = clean_sort(sort)
    ours, legacy = _sources(
        user, year=year, order_type=order_type, department_id=department_id, state=state, q=q, sort=sort
    )
    rows = [_ours(o, today) for o in ours or ()] + [_legacy(c, today) for c in legacy or ()]
    rows.sort(key=_sort_key(sort), reverse=sort.startswith("-"))
    return rows


def register_page(
    user: User,
    *,
    year: int | None,
    order_type: int | None,
    department_id: int | None,
    state: str | None,
    offset: int,
    size: int,
    today: date | None = None,
    q: str = "",
    sort: str = DEFAULT_SORT,
) -> tuple[list[RegisterRow], bool]:
    """One batch of the register and whether more rows follow it.

    By date, the first `offset + size + 1` rows of the merged list all lie within the first `offset + size + 1` of
    each source, which the database orders the same way, so each source is cut there and the rest is not read. By
    number or name the database collation and Python's string order can differ (Cyrillic, case, empty values), so a
    cut could drop or repeat rows between batches: those sorts read every matching row and sort here, like
    `register_rows`."""
    today = today or date.today()
    sort = clean_sort(sort)
    ours, legacy = _sources(
        user, year=year, order_type=order_type, department_id=department_id, state=state, q=q, sort=sort
    )
    need = offset + size + 1 if sort.lstrip("-") == "date" else None
    rows = [_ours(o, today) for o in (ours[:need] if ours is not None else ())]
    rows += [_legacy(c, today) for c in (legacy[:need] if legacy is not None else ())]
    rows.sort(key=_sort_key(sort), reverse=sort.startswith("-"))
    return rows[offset : offset + size], len(rows) > offset + size
