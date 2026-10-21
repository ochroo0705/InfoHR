"""The only doorway for writing dated history (spec §3). Every function is atomic."""

from datetime import date
from decimal import Decimal
from typing import Any, cast

from accounts.models import User
from django.db import connection, transaction
from django.utils import timezone
from psycopg.types.range import DateRange

from employees.models import (
    ActivityEntry,
    ActivityKind,
    ContractType,
    Department,
    Employee,
    EmployeeType,
    Event,
    HrOrder,
    JobRecord,
    OrderType,
    Position,
    SalaryRecord,
)
from employees.money import group
from employees.services import macs_writes, orders, personal_writes
from employees.services.display import shown
from employees.services.orders import OrderError

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


def _no_end_if_open_ended(values: dict[str, Any], current_type: str | None = None) -> dict[str, Any]:
    """An open-ended contract has no end date (models.contract_errors): drop any typed one."""
    if values.get("contract_type", current_type) == ContractType.OPEN_ENDED:
        return {**values, "contract_end": None}
    return values


@transaction.atomic
def hire(
    values: dict[str, Any],
    ext_values: dict[str, Any],
    *,
    start: date,
    job: dict[str, Any],
    salary: Decimal | None,
    by: User,
    address: dict[str, object] | None = None,
    contact: dict[str, object] | None = None,
    order_number: str = "",
    order_date: date | None = None,
    order_summary: str = "",
    order_issued_by: str = "",
) -> Employee:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [HIRE_LOCK_KEY])
    employee = macs_writes.create_employee(
        values, {**ext_values, "setup_required": True}, code=macs_writes.next_code(), by=by
    )
    job = _no_end_if_open_ended(job)
    if "emptype" not in job:  # D-028: the type is stored; a hire is probation (9) when a probation end is given
        job = {
            **job,
            "emptype": 9
            if ext_values.get("probation_end")
            else 5
            if job.get("contract_type") == ContractType.FIXED_TERM
            else 1,
        }
    JobRecord.objects.create(
        employee=employee, period=DateRange(start, None, "[)"), change_type="hire", created_by=by, **job
    )
    # Probation months count from this hire's start (not first_hire_date); needs the hire job row just created.
    months = macs_writes.probation_months(
        macs_writes.current_employment_start(employee), ext_values.get("probation_end")
    )
    macs_writes.update_employee_columns(employee, {"probation_months": months})
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
            changes=[{"field": "Үндсэн цалин", "old": "", "new": group(salary)}],
        )
    macs_writes.sync_current(employee, timezone.localdate())
    macs_writes.record_movement(employee, "in", start)
    history_id = macs_writes.snapshot_history(employee, start)
    order = orders.create_for_change(
        employee=employee,
        event=None,
        is_hire=True,
        order_type=OrderType.HIRED.value,
        number="",
        date=None,
        summary="",
        issued_by="",
        by=by,
    )
    HrOrder.objects.filter(pk=order.pk).update(history_id=history_id)
    if order_number.strip() or order_date is not None:  # registered after the history row is linked to it
        order.refresh_from_db()
        if not order_number.strip() or order_date is None:
            raise OrderError({"number" if not order_number.strip() else "date": "Дугаар болон огноог хамт оруулна уу."})
        orders.register(
            order, number=order_number, date=order_date, summary=order_summary, issued_by=order_issued_by, by=by
        )
    # The optional first address and emergency contact (production rows) belong to this hire: a refused one
    # raises PersonalConflict and the whole hire rolls back.
    if address is not None:
        personal_writes.add("address", employee, address, {}, by=by)
    if contact is not None:
        personal_writes.add("contact", employee, contact, {}, by=by)
    return employee


