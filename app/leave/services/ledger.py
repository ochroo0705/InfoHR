"""Annual-leave ledger: grants minus recorded leave, always computed (spec L-5)."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from accounts.models import User
from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, Employee, JobStatus
from employees.services import history

from leave.models import GrantKind, Leave, LeaveGrant, LeaveStatus
from leave.services import entitlement
from leave.services.fmt import fmt_days


class LedgerError(Exception):
    """A refused change; the message is shown to the user."""


@dataclass
class YearSummary:
    year_start: date
    year_end: date
    granted: Decimal
    taken: Decimal
    left: Decimal
    grants: list[LeaveGrant]
    leaves: list[Leave]
    upcoming: bool = False  # next year, shown only because days were carried into it


def _grant_starts(employee: Employee, today: date) -> list[date]:
    """Leave-year starts up to `today`, none starting after the person left."""
    starts = entitlement.year_starts(employee, today)
    job = history.job_on(employee, today)
    if job is not None and job.status == JobStatus.LEFT:
        starts = [s for s in starts if s < job.period.lower]
    return starts


@transaction.atomic
def ensure_grants(employee: Employee, today: date) -> None:
    Employee.objects.select_for_update().get(pk=employee.pk)
    have = set(LeaveGrant.objects.filter(employee=employee, kind=GrantKind.AUTO).values_list("year_start", flat=True))
    for start in _grant_starts(employee, today):
        if start not in have:
            ent = entitlement.entitled(employee, start)
            LeaveGrant.objects.create(
                employee=employee, year_start=start, days=ent.days, kind=GrantKind.AUTO, breakdown=ent.breakdown
            )


def _annual_leaves(employee: Employee, year_start: date) -> QuerySet[Leave]:
    return Leave.objects.filter(
        employee=employee, year_start=year_start, status=LeaveStatus.RECORDED, leave_type__uses_annual_balance=True
    )


def balance(employee: Employee, year_start: date, *, exclude_leave_id: int | None = None) -> Decimal:
    granted = LeaveGrant.objects.filter(employee=employee, year_start=year_start).aggregate(s=Sum("days"))[
        "s"
    ] or Decimal(0)
    leaves = _annual_leaves(employee, year_start)
    if exclude_leave_id is not None:
        leaves = leaves.exclude(pk=exclude_leave_id)
    taken = leaves.aggregate(s=Sum("working_days"))["s"] or Decimal(0)
    return Decimal(granted) - Decimal(taken)


def pending_grant(employee: Employee, year_start: date) -> Decimal:
    """The auto grant a not-yet-started year will get; nothing is written (a preview must not create grants)."""
    if LeaveGrant.objects.filter(employee=employee, year_start=year_start, kind=GrantKind.AUTO).exists():
        return Decimal(0)
    if year_start not in _grant_starts(employee, year_start):
        return Decimal(0)
    return entitlement.entitled(employee, year_start).days


def summaries(employee: Employee, today: date) -> list[YearSummary]:
    ensure_grants(employee, today)
    starts = _grant_starts(employee, today)
    out: list[YearSummary] = []
    for i, start in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else entitlement.next_year_start(employee, start)
        grants = list(LeaveGrant.objects.filter(employee=employee, year_start=start).order_by("created_at"))
        leaves = list(_annual_leaves(employee, start).select_related("leave_type").order_by("start_date"))
        granted = sum((g.days for g in grants), Decimal(0))
        taken = sum((lv.working_days for lv in leaves), Decimal(0))
        out.append(YearSummary(start, nxt - timedelta(days=1), granted, taken, granted - taken, grants, leaves))
    if starts:
        upcoming = entitlement.next_year_start(employee, starts[-1])
        grants = list(LeaveGrant.objects.filter(employee=employee, year_start=upcoming).order_by("created_at"))
        if grants:
            granted = sum((g.days for g in grants), Decimal(0))
            end = entitlement.next_year_start(employee, upcoming) - timedelta(days=1)
            out.append(YearSummary(upcoming, end, granted, Decimal(0), granted, grants, [], upcoming=True))
    return list(reversed(out))


def _check_year(employee: Employee, year_start: date, *, allow_upcoming: bool = False) -> None:
    starts = entitlement.year_starts(employee, timezone.localdate())
    if allow_upcoming and starts:
        starts.append(entitlement.next_year_start(employee, starts[-1]))
    if year_start not in starts:
        raise LedgerError("Ажлын жил олдсонгүй.")


def _reason(reason: str) -> str:
    reason = reason.strip()
    if not reason:
        raise LedgerError("Шалтгаан заавал бичнэ үү.")
    return reason


def _log(employee: Employee, by: User, message: str) -> None:
    ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.CHANGED, message=message)


@transaction.atomic
def adjust(employee: Employee, year_start: date, days: Decimal, reason: str, by: User) -> LeaveGrant:
    reason = _reason(reason)
    if days == 0:
        raise LedgerError("Хоног 0 байж болохгүй.")
    _check_year(employee, year_start, allow_upcoming=True)
    grant = LeaveGrant.objects.create(
        employee=employee,
        year_start=year_start,
        days=days,
        kind=GrantKind.ADJUSTMENT,
        reason=reason,
        created_by=by,
    )
    _log(
        employee,
        by,
        f"Амралтын эрх засварласан ({year_start} ажлын жил): {fmt_days(days, signed=True)} хоног. {reason}",
    )
    return grant


@transaction.atomic
def carry_over(
    employee: Employee, from_year: date, days: Decimal, reason: str, by: User
) -> tuple[LeaveGrant, LeaveGrant]:
    reason = _reason(reason)
    if days <= 0:
        raise LedgerError("Шилжүүлэх хоног 0-ээс их байна.")
    Employee.objects.select_for_update().get(pk=employee.pk)
    _check_year(employee, from_year)
    if days > balance(employee, from_year):
        raise LedgerError("Үлдэгдлээс их хоног шилжүүлэх боломжгүй.")
    to_year = entitlement.next_year_start(employee, from_year)
    out = LeaveGrant.objects.create(
        employee=employee, year_start=from_year, days=-days, kind=GrantKind.ADJUSTMENT, reason=reason, created_by=by
    )
    inn = LeaveGrant.objects.create(
        employee=employee, year_start=to_year, days=days, kind=GrantKind.CARRY_OVER, reason=reason, created_by=by
    )
    _log(employee, by, f"Амралтын эрх шилжүүлсэн: {from_year} → {to_year}, {fmt_days(days)} хоног. {reason}")
    return out, inn
