"""The only doorway for HR events (spec B). Every function is atomic."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.db import transaction
from django.utils import timezone
from macs.models import FiredReason

from employees.models import (
    ActivityEntry,
    ActivityKind,
    ChangeType,
    ContractType,
    Department,
    Employee,
    Event,
    EventType,
    JobRecord,
    JobStatus,
    LeaveKind,
    Position,
    contract_errors,
    ensure_ext,
)
from employees.services import history, macs_writes, orders
from employees.services.history import HistoryError
from employees.services.orders import OrderError

_PLACEMENT = ("position", "department", "manager")
_CONTRACT = ("emptype", "contract_type", "contract_no", "contract_start", "contract_end")
ALLOWED_FIELDS: dict[str, tuple[str, ...]] = {
    EventType.TRANSFER: _PLACEMENT,
    EventType.PROMOTION: _PLACEMENT,
    EventType.DEMOTION: _PLACEMENT,
    EventType.SALARY_CHANGE: (),
    EventType.CONTRACT: _CONTRACT,
    EventType.LEAVE_START: (),
    EventType.LEAVE_RETURN: (),
    EventType.TERMINATION: (),
    EventType.REHIRE: (*_PLACEMENT, "employee_type", *_CONTRACT),
}
# Same fields, shown as one menu item and one form with a type choice (scoping D-011).
PLACEMENT_TYPES = (EventType.TRANSFER, EventType.PROMOTION, EventType.DEMOTION)
PLACEMENT_LABEL = "Албан тушаал, байршил өөрчлөх"
SALARY_TYPES = (
    EventType.TRANSFER,
    EventType.PROMOTION,
    EventType.DEMOTION,
    EventType.SALARY_CHANGE,
    EventType.REHIRE,
)
NEW_STATUS = {
    EventType.LEAVE_START: JobStatus.LONG_LEAVE,
    EventType.LEAVE_RETURN: JobStatus.ACTIVE,
    EventType.TERMINATION: JobStatus.LEFT,
    EventType.REHIRE: JobStatus.ACTIVE,
}
REQUIRED_STATUS = {
    EventType.LEAVE_START: JobStatus.ACTIVE,
    EventType.LEAVE_RETURN: JobStatus.LONG_LEAVE,
}
REASON_CHOICES: dict[str, Any] = {EventType.LEAVE_START: LeaveKind}
_IN_SERVICE = (
    EventType.TRANSFER,
    EventType.PROMOTION,
    EventType.DEMOTION,
    EventType.SALARY_CHANGE,
    EventType.CONTRACT,
)
# Which events make sense for today's state (listing.Row.state); the service still validates on the effective date.
AVAILABLE: dict[str, tuple[str, ...]] = {
    "active": (*_IN_SERVICE, EventType.LEAVE_START, EventType.TERMINATION),
    "upcoming": (*_IN_SERVICE, EventType.TERMINATION),
    "long_leave": (EventType.SALARY_CHANGE, EventType.CONTRACT, EventType.LEAVE_RETURN, EventType.TERMINATION),
    "left": (EventType.REHIRE,),
}
SALARY_FIELD = "Үндсэн цалин"
LATER_CHANGE = "Энэ өдрөөс хойш өөр өөрчлөлт бүртгэгдсэн байна. Эхлээд түүнийг цуцлах эсвэл засна уу."


class EventError(Exception):
    """A refused event; `errors` maps field name -> message ("__all__" for general)."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def _reason_text(type: str, reason: str, fired_reason: FiredReason | None = None) -> str:
    if fired_reason is not None:
        return str(fired_reason)
    choices = REASON_CHOICES.get(type)
    if choices is not None and reason in choices.values:
        return str(choices(reason).label)
    return reason


def _add(errors: dict[str, str], key: str, message: str) -> None:
    errors[key] = f"{errors[key]} {message}" if key in errors else message