@transaction.atomic
def start_from_macs(
    employee: Employee,
    *,
    by: User,
    effective: date,
    department: Department | None = None,
    position: Position | None = None,
) -> None:
    """Give a MACS-only employee (no HR job history, QC 1d) its starting job and salary records, taken from the
    MACS row. Idempotent: does nothing once the job history exists. Never writes the MACS row, so the MACS
    leave and leaving flags stay as they are (QC 1e)."""
    # Local import: listing imports this module at the top.
    from employees.listing import legacy_job

    employee = Employee.objects.select_for_update().get(pk=employee.pk)  # read the MACS row under the lock
    if employee.job_records.exists():
        return
    dept = employee.department or department
    pos = employee.position or position
    if dept is None or pos is None:
        raise HistoryError("Хэлтэс, албан тушаалыг заавал сонгоно уу.")
    # The period starts at the contract start, else the first hire, else the event; never after the event or
    # today, so a planned first event does not turn a working employee into "upcoming".
    start = min(employee.contract_start or employee.first_hire_date or effective, effective, timezone.localdate())
    contract = employee.emptype == 5
    fixed_term = contract and employee.contract_end is not None  # a fixed-term contract needs an end date
    template = legacy_job(employee)  # status and contract dates, read the same way the list shows them
    JobRecord.objects.create(
        employee=employee,
        period=DateRange(start, None, "[)"),
        department=dept,
        position=pos,
        status=template.status,
        employee_type=EmployeeType.CONTRACT if contract else EmployeeType.FULL_TIME,
        contract_type=ContractType.FIXED_TERM if fixed_term else ContractType.OPEN_ENDED,
        emptype=employee.emptype if employee.emptype in (1, 5, 6, 9) else None,
        contract_no=employee.contract_no or "",
        contract_start=employee.contract_start,
        contract_end=employee.contract_end if fixed_term else None,
        change_type="opening",
        created_by=by,
    )
    if employee.salary and not employee.salary_records.exists():
        SalaryRecord.objects.create(
            employee=employee,
            period=DateRange(start, None, "[)"),
            base_salary=employee.salary,
            change_type="opening",
            created_by=by,
        )
    ActivityEntry.objects.create(
        employee=employee,
        by=by,
        kind=ActivityKind.HISTORY,
        message=f"Эхлэх ажлын түүхийг MACS-ийн мэдээллээс авав ({start:%Y-%m-%d}-аас).",
    )


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
    macs_writes.sync_current(employee, timezone.localdate())
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
        old = group(current.base_salary)
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
            changes=[{"field": "Үндсэн цалин", "old": old, "new": group(amount)}],
        )
    macs_writes.sync_current(employee, timezone.localdate())
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
    for employee_id in sorted({r.employee_id for r in records}):
        macs_writes.sync_current(Employee.objects.get(pk=employee_id), timezone.localdate())


def _require_reason(reason: str) -> str:
    if not reason.strip():
        raise HistoryError("Засварын шалтгааныг заавал бичнэ үү.")
    return reason.strip()


@transaction.atomic
def correct_job(record: JobRecord, *, changes: dict[str, Any], reason: str, by: User) -> JobRecord:
    reason = _require_reason(reason)
    Employee.objects.select_for_update().get(pk=record.employee_id)
    record = JobRecord.objects.select_for_update().get(pk=record.pk)
    changes = _no_end_if_open_ended(changes, record.contract_type)
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
    macs_writes.sync_current(record.employee, timezone.localdate())
    return record


@transaction.atomic
def correct_salary(record: SalaryRecord, *, amount: Decimal, reason: str, by: User) -> SalaryRecord:
    reason = _require_reason(reason)
    Employee.objects.select_for_update().get(pk=record.employee_id)
    record = SalaryRecord.objects.select_for_update().get(pk=record.pk)
    old = group(record.base_salary)
    record.base_salary = amount
    record.save(update_fields=["base_salary"])
    ActivityEntry.objects.create(
        employee=record.employee,
        by=by,
        kind=ActivityKind.CORRECTION,
        sensitive=True,
        message=f"Засвар: {reason}",
        changes=[{"field": "Үндсэн цалин", "old": old, "new": group(amount)}],
    )
    macs_writes.sync_current(record.employee, timezone.localdate())
    return record
