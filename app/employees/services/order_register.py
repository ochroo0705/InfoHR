"""The order register: Info HR orders plus the old program's own order rows, for the people a user may see."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from accounts.models import User
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
    today = today or date.today()
    people = access.visible_employees(user).select_related("department", "position")
    if department_id is not None:
        people = people.filter(department_id=department_id)
    by_id = {e.pk: e for e in people}
    rows: list[RegisterRow] = []
    ours = HrOrder.objects.filter(employee_id__in=by_id).select_related("event")
    taken = set(HrOrder.objects.exclude(command_id=None).values_list("command_id", flat=True))
    if state != LEGACY:
        if year is not None:
            ours = ours.filter(date__year=year)
        if order_type is not None:
            ours = ours.filter(order_type=order_type)
        if state:
            ours = ours.filter(state=state)
        for o in ours:
            rows.append(
                _row(
                    by_id[o.employee_id],
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
            )
    if not state or state == LEGACY:
        legacy = Command.objects.filter(employee_id__in=by_id)
        if year is not None:
            legacy = legacy.filter(date__year=year)
        if order_type is not None:
            legacy = legacy.filter(order_type=order_type)
        for c in legacy:
            if c.pk in taken:
                continue
            rows.append(
                _row(
                    by_id[c.employee_id],
                    today,
                    number=c.number or "",
                    date=c.date,
                    summary=c.summary or "",
                    issued_by=c.issued_by or "",
                    state=LEGACY,
                    state_label="Хуучин програм",
                    order_type=c.order_type,
                    command_id=c.pk,
                )
            )
    words = q.casefold().split()
    if words:  # every word must be part of the order number or the employee's name or code
        rows = [
            r for r in rows if all(w in f"{r.number} {r.employee_name} {r.employee_code}".casefold() for w in words)
        ]
    rows.sort(key=lambda r: r.date or date.min, reverse=True)
    return rows
