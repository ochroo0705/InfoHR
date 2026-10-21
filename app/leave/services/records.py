"""Recording leave: checks, then the calls into the write layer (spec §4, §9, §10).

The write layer (writes.py) owns the rows; this module decides what may be written and logs it.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from accounts.models import User
from django.db import transaction
from employees.models import ActivityEntry, ActivityKind, Employee
from macs.models import LeaveAssign, LeaveTypeRow

from leave.models import type_ext
from leave.services import calendar, entitlement, ledger, rows, writes
from leave.services.fmt import fmt_days
from leave.services.ledger import NO_PERIOD_LABEL, Period
from leave.services.writes import AssignSnapshot, WriteConflict


class LeaveError(Exception):
    """A refused change; the message is shown to the user."""


@dataclass
class Draft:
    employee: Employee
    leave_type: LeaveTypeRow
    start_date: date
    end_date: date
    note: str = ""
    override_reason: str = ""
    leave_id: int | None = None
    loaded: AssignSnapshot | None = None  # the row as the form loaded it (edit and cancel)


@dataclass
class Check:
    working_days: int = 0
    period: Period | None = None
    balance_after: int | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    needs_override: bool = False


def _date(day: date) -> str:
    return day.strftime("%Y-%m-%d")


def _is_annual(leave_type: LeaveTypeRow) -> bool:
    return type_ext(leave_type).uses_annual_balance


def check(draft: Draft, today: date) -> Check:
    c = Check()
    e = draft.employee
    start = entitlement.employment_start(e)
    if start is None:  # legacy row without any start date: no leave can be calculated
        c.errors.append(entitlement.MISSING_START)
        return c
    if draft.end_date < draft.start_date:
        c.errors.append("Дуусах огноо эхлэхээс өмнө байна.")
        return c
    if (draft.end_date - draft.start_date).days > 366:
        c.errors.append("Чөлөө 1 жилээс урт байж болохгүй.")
        return c
    c.working_days = calendar.working_days(draft.start_date, draft.end_date)
    if c.working_days == 0:
        c.errors.append("Сонгосон хугацаанд ажлын өдөр алга.")
        return c
    annual = _is_annual(draft.leave_type)
    for other in rows.leaves(employee_ids=[e.pk], start=draft.start_date, end=draft.end_date):
        if not other.counts or other.id == draft.leave_id:
            continue
        if (other.leave_type.pk, other.start, other.end) == (draft.leave_type.pk, draft.start_date, draft.end_date):
            c.errors.append(writes.DUPLICATE)  # the same leave again: say so, not "overlaps another leave"
            return c
        msg = f"Энэ хугацаанд өөр чөлөө бүртгэгдсэн байна: {other.leave_type} {_date(other.start)}–{_date(other.end)}."
        if annual and other.type_ext.uses_annual_balance:
            c.errors.append(msg)  # two annual leaves may not share days
        else:
            c.warnings.append(msg)
    if not annual:
        return c
    try:
        year = entitlement.year_start_for(e, draft.start_date)
    except ValueError:
        c.errors.append("Ажилд орохоос өмнөх огноо байна.")
        return c
    next_year = entitlement.next_year_start(e, year)
    if draft.end_date >= next_year:
        c.errors.append(
            "Ажлын жилийн хил давсан тул хоёр хуваан бүртгэнэ үү: "
            f"{_date(next_year - timedelta(days=1))} хүртэл, {_date(next_year)}-аас."
        )
        return c
    ledger.ensure_grants(e, today)  # never ahead of today: grants are frozen once written (T-004)
    c.period = ledger.period_for(e, draft.start_date)
    left = ledger.balance_on(e, draft.start_date, exclude_leave_id=draft.leave_id)
    available = 0 if left is None else left  # no grant period: the day is charged with nothing available
    c.balance_after = available - c.working_days
    if c.period is None:
        c.warnings.append(f"Энэ огноонд амралтын эрх олдсонгүй ({NO_PERIOD_LABEL}).")
    if c.balance_after < 0:
        c.needs_override = True
        c.warnings.append(f"Үлдэгдэл хүрэлцэхгүй: {fmt_days(c.balance_after)} хоног болно.")
    eligible = entitlement.eligible_from(e)
    if eligible is not None and draft.start_date < eligible:
        months = entitlement.rule_for(start).eligibility_months
        c.warnings.append(f"Ажилд орсноос хойш {months} сар болоогүй ({_date(eligible)}-аас эрх үүснэ).")
    minimum = entitlement.rule_for(year).min_continuous_part
    others = [lv for lv in c.period.leaves if lv.id != draft.leave_id] if c.period else []
    has_long_part = c.working_days >= minimum or any(lv.days >= minimum for lv in others)
    if not has_long_part and c.balance_after < minimum:
        c.warnings.append(f"Хуулиар нэг хэсэг нь {minimum}-аас доошгүй ажлын өдөр байх ёстой.")
    return c


def _validated(draft: Draft, today: date) -> Check:
    c = check(draft, today)
    if c.errors:
        raise LeaveError(c.errors[0])
    if c.needs_override and not draft.override_reason.strip():
        raise LeaveError("Үлдэгдэл хүрэлцэхгүй тул шалтгаан бичнэ үү.")
    return c


def _override(draft: Draft, c: Check) -> str:
    return draft.override_reason.strip() if c.needs_override else ""


def _text(type_name: str, start: date, end: date, days: int) -> str:
    return f"{type_name} {_date(start)}–{_date(end)} ({fmt_days(days)} ажлын өдөр)"


def _loaded_text(loaded: AssignSnapshot) -> str:
    """The row as the user saw it when the form was opened (for the activity log)."""
    name = LeaveTypeRow.objects.filter(pk=loaded.leave_type_id).values_list("name", flat=True).first() or ""
    days = loaded.adays if loaded.adays is not None else calendar.working_days(loaded.date1, loaded.date2)
    return _text(name, loaded.date1, loaded.date2, days)


def _log(employee: Employee, by: User, message: str) -> None:
    ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.CHANGED, message=message)


def _lock_employee(employee: Employee) -> None:
    """Hold the employee row until the transaction ends, so two saves for one person run one at a time."""
    Employee.objects.select_for_update().get(pk=employee.pk)


@transaction.atomic
def record(draft: Draft, by: User, today: date) -> LeaveAssign:
    _lock_employee(draft.employee)
    c = _validated(draft, today)
    try:
        assign = writes.record_assign(
            draft.employee,
            draft.leave_type,
            draft.start_date,
            draft.end_date,
            c.working_days,
            draft.note.strip(),
            by,
            override_reason=_override(draft, c),
        )
    except WriteConflict as exc:
        raise LeaveError(str(exc)) from exc
    text = _text(str(draft.leave_type), draft.start_date, draft.end_date, c.working_days)
    _log(draft.employee, by, f"Чөлөө бүртгэсэн: {text}")
    return assign


@transaction.atomic
def update(a: LeaveAssign, draft: Draft, by: User, today: date) -> LeaveAssign:
    """Change a recorded leave. The leave keeps its own employee; `draft.loaded` is the row as the form loaded it."""
    _lock_employee(a.employee)
    loaded = draft.loaded
    if loaded is None:  # the form did not carry the loaded row: it cannot be checked for changes
        raise LeaveError(writes.STALE)
    if loaded.status not in (None, LeaveAssign.APPROVED):
        raise LeaveError("Цуцалсан чөлөөг засах боломжгүй.")
    before = _loaded_text(loaded)
    draft.employee = a.employee
    draft.leave_id = a.pk
    c = _validated(draft, today)
    try:
        row = writes.update_assign(
            a,
            loaded,
            leave_type=draft.leave_type,
            start=draft.start_date,
            end=draft.end_date,
            days=c.working_days,
            comment=draft.note.strip(),
            by=by,
            override_reason=_override(draft, c),
        )
    except WriteConflict as exc:
        raise LeaveError(str(exc)) from exc
    after = _text(str(draft.leave_type), draft.start_date, draft.end_date, c.working_days)
    _log(a.employee, by, f"Чөлөө засварласан: {before} → {after}")
    return row


@transaction.atomic
def cancel(a: LeaveAssign, loaded: AssignSnapshot, reason: str, by: User, today: date) -> LeaveAssign:
    """A leave not started yet is cancelled; one that has started is marked "Буруу бүртгэсэн"."""
    reason = reason.strip()
    if not reason:
        raise LeaveError("Шалтгаан бичнэ үү.")
    if loaded.status not in (None, LeaveAssign.APPROVED):
        raise LeaveError("Аль хэдийн цуцалсан.")
    mistake = loaded.date1 <= today
    before = _loaded_text(loaded)
    try:
        row = writes.cancel_assign(a, loaded, reason, mistake=mistake, by=by)
    except WriteConflict as exc:
        raise LeaveError(str(exc)) from exc
    verb = "Буруу бүртгэсэн тул хассан" if mistake else "Чөлөө цуцалсан"
    _log(a.employee, by, f"{verb}: {before}. {reason}")
    return row