def _validate(
    employee: Employee,
    type: EventType,
    effective: date,
    changes: dict[str, Any],
    salary: Decimal | None,
    reason: str,
    fired_reason: FiredReason | None = None,
    pension: bool = False,
) -> dict[str, Any]:
    """Return the job changes to apply (including the status), or raise EventError."""
    errors: dict[str, str] = {}
    current = history.job_on(employee, effective)
    if current is None:
        raise EventError({"effective": "Энэ өдөр ажилтанд ажлын түүх байхгүй байна."})
    allowed = ALLOWED_FIELDS[type]
    for field in changes:
        if field not in allowed:
            errors[field] = "Энэ өөрчлөлтөөр энэ талбарыг өөрчлөх боломжгүй."
    new = {f: v for f, v in changes.items() if f in allowed and getattr(current, f) != v}
    if type == EventType.TRANSFER and not new:
        _add(errors, "__all__", "Хэлтэс, албан тушаал эсвэл удирдлагын аль нэгийг өөрчилнө үү.")
    if type in (EventType.PROMOTION, EventType.DEMOTION) and "position" not in new:
        errors["position"] = "Албан тушаал өөрчлөгдөөгүй байна."
    if type == EventType.CONTRACT and not new and not pension:
        _add(errors, "__all__", "Гэрээний аль нэг мэдээллийг өөрчилнө үү.")
    if "contract_end" in allowed:
        kind = changes.get("contract_type", current.contract_type)
        if kind == ContractType.OPEN_ENDED:  # an open-ended contract has no end date: clear it, never refuse
            new.pop("contract_end", None)
            if current.contract_end is not None:
                new["contract_end"] = None
        start = changes.get("contract_start", current.contract_start)
        end = new.get("contract_end", current.contract_end) if kind != ContractType.OPEN_ENDED else None
        errors.update(contract_errors(kind, start, end))
    needed = REQUIRED_STATUS.get(type)
    if needed is not None and current.status != needed:
        _add(
            errors,
            "__all__",
            "Зөвхөн ажиллаж байгаа ажилтан урт чөлөө авна."
            if type == EventType.LEAVE_START
            else "Зөвхөн урт чөлөөтэй ажилтан буцаж ирнэ.",
        )
    if type == EventType.TERMINATION and current.status == JobStatus.LEFT:
        _add(errors, "__all__", "Ажилтан аль хэдийн ажлаас гарсан байна.")
    if type == EventType.REHIRE and current.status != JobStatus.LEFT:
        _add(errors, "__all__", "Зөвхөн ажлаас гарсан ажилтныг дахин ажилд авна.")
    reason = reason.strip()
    choices = REASON_CHOICES.get(type)
    if choices is not None:
        if reason not in choices.values:
            errors["reason"] = "Жагсаалтаас шалтгаан сонгоно уу."
    elif type == EventType.DEMOTION and not reason:
        errors["reason"] = "Шалтгааныг заавал бичнэ үү."
    if type == EventType.TERMINATION and fired_reason is None:
        errors["fired_reason"] = "Жагсаалтаас шалтгаан сонгоно уу."
    elif type != EventType.TERMINATION and fired_reason is not None:
        errors["fired_reason"] = "Ажлаас гарсан шалтгаан зөвхөн ажлаас чөлөөлөхөд хамаарна."
    if salary is not None:
        if type not in SALARY_TYPES:
            errors["salary"] = "Энэ өөрчлөлтөд цалин оруулах боломжгүй."
        else:
            current_salary = history.salary_on(employee, effective)
            if current_salary is not None and current_salary.base_salary == salary:
                errors["salary"] = "Цалин өөрчлөгдөөгүй байна."
    elif type == EventType.SALARY_CHANGE:
        errors["salary"] = "Шинэ цалинг оруулна уу."
    if errors:
        raise EventError(errors)
    status = NEW_STATUS.get(type)
    if status is not None:
        new["status"] = status.value
    return new


def _diffs(current: JobRecord, new: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "field": history._label(JobRecord, f),
            "old": history._show(getattr(current, f), JobRecord, f),
            "new": history._show(v, JobRecord, f),
        }
        for f, v in new.items()
    ]


