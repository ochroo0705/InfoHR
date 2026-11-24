"""The leave add, edit and cancel pop-ups' rules: the first values a form shows, the assistant's lines, the live
check and the cancel question. The Django pop-up views and the API both call this module. Rules only; drawing is the
caller's job.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from accounts.models import User
from django.db.models import QuerySet
from django.http import Http404
from employees import access as employee_access
from employees import palette as employee_palette
from employees.models import Employee
from macs.models import LeaveAssign

from leave.forms import LeaveForm, active_types, initial_dates
from leave.services import records, rows
from leave.services.list_page import MAX_INT, parse_id, parse_iso
from leave.services.rows import LeaveRow

MAX_PREFILL_YEARS = 10  # a date this far from today is a typing slip (the assistant refuses the same), not a leave date


@dataclass(frozen=True)
class CancelInfo:
    label: str  # the leave type's name, as the cancel pop-up's line shows it
    start: date
    end: date
    mistake: bool  # the leave has started: the cancel is marked «Буруу бүртгэсэн», not removed
    restores_balance: bool  # the leave type uses the annual balance, so the days come back


def visible_assign(user: User, pk: int | None) -> LeaveAssign | None:
    """A production leave row whose employee the user may see, or None. An id outside 0..2**31-1 (as parse_id refuses
    them) is no leave and is never queried."""
    if pk is None or not 0 <= pk <= MAX_INT:
        return None
    visible = employee_access.visible_employees(user).values("pk")
    return LeaveAssign.objects.filter(pk=pk, employee_id__in=visible).first()


def own_leave(user: User, pk: int) -> tuple[LeaveAssign, LeaveRow]:
    """A leave the user may see, with its row. Http404 for an invisible or unusable one (the API maps it to 404)."""
    found = visible_assign(user, pk)
    if found is None:
        raise Http404
    try:
        return found, rows.leave(found.pk)
    except LeaveAssign.DoesNotExist as exc:  # unusable row (missing employee or type): not shown
        raise Http404 from exc


def _prefill_date(raw: str | None, t: date) -> date | None:
    day = parse_iso(raw or "")
    if day is None or abs(day.year - t.year) > MAX_PREFILL_YEARS:
        return None
    return day


def visible_pk(raw: str | None, employees: QuerySet[Employee]) -> int | None:
    """An employee id from the address or the posted form, only when the asker may see that employee."""
    pk = parse_id(raw)
    return pk if pk is not None and employees.filter(pk=pk).exists() else None


def add_initial(
    query: Mapping[str, str], employees: QuerySet[Employee], today: date
) -> tuple[dict[str, Any], list[str]]:
    """The first values of a new leave, read from the address (the assistant's leave link, or a link from the employee
    page), and the labels of what the address filled. A value the asker may not use (an employee outside `employees`,
    an inactive type) or that does not parse is left out; a date that was given but is unusable stays empty. The form's
    own querysets refuse the same values on POST, so this only fills the boxes: it grants nothing."""
    dates_given = query.get("from") == "assistant" or "start" in query or "end" in query
    initial: dict[str, Any] = dict(initial_dates(today))
    filled: list[str] = []
    employee_pk = visible_pk(query.get("employee"), employees)
    if employee_pk is not None:
        initial["employee"] = employee_pk
        filled.append("Ажилтан")
    type_pk = parse_id(query.get("type"))
    if type_pk is not None and (found := active_types().filter(pk=type_pk).first()) is not None:
        initial["leave_type"] = found.pk
        filled.append("Төрөл")
    if dates_given:
        start, end = _prefill_date(query.get("start"), today), _prefill_date(query.get("end"), today)
        if start is not None and end is not None and end < start:
            end = None
        initial.update(start_date=start, end_date=end)
        filled += [label for label, day in (("Эхлэх", start), ("Дуусах", end)) if day is not None]
    return initial, filled


def assisted_lines(user: User, employee_pk: int | None, filled: list[str], today: date) -> dict[str, str]:
    """The two soft lines above the form when the link came from the assistant: the chosen person (name, then position
    and department as the lists show a job) and what the sentence filled in."""
    line = ""
    if (pk := employee_pk) is not None:
        person = Employee.objects.get(pk=pk)
        hit = employee_palette.current(user, pk, today)
        parts = [person.full_name, hit.position, hit.department] if hit else [person.full_name]
        line = " · ".join(part for part in parts if part)
    filled_line = (
        f"Асуултаас бөглөсөн: {', '.join(filled)}"
        if filled
        else "Асуултаас юу ч бөглөгдөөгүй. Мэдээллээ өөрөө оруулна уу."
    )
    return {"person_line": line, "filled_line": filled_line}


def edit_initial(a: LeaveAssign, row: LeaveRow) -> dict[str, Any]:
    """The first values of the edit form: the stored row, as the Django edit view shows it."""
    return {
        "employee": a.employee_id,
        "leave_type": a.leave_type_id,
        "start_date": a.date1,
        "end_date": a.date2,
        "note": a.comment or "",
        "override_reason": row.override_reason,
    }


def check_for(user: User, form: LeaveForm, leave_id: int | None, today: date) -> records.Check | None:
    """The live check of a form as posted, or None when the form is invalid. An edit (`leave_id` a leave the user may
    see) checks against that leave's own employee, not the posted one; any other id is ignored."""
    if not form.is_valid():
        return None
    leave = visible_assign(user, leave_id) if leave_id is not None else None
    draft = form.draft(leave_id=leave.pk if leave else None)
    if leave is not None:  # same as records.update: the leave's own employee, not the posted one
        draft.employee = leave.employee
    return records.check(draft, today)


def cancel_info(a: LeaveAssign, row: LeaveRow, today: date) -> CancelInfo:
    """What the cancel pop-up asks: a leave that has started is marked wrong (same rule as records.cancel)."""
    return CancelInfo(
        label=str(row.leave_type),
        start=row.start,
        end=row.end,
        mistake=a.date1 <= today,
        restores_balance=row.type_ext.uses_annual_balance,
    )
