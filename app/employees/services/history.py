"""The only doorway for writing dated history (spec §3). Every function is atomic."""

from datetime import date
from decimal import Decimal
from typing import Any, cast

from accounts.models import User
from django.db import connection, transaction
from django.utils import timezone
from psycopg.types.range import DateRange

from employees.models import ActivityEntry, ActivityKind, Employee, Event, JobRecord, SalaryRecord
from employees.services.display import shown

# Fixed key for the advisory lock that serialises employee-code generation in hire().
HIRE_LOCK_KEY = 7301


class HistoryError(Exception):
    """A refused change; the message is shown to the user."""


def _label(model: type[JobRecord] | type[SalaryRecord], field: str) -> str:
    return str(getattr(model._meta.get_field(field), "verbose_name", field))


def _show(value: Any, model: type[JobRecord] | type[SalaryRecord] = JobRecord, field: str = "") -> str:
    if not field:
        return "" if value is None else str(value)
    return shown(model._meta.get_field(field), value)


def _containing(qs: Any, day: date) -> Any:
    return qs.filter(period__contains=day).first()


def job_on(employee: Employee, day: date) -> JobRecord | None:
    return cast(JobRecord | None, _containing(employee.job_records.all(), day))


def salary_on(employee: Employee, day: date) -> SalaryRecord | None:
    return cast(SalaryRecord | None, _containing(employee.salary_records.all(), day))


def _split(record: Any, effective: date) -> Any:
    """Close `record` at `effective` and return an unsaved copy starting at `effective`."""
    if record.period.lower == effective:
        raise HistoryError("Энэ өдрөөс эхэлсэн хугацаа аль хэдийн байна. Засвар ашиглана уу.")
    upper = record.period.upper
    record.period = DateRange(record.period.lower, effective, "[)")
    record.save(update_fields=["period"])
    record.pk = None
    record.id = None
    record.period = DateRange(effective, upper, "[)")
    return record


def _backdated(effective: date) -> str:
    return " (буцаан хугацаагаар)" if effective < timezone.localdate() else ""


@transaction.atomic
def hire(employee: Employee, *, start: date, job: dict[str, Any], salary: Decimal | None, by: User) -> Employee:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [HIRE_LOCK_KEY])
    employee.code = Employee.next_code()
    employee.created_by = employee.updated_by = by
    employee.setup_required = True
    employee.full_clean(exclude=["code"])
    employee.save()
    JobRecord.objects.create(
        employee=employee, period=DateRange(start, None, "[)"), change_type="hire", created_by=by, **job
    )
    ActivityEntry.objects.create(
        employee=employee,
        by=by,
        kind=ActivityKind.CREATED,
        message=f"Ажилтан бүртгэв. Ажилд орсон: {start:%Y-%m-%d}",
    )
    if salary is not None:
        SalaryRecord.objects.create(
            employee=employee,
            period=DateRange(start, None, "[)"),
            base_salary=salary,
            change_type="hire",
            created_by=by,
        )
        ActivityEntry.objects.create(
            employee=employee,
            by=by,
            kind=ActivityKind.HISTORY,
            sensitive=True,
            message="Үндсэн цалин тогтоов",
            changes=[{"field": "Үндсэн цалин", "old": "", "new": str(salary)}],
        )
    return employee


@transaction.atomic
def change_job(
    employee: Employee,
    *,
    effective: date,
    changes: dict[str, Any],
    change_type: str,
    note: str,
    by: User,
    event: Event | None = None,
    log: bool = True,
) -> JobRecord:
    for field in changes:
        if field not in JobRecord.JOB_FIELDS:
            raise HistoryError(f"'{field}' талбарыг засах боломжгүй.")
    Employee.objects.select_for_update().get(pk=employee.pk)
    current = _containing(employee.job_records.select_for_update(), effective)
    if current is None:
        raise HistoryError("Энэ өдөр ажилтанд ажлын түүх байхгүй байна.")
    old = {field: getattr(current, field) for field in changes}
    record: JobRecord = _split(current, effective)
    for field, value in changes.items():
        setattr(record, field, value)
    record.change_type, record.note, record.created_by = change_type, note, by
    record.event = event
    record.save()
    if log:
        ActivityEntry.objects.create(
            employee=employee,
            by=by,
            kind=ActivityKind.HISTORY,
            message=f"{effective:%Y-%m-%d}-аас өөрчлөгдөв{_backdated(effective)}. {note}".strip(),
            changes=[
                {"field": _label(JobRecord, f), "old": _show(old[f], JobRecord, f), "new": _show(v, JobRecord, f)}
                for f, v in changes.items()
            ],
        )
    return record