def start_placement_missing(employee: Employee) -> tuple[str, ...]:
    """Placement values the event form must ask for before the first event (QC 1d): only for a MACS-only
    employee (no HR job history) whose MACS row has no department or position. Empty otherwise."""
    if employee.job_records.exists():
        return ()
    return tuple(
        name
        for name, value in (("department", employee.department_id), ("position", employee.position_id))
        if value is None
    )


@transaction.atomic
def record(
    employee: Employee,
    *,
    type: str,
    effective: date,
    changes: dict[str, Any],
    salary: Decimal | None,
    reason: str,
    note: str,
    by: User,
    expected_return: date | None = None,
    fired_reason: FiredReason | None = None,
    pension: bool = False,
    start_department: Department | None = None,
    start_position: Position | None = None,
    order_number: str = "",
    order_date: date | None = None,
    order_summary: str = "",
    order_issued_by: str = "",
) -> Event:
    Employee.objects.select_for_update().get(pk=employee.pk)
    try:
        event_type = EventType(type)
    except ValueError:
        raise EventError({"type": "Үйл явдлын төрөл буруу байна."}) from None
    if expected_return is not None:
        if event_type != EventType.LEAVE_START:
            raise EventError({"expected_return": "Буцах огноо зөвхөн урт чөлөөнд хамаарна."})
        if expected_return <= effective:
            raise EventError({"expected_return": "Буцах огноо чөлөө эхлэх огнооноос хойш байх ёстой."})
    if not employee.job_records.exists():
        # QC 1d: the first event starts the HR history from the MACS row, in this same transaction.
        given = {"department": start_department, "position": start_position}
        missing = {
            f"start_{name}": "Заавал сонгоно уу." for name in start_placement_missing(employee) if not given[name]
        }
        if missing:
            raise EventError(missing)
        try:
            history.start_from_macs(
                employee, by=by, effective=effective, department=start_department, position=start_position
            )
        except HistoryError as exc:
            raise EventError({"__all__": str(exc)}) from exc
    changes = dict(changes)
    if "emptype" in changes and changes["emptype"] is None:
        del changes["emptype"]  # nothing chosen: keep the stored type
    if event_type == EventType.REHIRE and "emptype" not in changes:
        kind = changes.get("contract_type") or getattr(history.job_on(employee, effective), "contract_type", None)
        changes["emptype"] = 5 if kind == ContractType.FIXED_TERM else 1
    if pension and event_type not in (EventType.TERMINATION, EventType.CONTRACT):
        raise EventError({"pension": "Тэтгэвэрт гарсан нь зөвхөн ажлаас гарах эсвэл гэрээ өөрчлөхөд хамаарна."})
    new = _validate(employee, event_type, effective, changes, salary, reason, fired_reason, pension)
    if (new and employee.job_records.filter(period__startswith__gt=effective).exists()) or (
        salary is not None and employee.salary_records.filter(period__startswith__gt=effective).exists()
    ):
        raise EventError({"__all__": LATER_CHANGE})
    current = history.job_on(employee, effective)
    assert current is not None  # _validate guarantees it  # noqa: S101
    job_diffs = _diffs(current, new)
    old_salary = history.salary_on(employee, effective)
    reason = reason.strip()
    event = Event.objects.create(
        employee=employee,
        type=event_type,
        effective=effective,
        reason=reason,
        fired_reason=fired_reason,
        note=note,
        expected_return=expected_return,
        pension=pension,
        created_by=by,
    )
    if pension and event_type == EventType.CONTRACT:
        ext = ensure_ext(employee)
        ext.is_pensioner = True
        ext.save(update_fields=["is_pensioner"])
    try:
        if new:
            history.change_job(
                employee,
                effective=effective,
                changes=new,
                change_type=event_type.change_type,
                note=note,
                by=by,
                event=event,
                log=False,
            )
        if salary is not None:
            history.change_salary(
                employee,
                effective=effective,
                amount=salary,
                change_type=event_type.change_type,
                note=note,
                by=by,
                event=event,
                log=False,
            )
    except HistoryError as exc:
        raise EventError({"__all__": str(exc)}) from exc
    macs_writes.write_event_rows(event)
    new_state = macs_writes._state_on(employee, effective)
    if new_state is not None:
        old_state = macs_writes._state_on(employee, effective - timedelta(days=1)) or new_state
        order_type = orders.classify(event, old_state, new_state)
        if order_type is not None:
            try:
                orders.create_for_change(
                    employee=employee,
                    event=event,
                    is_hire=False,
                    order_type=order_type,
                    number=order_number,
                    date=order_date,
                    summary=order_summary,
                    issued_by=order_issued_by,
                    by=by,
                )
            except OrderError as exc:
                raise EventError({f"order_{k}" if k != "__all__" else k: v for k, v in exc.errors.items()}) from exc
    message = f"{ChangeType(event_type.change_type).label} · {effective:%Y-%m-%d}-нээс"
    if effective < timezone.localdate():
        message += " (өнгөрсөн огноогоор)"
    if expected_return is not None:
        message += f" · {expected_return:%Y-%m-%d} хүртэл"
    if reason or fired_reason is not None:
        message += f". {_reason_text(event_type, reason, fired_reason)}"
    if job_diffs:
        ActivityEntry.objects.create(
            employee=employee, by=by, kind=ActivityKind.HISTORY, message=message, changes=job_diffs
        )
    if salary is not None:
        ActivityEntry.objects.create(
            employee=employee,
            by=by,
            kind=ActivityKind.HISTORY,
            sensitive=True,
            message=message,
            changes=[
                {
                    "field": SALARY_FIELD,
                    "old": str(old_salary.base_salary) if old_salary else "",
                    "new": str(salary),
                }
            ],
        )
    return event


