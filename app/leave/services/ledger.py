"""Annual-leave ledger on grant periods (spec §5, §6).

A period is one exact (start, end) pair of annual-type grants. A counted annual leave is charged to
the period that contains its start; when several contain it, the latest start wins. Everything is
read from the production rows on each call (spec §10: nothing is cached).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User
from django.db import transaction
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, Employee, JobStatus
from employees.services import history
from macs.models import LeaveTypeRow

from leave.models import GrantKind, LeaveSettings, LeaveTypeExt
from leave.services import entitlement, rows, writes
from leave.services.rows import GrantRow, LeaveRow

NOT_CONFIGURED = "Ээлжийн амралтын төрлийг сонгоогүй байна"
NO_PERIOD_LABEL = "Хугацаа тодорхойгүй"


class LedgerError(Exception):
    """A refused change; the message is shown to the user."""


@dataclass
class Period:
    start: date
    end: date
    granted: int
    taken: int
    left: int
    grants: list[GrantRow]
    leaves: list[LeaveRow]
    doubled: bool
    upcoming: bool = False  # starts after today
    current: bool = False  # today falls inside it


def _grant_starts(employee: Employee, today: date) -> list[date]:
    """Leave-year starts up to `today`, none starting after the person left."""
    starts = entitlement.year_starts(employee, today)
    if not employee.job_records.exists():
        # MACS-only employee: MACS has no leaving date, so a leaver gets no leave years at all (QC 2a review).
        from employees.listing import legacy_job

        return [] if legacy_job(employee).status == JobStatus.LEFT else starts
    job = history.job_on(employee, today)
    if job is not None and job.status == JobStatus.LEFT:
        starts = [s for s in starts if s < job.period.lower]
    return starts


def annual_types() -> list[LeaveTypeRow]:
    """Leave types marked `uses_annual_balance`, lowest ext order first; ext rows with no production row are skipped."""
    exts = list(LeaveTypeExt.objects.filter(uses_annual_balance=True).order_by("order", "pk"))
    types = LeaveTypeRow.objects.in_bulk([e.pk for e in exts])
    return [types[e.pk] for e in exts if e.pk in types]


def annual_configured() -> bool:
    return bool(annual_types())


def _annual_type() -> LeaveTypeRow:
    types = annual_types()
    if not types:
        raise LedgerError(NOT_CONFIGURED)
    return types[0]


def _overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


@transaction.atomic
def ensure_grants(employee: Employee, today: date) -> None:
    """With the switch on, write the law's annual grant for the current employment year if nothing covers it.

    Past years are never filled in, and any grant of any leave type (old program included) counts as covering."""
    if not LeaveSettings.get().auto_annual_grant or not annual_configured():
        return
    Employee.objects.select_for_update().get(pk=employee.pk)
    leave_type = _annual_type()
    existing = rows.grants(employee.pk, annual_only=False)
    for start in _grant_starts(employee, today)[-1:]:
        end = entitlement.next_year_start(employee, start) - timedelta(days=1)
        if end < today:  # a leaver's last year is over: no back-filling
            continue
        if any(g.kind == GrantKind.AUTO and g.start == start for g in existing):
            continue
        # Only positive grants cover a year; reductions and carry-outs do not (spec §9).
        if any(g.days > 0 and _overlaps(g.start, g.end, start, end) for g in existing):
            continue
        ent = entitlement.entitled(employee, start)
        writes.add_grant(employee, leave_type, start, end, ent.days, "", GrantKind.AUTO, None, ent.breakdown)


def periods(employee: Employee, today: date) -> tuple[list[Period], list[LeaveRow]]:
    """Grant periods newest first, and the counted annual leaves that no period contains."""
    if not annual_configured():
        return [], []
    grants = rows.grants(employee.pk)
    counted = [lv for lv in rows.leaves(employee_ids=[employee.pk]) if lv.counts and lv.type_ext.uses_annual_balance]

    # Keys sorted (start, end) descending: the first key that contains a day is the latest-starting period.
    found: dict[tuple[date, date], tuple[list[GrantRow], list[LeaveRow]]] = {}
    for key in sorted({(g.start, g.end) for g in grants}, reverse=True):
        found[key] = ([g for g in grants if (g.start, g.end) == key], [])
    nowhere: list[LeaveRow] = []
    for lv in counted:
        target = next((key for key in found if key[0] <= lv.start <= key[1]), None)
        if target is None:
            nowhere.append(lv)
        else:
            found[target][1].append(lv)

    out: list[Period] = []
    for (start, end), (own_grants, own_leaves) in found.items():
        granted = sum(g.days for g in own_grants)
        taken = sum(lv.days for lv in own_leaves)
        out.append(
            Period(
                start=start,
                end=end,
                granted=granted,
                taken=taken,
                left=granted - taken,
                grants=own_grants,
                leaves=own_leaves,
                doubled=False,
                upcoming=start > today,
                current=start <= today <= end,
            )
        )
    for p in out:
        # One exact period is doubled when it holds 2+ positive AUTO/MANUAL grants (an auto grant plus a hand grant
        # for the same year). Adjustments and carry-ins never make a period doubled.
        same_period_positive = (
            sum(1 for g in p.grants if g.days > 0 and g.kind in (GrantKind.AUTO, GrantKind.MANUAL)) > 1
        )
        p.doubled = p.granted > 0 and (
            same_period_positive
            or any(q is not p and q.granted > 0 and _overlaps(q.start, q.end, p.start, p.end) for q in out)
        )
    return out, nowhere


def period_for(employee: Employee, day: date) -> Period | None:
    found, _ = periods(employee, timezone.localdate())
    return next((p for p in found if p.start <= day <= p.end), None)


def balance_on(employee: Employee, day: date, *, exclude_leave_id: int | None = None) -> int | None:
    """Days left in the period containing `day`; None when no period contains it."""
    period = period_for(employee, day)
    if period is None:
        return None
    left = period.left
    if exclude_leave_id is not None:
        left += sum(lv.days for lv in period.leaves if lv.id == exclude_leave_id)
    return left


def _reason(reason: str) -> str:
    reason = reason.strip()
    if not reason:
        raise LedgerError("Шалтгаан заавал бичнэ үү.")
    return reason


def _require_start(employee: Employee) -> None:
    if entitlement.employment_start(employee) is None:
        raise LedgerError(entitlement.MISSING_START)


def _check_range(start: date, end: date) -> None:
    if end < start:
        raise LedgerError("Дуусах огноо эхлэх огнооноос өмнө байж болохгүй.")


def _signed(days: int) -> str:
    return f"+{days}" if days > 0 else str(days)


def _log(employee: Employee, by: User, message: str) -> None:
    ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.CHANGED, message=message)


def _written(employee: Employee, grant_pk: int) -> GrantRow:
    return next(g for g in rows.grants(employee.pk) if g.id == grant_pk)


def _next_period(employee: Employee, start: date, end: date) -> tuple[date, date]:
    """The period a carry-over goes to: the next employment year, or the same length right after."""
    is_year = start in entitlement.year_starts(employee, start)
    if is_year and end == entitlement.next_year_start(employee, start) - timedelta(days=1):
        nxt = entitlement.next_year_start(employee, start)
        return nxt, entitlement.next_year_start(employee, nxt) - timedelta(days=1)
    to_start = end + timedelta(days=1)
    return to_start, to_start + timedelta(days=(end - start).days)


@transaction.atomic
def adjust(employee: Employee, period_start: date, period_end: date, days: int, reason: str, by: User) -> GrantRow:
    reason = _reason(reason)
    _check_range(period_start, period_end)
    Employee.objects.select_for_update().get(pk=employee.pk)
    if days == 0:
        raise LedgerError("Хоног 0 байж болохгүй.")
    leave_type = _annual_type()
    grant = writes.add_grant(employee, leave_type, period_start, period_end, days, reason, GrantKind.ADJUSTMENT, by)
    _log(
        employee,
        by,
        f"Амралтын эрх засварласан ({period_start} – {period_end}): {_signed(days)} хоног. {reason}",
    )
    return _written(employee, grant.pk)


@transaction.atomic
def manual_grant(employee: Employee, start: date, end: date, days: int, reason: str, by: User) -> GrantRow:
    reason = _reason(reason)
    _check_range(start, end)
    Employee.objects.select_for_update().get(pk=employee.pk)
    if days == 0:
        raise LedgerError("Хоног 0 байж болохгүй.")
    leave_type = _annual_type()
    grant = writes.add_grant(employee, leave_type, start, end, days, reason, GrantKind.MANUAL, by)
    _log(employee, by, f"Амралтын эрх нэмсэн ({start} – {end}): {_signed(days)} хоног. {reason}")
    return _written(employee, grant.pk)


@transaction.atomic
def carry_over(
    employee: Employee, period_start: date, period_end: date, days: int, reason: str, by: User
) -> tuple[GrantRow, GrantRow]:
    reason = _reason(reason)
    _require_start(employee)
    if days <= 0:
        raise LedgerError("Шилжүүлэх хоног 0-ээс их байна.")
    Employee.objects.select_for_update().get(pk=employee.pk)
    leave_type = _annual_type()
    found, _ = periods(employee, timezone.localdate())
    source = next((p for p in found if (p.start, p.end) == (period_start, period_end)), None)
    if source is None:
        raise LedgerError("Ажлын жил олдсонгүй.")
    if days > source.left:
        raise LedgerError("Үлдэгдлээс их хоног шилжүүлэх боломжгүй.")
    to_start, to_end = _next_period(employee, period_start, period_end)
    out = writes.add_grant(employee, leave_type, period_start, period_end, -days, reason, GrantKind.ADJUSTMENT, by)
    inn = writes.add_grant(employee, leave_type, to_start, to_end, days, reason, GrantKind.CARRY_OVER, by)
    _log(employee, by, f"Амралтын эрх шилжүүлсэн: {period_start} → {to_start}, {days} хоног. {reason}")
    return _written(employee, out.pk), _written(employee, inn.pk)