@transaction.atomic
def change_salary(
    employee: Employee,
    *,
    effective: date,
    amount: Decimal,
    change_type: str,
    note: str,
    by: User,
    first_only: bool = False,
    event: Event | None = None,
    log: bool = True,
) -> SalaryRecord:
    Employee.objects.select_for_update().get(pk=employee.pk)
    if first_only and employee.salary_records.exists():
        raise HistoryError("Цалин аль хэдийн тогтоогдсон байна.")
    current = _containing(employee.salary_records.select_for_update(), effective)
    if current is None:
        if employee.salary_records.filter(period__startswith__gt=effective).exists():
            raise HistoryError("Энэ өдрөөс хойш цалингийн түүх байна. Засвар ашиглана уу.")
        record = SalaryRecord(employee=employee, period=DateRange(effective, None, "[)"))
        old = ""
    else:
        old = str(current.base_salary)
        record = _split(current, effective)
    record.base_salary, record.change_type, record.note, record.created_by = amount, change_type, note, by
    record.event = event
    record.save()
    if log:
        ActivityEntry.objects.create(
            employee=employee,
            by=by,
            kind=ActivityKind.HISTORY,
            sensitive=True,
            message=f"{effective:%Y-%m-%d}-аас цалин өөрчлөгдөв{_backdated(effective)}. {note}".strip(),
            changes=[{"field": "Үндсэн цалин", "old": old, "new": str(amount)}],
        )
    return record


@transaction.atomic
def undo(records: list[JobRecord | SalaryRecord]) -> None:
    """Remove history rows and extend the previous period over the gap (used when an event is cancelled)."""
    for employee_id in sorted({r.employee_id for r in records}):
        Employee.objects.select_for_update().get(pk=employee_id)
    for stale in sorted(records, key=lambda r: r.period.lower, reverse=True):
        model = type(stale)
        record = model.objects.select_for_update().get(pk=stale.pk)
        lower, upper = record.period.lower, record.period.upper
        siblings = model.objects.filter(employee_id=record.employee_id)
        if siblings.filter(period__startswith__gt=lower).exclude(pk=record.pk).exists():
            raise HistoryError("Энэ өөрчлөлтөөс хойш өөр өөрчлөлт бий. Эхлээд сүүлийнхийг цуцална уу.")
        previous = siblings.filter(period__endswith=lower).first()
        record.delete()
        if previous is not None:
            previous.period = DateRange(previous.period.lower, upper, "[)")
            previous.save(update_fields=["period"])


def _require_reason(reason: str) -> str:
    if not reason.strip():
        raise HistoryError("Засварын шалтгааныг заавал бичнэ үү.")
    return reason.strip()


@transaction.atomic
def correct_job(record: JobRecord, *, changes: dict[str, Any], reason: str, by: User) -> JobRecord:
    reason = _require_reason(reason)
    Employee.objects.select_for_update().get(pk=record.employee_id)
    record = JobRecord.objects.select_for_update().get(pk=record.pk)
    diff = []
    for field, value in changes.items():
        if field not in JobRecord.JOB_FIELDS:
            raise HistoryError(f"'{field}' талбарыг засах боломжгүй.")
        old = getattr(record, field)
        if old != value:
            diff.append(
                {
                    "field": _label(JobRecord, field),
                    "old": _show(old, JobRecord, field),
                    "new": _show(value, JobRecord, field),
                }
            )
            setattr(record, field, value)
    record.save()
    ActivityEntry.objects.create(
        employee=record.employee, by=by, kind=ActivityKind.CORRECTION, message=f"Засвар: {reason}", changes=diff
    )
    return record


@transaction.atomic
def correct_salary(record: SalaryRecord, *, amount: Decimal, reason: str, by: User) -> SalaryRecord:
    reason = _require_reason(reason)
    Employee.objects.select_for_update().get(pk=record.employee_id)
    record = SalaryRecord.objects.select_for_update().get(pk=record.pk)
    old = str(record.base_salary)
    record.base_salary = amount
    record.save(update_fields=["base_salary"])
    ActivityEntry.objects.create(
        employee=record.employee,
        by=by,
        kind=ActivityKind.CORRECTION,
        sensitive=True,
        message=f"Засвар: {reason}",
        changes=[{"field": "Үндсэн цалин", "old": old, "new": str(amount)}],
    )
    return record