def leave_until(employee: Employee, today: date) -> date | None:
    """Planned return of the long leave in force on `today` (None if not on leave or not given)."""
    job = history.job_on(employee, today)
    if job is None or job.status != JobStatus.LONG_LEAVE:
        return None
    start = (
        employee.events.filter(type=EventType.LEAVE_START, cancelled_at__isnull=True, effective__lte=today)
        .order_by("-effective", "-id")
        .first()
    )
    return start.expected_return if start else None


@transaction.atomic
def cancel(event: Event, *, reason: str, by: User, cancel_order_no: str = "") -> Event:
    reason = reason.strip()
    if not reason:
        raise EventError({"reason": "Цуцлах шалтгаанаа бичнэ үү."})
    Employee.objects.select_for_update().get(pk=event.employee_id)
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.status(timezone.localdate()) != "scheduled":
        raise EventError({"__all__": "Зөвхөн төлөвлөсөн үйл явдлыг цуцлах боломжтой."})
    job_records = list(event.job_records.all())
    salary_records = list(event.salary_records.all())
    macs_writes.delete_event_rows(event)
    try:
        history.undo([*job_records, *salary_records])
    except HistoryError as exc:
        raise EventError({"__all__": str(exc)}) from exc
    event.cancelled_at, event.cancelled_by, event.cancel_reason = timezone.now(), by, reason
    event.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])
    try:
        orders.cancel_for_event(event, reason=reason, cancel_order_no=cancel_order_no)
    except OrderError as exc:
        raise EventError(exc.errors) from exc
    if event.pension and event.type == EventType.CONTRACT:
        # Still a pensioner only if another live contract event says so.
        ext = ensure_ext(event.employee)
        ext.is_pensioner = event.employee.events.filter(
            type=EventType.CONTRACT, pension=True, cancelled_at__isnull=True
        ).exists()
        ext.save(update_fields=["is_pensioner"])
    message = f"Цуцалсан: {event.get_type_display()} ({event.effective:%Y-%m-%d}) — {reason}"
    if job_records or not salary_records:
        ActivityEntry.objects.create(employee=event.employee, by=by, kind=ActivityKind.HISTORY, message=message)
    if salary_records:
        ActivityEntry.objects.create(
            employee=event.employee,
            by=by,
            kind=ActivityKind.HISTORY,
            sensitive=True,
            message=message,
            changes=[{"field": SALARY_FIELD, "old": str(r.base_salary), "new": ""} for r in salary_records],
        )
    return event
