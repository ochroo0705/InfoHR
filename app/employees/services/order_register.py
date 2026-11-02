"""The order register: Info HR orders plus MACS's own order rows, for the people a user may see."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from accounts.models import User
from django.db.models import F, Q, QuerySet
from macs.models import Command

from employees import access
from employees.models import HrOrder

LEGACY = "legacy"


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
            Q(number__icontains=word)
            | Q(employee__family_name__icontains=word)
            | Q(employee__given_name__icontains=word)
            | Q(employee__code__icontains=word)
        )
    return rows


def _sources(
    user: User,
    *,
    year: int | None,
    order_type: int | None,
    department_id: int | None,
    state: str | None,
    q: str,
) -> tuple[QuerySet[HrOrder] | None, QuerySet[Command] | None]:
    """The two filtered, newest-first sources of the register (None when the filters leave a source out).

    Everything is filtered and sorted by the database, so a page can read just the rows it shows."""
    people = access.visible_employees(user)
    if department_id is not None:
        people = people.filter(department_id=department_id)
    words = q.casefold().split()
    ours: QuerySet[HrOrder] | None = None
    legacy: QuerySet[Command] | None = None
    newest_first = (F("date").desc(nulls_last=True), "-pk")
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
        ours = _matching(ours, words).order_by(*newest_first)
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
        legacy = _matching(legacy, words).order_by(*newest_first)
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


def _newest_first(row: RegisterRow) -> tuple[date, bool, int]:
    """Sort key: by date, an Info HR order before an old-program order of the same day, then the later record."""
    return row.date or date.min, row.order_id is not None, row.order_id or row.command_id or 0


def register_rows(
    user: User,
    *,
    year: int | None,
    order_type: int | None,
    department_id: int | None,
    state: str | None,
    today: date | None = None,
    q: str = "",
) -> list[RegisterRow]:
    """Every matching row, newest first (the print view and the report: they need the whole register)."""
    today = today or date.today()
    ours, legacy = _sources(user, year=year, order_type=order_type, department_id=department_id, state=state, q=q)
    rows = [_ours(o, today) for o in ours or ()] + [_legacy(c, today) for c in legacy or ()]
    rows.sort(key=_newest_first, reverse=True)
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
) -> tuple[list[RegisterRow], bool]:
    """One batch of the register and whether more rows follow it, without reading the rest.

    The newest `offset + size + 1` rows of the merged list all lie within the newest `offset + size + 1` of each
    source, so each source is cut there and the two are merged here."""
    today = today or date.today()
    ours, legacy = _sources(user, year=year, order_type=order_type, department_id=department_id, state=state, q=q)
    need = offset + size + 1
    rows = [_ours(o, today) for o in (ours[:need] if ours is not None else ())]
    rows += [_legacy(c, today) for c in (legacy[:need] if legacy is not None else ())]
    rows.sort(key=_newest_first, reverse=True)
    return rows[offset : offset + size], len(rows) > offset + size
