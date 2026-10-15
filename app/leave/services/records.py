"""Recording leave: checks, then the only writers of Leave rows (spec §4)."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from accounts.models import User
from django.db import transaction
from employees.models import ActivityEntry, ActivityKind, Employee

from leave.models import Leave, LeaveStatus, LeaveType
from leave.services import calendar, entitlement, ledger
from leave.services.fmt import fmt_days


class LeaveError(Exception):
    """A refused change; the message is shown to the user."""


@dataclass
class Draft:
    employee: Employee
    leave_type: LeaveType
    start_date: date
    end_date: date
    start_half: bool = False
    end_half: bool = False
    note: str = ""
    override_reason: str = ""
    leave_id: int | None = None


@dataclass
class Check:
    working_days: Decimal = Decimal(0)
    year_start: date | None = None
    balance_after: Decimal | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    needs_override: bool = False


def _date(day: date) -> str:
    return day.strftime("%Y-%m-%d")


def check(draft: Draft, today: date) -> Check:
    c = Check()
    if draft.end_date < draft.start_date:
        c.errors.append("Дуусах огноо эхлэхээс өмнө байна.")
        return c
    if (draft.end_date - draft.start_date).days > 366:
        c.errors.append("Чөлөө 1 жилээс урт байж болохгүй.")
        return c
    c.working_days = calendar.working_days(
        draft.start_date, draft.end_date, start_half=draft.start_half, end_half=draft.end_half
    )
    if c.working_days == 0:
        c.errors.append("Сонгосон хугацаанд ажлын өдөр алга.")
        return c
    others = Leave.objects.filter(
        employee=draft.employee,
        status=LeaveStatus.RECORDED,
        start_date__lte=draft.end_date,
        end_date__gte=draft.start_date,
    )
    if draft.leave_id is not None:
        others = others.exclude(pk=draft.leave_id)
    for o in others.select_related("leave_type"):
        msg = f"Энэ хугацаанд өөр чөлөө бүртгэгдсэн байна: {o.leave_type} {_date(o.start_date)}–{_date(o.end_date)}."
        if draft.leave_type.uses_annual_balance and o.leave_type.uses_annual_balance:
            c.errors.append(msg)  # two annual leaves may not share days
        else:
            c.warnings.append(msg)
    if not draft.leave_type.uses_annual_balance:
        return c
    e = draft.employee
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
    c.year_start = year
    ledger.ensure_grants(e, today)  # never ahead of today: grants are frozen once written (T-004)
    available = ledger.balance(e, year, exclude_leave_id=draft.leave_id) + ledger.pending_grant(e, year)
    c.balance_after = available - c.working_days
    if c.balance_after < 0:
        c.needs_override = True
        c.warnings.append(f"Үлдэгдэл хүрэлцэхгүй: {fmt_days(c.balance_after)} хоног болно.")
    eligible = entitlement.eligible_from(e)
    if draft.start_date < eligible:
        months = entitlement.rule_for(entitlement.employment_start(e)).eligibility_months
        c.warnings.append(f"Ажилд орсноос хойш {months} сар болоогүй ({_date(eligible)}-аас эрх үүснэ).")
    minimum = entitlement.rule_for(year).min_continuous_part
    parts = Leave.objects.filter(
        employee=e, year_start=year, status=LeaveStatus.RECORDED, leave_type__uses_annual_balance=True
    )
    if draft.leave_id is not None:
        parts = parts.exclude(pk=draft.leave_id)
    has_long_part = c.working_days >= minimum or parts.filter(working_days__gte=minimum).exists()
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


def _describe(leave: Leave) -> str:
    return (
        f"{leave.leave_type} {_date(leave.start_date)}–{_date(leave.end_date)} "
        f"({fmt_days(leave.working_days)} ажлын өдөр)"
    )


def _log(employee: Employee, by: User, message: str) -> None:
    ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.CHANGED, message=message)


def _apply(leave: Leave, draft: Draft, c: Check) -> None:
    leave.leave_type = draft.leave_type
    leave.start_date, leave.end_date = draft.start_date, draft.end_date
    leave.start_half, leave.end_half = draft.start_half, draft.end_half
    leave.working_days, leave.year_start = c.working_days, c.year_start
    leave.note = draft.note.strip()
    leave.override_reason = draft.override_reason.strip() if c.needs_override else ""


@transaction.atomic
def record(draft: Draft, by: User, today: date) -> Leave:
    c = _validated(draft, today)
    leave = Leave(employee=draft.employee, created_by=by)
    _apply(leave, draft, c)
    leave.save()
    _log(draft.employee, by, f"Чөлөө бүртгэсэн: {_describe(leave)}")
    return leave


@transaction.atomic
def update(leave: Leave, draft: Draft, by: User, today: date) -> Leave:
    if leave.status != LeaveStatus.RECORDED:
        raise LeaveError("Цуцалсан чөлөөг засах боломжгүй.")
    draft.leave_id = leave.pk
    draft.employee = leave.employee
    c = _validated(draft, today)
    before = _describe(leave)
    _apply(leave, draft, c)
    leave.save()
    _log(leave.employee, by, f"Чөлөө засварласан: {before} → {_describe(leave)}")
    return leave


@transaction.atomic
def cancel(leave: Leave, reason: str, by: User, today: date) -> Leave:
    """A leave not started yet is cancelled; one that has started or ended is marked "Буруу бүртгэсэн"."""
    reason = reason.strip()
    if not reason:
        raise LeaveError("Шалтгаан бичнэ үү.")
    if leave.status != LeaveStatus.RECORDED:
        raise LeaveError("Аль хэдийн цуцалсан.")
    mistake = leave.started(today)
    leave.status = LeaveStatus.MISTAKE if mistake else LeaveStatus.CANCELLED
    leave.cancel_reason = reason
    leave.save(update_fields=["status", "cancel_reason", "updated_at"])
    verb = "Буруу бүртгэсэн тул хассан" if mistake else "Чөлөө цуцалсан"
    _log(leave.employee, by, f"{verb}: {_describe(leave)}. {reason}")
    return leave


@transaction.atomic
def recount(days: set[date], by: User) -> int:
    """Re-count recorded leaves covering `days` after the holiday list changed; returns how many changed."""
    if not days:
        return 0
    changed = 0
    covering = Leave.objects.filter(
        status=LeaveStatus.RECORDED, start_date__lte=max(days), end_date__gte=min(days)
    ).select_related("employee", "leave_type")
    for leave in covering:
        if not any(leave.start_date <= d <= leave.end_date for d in days):
            continue
        new = calendar.working_days(
            leave.start_date, leave.end_date, start_half=leave.start_half, end_half=leave.end_half
        )
        if new == leave.working_days:
            continue
        before = _describe(leave)
        leave.working_days = new
        leave.save(update_fields=["working_days", "updated_at"])
        _log(leave.employee, by, f"Баярын өдөр өөрчлөгдсөн тул дахин тооцсон: {before} → {fmt_days(new)} ажлын өдөр")
        changed += 1
    return changed
