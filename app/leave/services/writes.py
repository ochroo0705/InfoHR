"""Write layer for the production leave tables: the only code that writes them (D-017).

Every public function is atomic. A refused change raises WriteConflict with the user-facing
text; the caller shows that text as it is. Production ids come from the database sequences,
so nothing here sets a primary key.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from accounts.models import User
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from employees.models import ActivityEntry, ActivityKind
from employees.services.macs_writes import ListEntryInUse
from macs.models import Employee, Entitlement, LeaveAssign, LeaveTypeRow, LegalHoliday

from leave.models import GrantKind, LeaveExt, LeaveGrantExt, LeaveTypeExt
from leave.services.fmt import fmt_days

DUPLICATE = "Энэ чөлөө аль хэдийн бүртгэгдсэн байна"
CANCELLED_CLASH = "Ийм огноотой цуцлагдсан чөлөө бүртгэлтэй байна. Түүнийг дахин бүртгэнэ үү."
STALE = "Өөр хэрэглэгч өөрчилсөн байна, дахин ачаална уу"


class WriteConflict(Exception):
    """A refused write; the message is the user-facing text."""


@dataclass(frozen=True)
class AssignSnapshot:
    leave_type_id: int
    date1: date
    date2: date
    status: int | None
    adays: int | None
    comment: str | None


def snapshot(a: LeaveAssign) -> AssignSnapshot:
    return AssignSnapshot(
        leave_type_id=a.leave_type_id,
        date1=a.date1,
        date2=a.date2,
        status=a.status,
        adays=a.adays,
        comment=a.comment,
    )


def _key_row(employee: Employee, leave_type: LeaveTypeRow, start: date, end: date) -> LeaveAssign | None:
    """The one row that holds this unique key (employee, type, start, end), locked for the write."""
    return (
        LeaveAssign.objects.select_for_update()
        .filter(employee=employee, leave_type=leave_type, date1=start, date2=end)
        .first()
    )


def _save_ext(assign: LeaveAssign, **values: Any) -> LeaveExt:
    ext, _ = LeaveExt.objects.get_or_create(assign=assign)
    for field, value in values.items():
        setattr(ext, field, value)
    ext.save()
    return ext


@transaction.atomic
def record_assign(
    employee: Employee,
    leave_type: LeaveTypeRow,
    start: date,
    end: date,
    days: int,
    comment: str,
    by: User,
    override_reason: str = "",
) -> LeaveAssign:
    existing = _key_row(employee, leave_type, start, end)
    if existing is not None:
        if existing.status not in (LeaveAssign.CANCELLED, LeaveAssign.REJECTED):
            raise WriteConflict(DUPLICATE)
        # A cancelled or rejected row holds the key: bring it back instead of inserting a second one.
        existing.status = LeaveAssign.APPROVED
        existing.adays = days
        existing.comment = comment
        existing.save(update_fields=["status", "adays", "comment"])
        _save_ext(
            existing,
            mistake=False,
            cancel_reason="",
            override_reason=override_reason,
            created_by=by,
        )
        sync_vacation(existing.employee_id, start.year)
        return existing

    try:
        with transaction.atomic():
            assign = LeaveAssign.objects.create(
                employee=employee,
                leave_type=leave_type,
                date1=start,
                date2=end,
                comment=comment,
                status=LeaveAssign.APPROVED,
                adays=days,
            )
    except IntegrityError as exc:
        raise WriteConflict(DUPLICATE) from exc
    LeaveExt.objects.create(assign=assign, override_reason=override_reason, created_by=by)
    sync_vacation(assign.employee_id, start.year)
    return assign


def _locked_unchanged(a: LeaveAssign, loaded: AssignSnapshot) -> LeaveAssign:
    """Lock the row and refuse if it differs from what the user loaded (another program or user changed it)."""
    row = LeaveAssign.objects.select_for_update().get(pk=a.pk)
    if snapshot(row) != loaded:
        raise WriteConflict(STALE)
    return row


@transaction.atomic
def update_assign(
    a: LeaveAssign,
    loaded: AssignSnapshot,
    *,
    leave_type: LeaveTypeRow,
    start: date,
    end: date,
    days: int,
    comment: str,
    by: User,
    override_reason: str = "",
) -> LeaveAssign:
    row = _locked_unchanged(a, loaded)
    old_year = row.date1.year
    clash = (
        LeaveAssign.objects.select_for_update()
        .filter(employee_id=row.employee_id, leave_type=leave_type, date1=start, date2=end)
        .exclude(pk=row.pk)
        .first()
    )
    if clash is not None:
        if clash.status == LeaveAssign.CANCELLED:
            raise WriteConflict(CANCELLED_CLASH)
        raise WriteConflict(DUPLICATE)
    row.leave_type = leave_type
    row.date1 = start
    row.date2 = end
    row.adays = days
    row.comment = comment
    try:
        with transaction.atomic():
            row.save(update_fields=["leave_type", "date1", "date2", "adays", "comment"])
    except IntegrityError as exc:
        raise WriteConflict(DUPLICATE) from exc
    _save_ext(row, override_reason=override_reason)
    for year in {old_year, start.year}:
        sync_vacation(row.employee_id, year)
    return row


@transaction.atomic
def cancel_assign(a: LeaveAssign, loaded: AssignSnapshot, reason: str, *, mistake: bool, by: User) -> LeaveAssign:
    row = _locked_unchanged(a, loaded)
    row.status = LeaveAssign.CANCELLED
    row.save(update_fields=["status"])
    _save_ext(row, cancel_reason=reason, mistake=mistake)
    sync_vacation(row.employee_id, row.date1.year)
    return row


@transaction.atomic
def write_old_style_assign(
    employee: Employee,
    leave_type: LeaveTypeRow,
    start: date,
    end: date,
    *,
    status: int | None,
    adays: int | None,
    comment: str,
) -> LeaveAssign:
    """A row exactly as the old program writes it: no ext row. Used by the demo seed only."""
    return LeaveAssign.objects.create(
        employee=employee, leave_type=leave_type, date1=start, date2=end, status=status, adays=adays, comment=comment
    )


@transaction.atomic
def write_old_style_grant(
    employee: Employee, leave_type: LeaveTypeRow, start: date, end: date, days: int, comment: str
) -> Entitlement:
    """A grant exactly as the old program writes it: no ext row. Used by the demo seed only."""
    return Entitlement.objects.create(
        employee=employee, leave_type=leave_type, date1=start, date2=end, ent_days=days, comment=comment
    )


@transaction.atomic
def add_grant(
    employee: Employee,
    leave_type: LeaveTypeRow,
    start: date,
    end: date,
    days: int,
    comment: str,
    kind: GrantKind,
    by: User | None,
    breakdown: str = "",
) -> Entitlement:
    grant = Entitlement.objects.create(
        employee=employee,
        leave_type=leave_type,
        date1=start,
        date2=end,
        ent_days=days,
        comment=comment,
    )
    LeaveGrantExt.objects.create(grant=grant, kind=kind, breakdown=breakdown, created_by=by)
    return grant


@transaction.atomic
def save_leave_type(name: str, ext_values: dict[str, Any], *, row: LeaveTypeRow | None = None) -> LeaveTypeRow:
    if row is None:
        row = LeaveTypeRow.objects.create(name=name)
    else:
        row.name = name
        row.save(update_fields=["name"])
    LeaveTypeExt.objects.update_or_create(leave_type=row, defaults=ext_values)
    return row


@transaction.atomic
def delete_leave_type(row: LeaveTypeRow) -> None:
    LeaveTypeRow.objects.select_for_update().filter(pk=row.pk).first()
    count = LeaveAssign.objects.filter(leave_type=row).count() + Entitlement.objects.filter(leave_type=row).count()
    if count:
        raise ListEntryInUse(count)
    LeaveTypeExt.objects.filter(pk=row.pk).delete()
    LeaveTypeRow.objects.filter(pk=row.pk).delete()


@dataclass(frozen=True)
class _Run:
    name: str
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _span(start: date, end: date) -> list[date]:
    return [start + timedelta(n) for n in range((end - start).days + 1)]


def _runs(dates: dict[date, str], year: int) -> list[_Run]:
    """Maximal runs of consecutive calendar days that share one name, in date order.

    A run never crosses the edge of `year`: the part of a row outside the year stays its own row.
    """
    runs: list[_Run] = []
    for day in sorted(dates):
        name = dates[day]
        last = runs[-1] if runs else None
        if (
            last is not None
            and last.name == name
            and last.end + timedelta(days=1) == day
            and (last.end.year == year) == (day.year == year)
        ):
            runs[-1] = _Run(name, last.start, day)
        else:
            runs.append(_Run(name, day, day))
    return runs


def _insert_run(run: _Run) -> None:
    LegalHoliday.objects.create(name=run.name, start_date=run.start, end_date=run.end, hdays=run.days)


@transaction.atomic
def set_holiday_dates(year: int, dates: dict[date, str]) -> None:
    """Change the holidays of one year to `dates` (every holiday day -> its name), touching as little as possible.

    A day is changed when it is added, removed or renamed. Only stored rows that contain a changed day are
    rebuilt; every other row keeps its id and dates, even when it is adjacent with the same name. A rebuilt row
    keeps its days outside `year` as a separate row (the first such piece reuses the row's id). Added days get
    one new row per run of same-name days, with hdays = run length.
    """
    if any(day.year != year for day in dates):
        raise ValueError("Бүх огноо сонгосон жилийнх байх ёстой.")
    rows = list(
        LegalHoliday.objects.select_for_update().filter(
            start_date__lte=date(year, 12, 31), end_date__gte=date(year, 1, 1)
        )
    )
    current: dict[date, str] = {}
    for row in rows:
        for day in _span(max(row.start_date, date(year, 1, 1)), min(row.end_date, date(year, 12, 31))):
            current[day] = row.name
    changed = {day for day in current.keys() | dates.keys() if current.get(day) != dates.get(day)}
    if not changed:
        return

    affected = [row for row in rows if any(row.start_date <= day <= row.end_date for day in changed)]
    covered: set[date] = set()
    for row in affected:
        span = _span(row.start_date, row.end_date)
        covered.update(span)
        names = {day: (dates.get(day) if day in changed else row.name) for day in span}
        pieces = _runs({day: name for day, name in names.items() if name is not None}, year)
        outside = next((piece for piece in pieces if piece.start.year != year), None)
        if outside is None:
            row.delete()
        else:
            pieces.remove(outside)
            row.name, row.start_date, row.end_date, row.hdays = outside.name, outside.start, outside.end, outside.days
            row.save(update_fields=["name", "start_date", "end_date", "hdays"])
        for piece in pieces:
            _insert_run(piece)

    added = {day: name for day, name in dates.items() if day in changed and day not in covered}
    for run in _runs(added, year):
        _insert_run(run)


@transaction.atomic
def recount_assigns(days: set[date], by: User) -> int:
    """Recount working days of Info HR leaves that cover any of `days` after the holiday list changed.

    Only rows with an ext row, status 1 or NULL, are touched; old-program rows and cancelled ones keep their days.
    Returns how many rows changed.
    """
    from leave.services import calendar  # calendar imports this module

    if not days:
        return 0
    changed = 0
    covering = (
        LeaveAssign.objects.select_for_update()
        .filter(pk__in=LeaveExt.objects.values("pk"))
        .filter(Q(status=LeaveAssign.APPROVED) | Q(status__isnull=True))
        .filter(date1__lte=max(days), date2__gte=min(days))
        .select_related("employee", "leave_type")
    )
    for row in covering:
        if not any(row.date1 <= d <= row.date2 for d in days):
            continue
        new = calendar.working_days(row.date1, row.date2)
        if row.adays == new:
            continue
        old = row.adays if row.adays is not None else calendar.working_days(row.date1, row.date2)
        before = f"{row.leave_type.name} {row.date1:%Y-%m-%d}–{row.date2:%Y-%m-%d} ({fmt_days(old)} ажлын өдөр)"
        row.adays = new
        row.save(update_fields=["adays"])
        sync_vacation(row.employee_id, row.date1.year)
        ActivityEntry.objects.create(
            employee=row.employee,
            by=by,
            kind=ActivityKind.CHANGED,
            message=f"Баярын өдөр өөрчлөгдсөн тул дахин тооцсон: {before} → {fmt_days(new)} ажлын өдөр",
        )
        changed += 1
    return changed


@transaction.atomic
def sync_vacation(employee_id: int, year: int) -> None:
    """Keep `emp_vacation` at one total row per employee per year for annual leave (Q-13; user 2026-10-19).

    Totals every counted annual leave that starts in `year` (Info HR and old-program rows alike): `v_day` = days,
    `mmonth` = month of the first leave, dates = earliest start and latest end, `is_vacation` = 'yes'. With no annual
    leave left the row goes back to 'no', 0 days, no dates; it is never deleted. An existing row for the year (e.g.
    the empty month-1 row the old INSERT_VACATION procedure made) is updated, not duplicated.
    """
    from leave.services import calendar  # calendar imports this module

    annual_types = LeaveTypeExt.objects.filter(uses_annual_balance=True).values("pk")
    leaves = (
        LeaveAssign.objects.filter(employee_id=employee_id, leave_type_id__in=annual_types)
        .filter(Q(status=LeaveAssign.APPROVED) | Q(status__isnull=True))
        .filter(date1__gte=date(year, 1, 1), date1__lte=date(year, 12, 31))
        .order_by("date1")
    )
    rows = list(leaves)
    days = sum(r.adays if r.adays is not None else calendar.working_days(r.date1, r.date2) for r in rows)
    dep = Employee.objects.filter(pk=employee_id).values_list("department_id", flat=True).first()
    with connection.cursor() as cur:
        cur.execute(
            "SELECT mmonth FROM emp_vacation WHERE emp_ident = %s AND myear = %s ORDER BY mmonth FOR UPDATE",
            [employee_id, year],
        )
        months = [m for (m,) in cur.fetchall()]
        if not rows and not months:
            return  # nothing taken and nothing recorded: no row needed
        month = rows[0].date1.month if rows else months[0]
        values = [days, "yes", rows[0].date1, max(r.date2 for r in rows)] if rows else [0, "no", None, None]
        if not months:
            cur.execute(
                "INSERT INTO emp_vacation (emp_ident, dep_ident, xmonth, myear, mmonth, v_day, is_vacation,"
                " start_date, end_date) VALUES (%s, %s, 0, %s, %s, %s, %s, %s, %s)",
                [employee_id, dep, year, month, *values],
            )
            return
        # Update the row already holding the target month, else the year's first row (moved to the new month).
        target = month if month in months else months[0]
        cur.execute(
            "UPDATE emp_vacation SET mmonth = %s, dep_ident = COALESCE(%s, dep_ident), v_day = %s, is_vacation = %s,"
            " start_date = %s, end_date = %s WHERE emp_ident = %s AND myear = %s AND mmonth = %s",
            [month, dep, *values, employee_id, year, target],
        )
