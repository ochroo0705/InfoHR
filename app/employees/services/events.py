"""The only doorway for HR events (spec B). Every function is atomic."""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from accounts.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Model, Q
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
    SalaryRecord,
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
SAME_DAY_RECORD = "Энэ өдрөөс эхэлсэн хугацаа аль хэдийн байна. Засвар ашиглана уу."  # = history._split's message


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


def _dump_changes(new: dict[str, Any]) -> dict[str, Any]:
    """`new` as JSON for Event.proposed: model rows as their pk, dates as ISO text, enums as their value."""
    dumped: dict[str, Any] = {}
    for name, value in new.items():
        if isinstance(value, Model):
            dumped[name] = value.pk
        elif isinstance(value, date):
            dumped[name] = value.isoformat()
        elif isinstance(value, Enum):
            dumped[name] = value.value
        else:
            dumped[name] = value
    return dumped


def _load_changes(dumped: dict[str, Any]) -> dict[str, Any]:
    """The inverse of `_dump_changes`: foreign keys back to rows, other values through the field's `to_python`."""
    loaded: dict[str, Any] = {}
    for name, value in dumped.items():
        field: Any = JobRecord._meta.get_field(name)  # Django's field union has no to_python/related_model for all
        if value is None:
            loaded[name] = None
        elif field.is_relation:
            loaded[name] = field.related_model.objects.get(pk=value)
        else:
            loaded[name] = field.to_python(value)
    return loaded


def _applied_message(event: Event, *, signed: bool) -> str:
    """The activity text of a change that is in the history (today's wording; a signed one says so)."""
    event_type = EventType(event.type)
    message = f"{ChangeType(event_type.change_type).label} · {event.effective:%Y-%m-%d}-нээс"
    if event.effective < timezone.localdate():
        message += " (өнгөрсөн огноогоор)"
    if event.expected_return is not None:
        message += f" · {event.expected_return:%Y-%m-%d} хүртэл"
    if event.reason or event.fired_reason_id is not None:
        message += f". {_reason_text(event_type, event.reason, event.fired_reason)}"
    if signed:
        message += ". Тушаал гарын үсэгтэй болсон."
    return message


def _log_applied(
    employee: Employee,
    *,
    by: User,
    message: str,
    job_diffs: list[dict[str, str]],
    salary: Decimal | None,
    old_salary: SalaryRecord | None,
) -> None:
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


def _mark_pensioner(employee: Employee, event: Event) -> None:
    if event.pension and event.type == EventType.CONTRACT:
        ext = ensure_ext(employee)
        ext.is_pensioner = True
        ext.save(update_fields=["is_pensioner"])


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
    reason = reason.strip()
    order_type = orders.order_type_for(event_type, pension, current, new, employee, effective)
    if order_type is not None:
        # A change that waits must not collide with a record that already starts on its date: refuse it now, as the
        # immediate path does (history._split), instead of at signing.
        same_day = bool(new) and current.period.lower == effective
        if not same_day and salary is not None:
            salary_now = history.salary_on(employee, effective)
            same_day = salary_now is not None and salary_now.period.lower == effective
        if same_day:
            raise EventError({"__all__": SAME_DAY_RECORD})
        # The change needs a signed order: it waits. Nothing is written to the history, the production rows or the
        # movements until apply_waiting runs (spec: "Recording").
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
            applied_at=None,
            proposed={"job": _dump_changes(new), "salary": None if salary is None else str(salary)},
        )
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
        waiting = f"{ChangeType(event_type.change_type).label} · {effective:%Y-%m-%d}-нээс"
        ActivityEntry.objects.create(
            employee=employee,
            by=by,
            kind=ActivityKind.CHANGED,
            message=f"{waiting} — тушаалын гарын үсэг хүлээж байна",
        )
        return event
    job_diffs = _diffs(current, new)
    old_salary = history.salary_on(employee, effective)
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
        applied_at=timezone.now(),
    )
    _mark_pensioner(employee, event)
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
    _log_applied(
        employee,
        by=by,
        message=_applied_message(event, signed=False),
        job_diffs=job_diffs,
        salary=salary,
        old_salary=old_salary,
    )
    return event


@transaction.atomic
def apply_waiting(event: Event, *, by: User) -> None:
    """Apply a change that waited for its signed order, at its own date. Validated again against the history as it is
    now; a same-field change recorded later refuses it (insert_job). Nothing is applied when this raises."""
    employee = Employee.objects.select_for_update().get(pk=event.employee_id)
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.applied_at is not None:
        raise EventError({"__all__": "Энэ өөрчлөлт аль хэдийн хүчинтэй болсон байна."})
    if event.cancelled_at is not None:
        raise EventError({"__all__": "Цуцлагдсан өөрчлөлтийг хүчинтэй болгох боломжгүй."})
    # Ordering: an earlier change that still waits for its signature comes first (by its date, then its id).
    earlier = (
        employee.events.filter(applied_at__isnull=True, cancelled_at__isnull=True)
        .exclude(pk=event.pk)
        .filter(Q(effective__lt=event.effective) | Q(effective=event.effective, pk__lt=event.pk))
        .order_by("effective", "pk")
        .first()
    )
    if earlier is not None:
        raise EventError(
            {
                "__all__": (
                    f"Өмнөх өөрчлөлт ({ChangeType(EventType(earlier.type).change_type).label}, "
                    f"{earlier.effective:%Y-%m-%d}-нээс) тушаалын гарын үсэг хүлээж байна. "
                    "Эхлээд түүний тушаалд гарын үсэг зуруулна уу."
                )
            }
        )
    event_type = EventType(event.type)
    proposed = event.proposed or {}
    # The stored status is the result of the change, not an input: _validate sets it again.
    try:
        job_changes = _load_changes({k: v for k, v in (proposed.get("job") or {}).items() if k != "status"})
    except ObjectDoesNotExist:  # the department or position was deleted after the change was recorded
        raise EventError({"__all__": "Хэлтэс эсвэл албан тушаал устгагдсан байна. Өөрчлөлтийг цуцлана уу."}) from None
    salary = Decimal(proposed["salary"]) if proposed.get("salary") is not None else None
    new = _validate(
        employee,
        event_type,
        event.effective,
        job_changes,
        salary,
        event.reason,
        event.fired_reason,
        event.pension,
    )
    current = history.job_on(employee, event.effective)
    assert current is not None  # _validate guarantees it  # noqa: S101
    if event_type in _IN_SERVICE and current.status == JobStatus.LEFT:
        raise EventError({"__all__": "Ажилтан тухайн өдөр ажлаас гарсан байна. Өөрчлөлтийг цуцлана уу."})
    job_diffs = _diffs(current, new)
    old_salary = history.salary_on(employee, event.effective)
    try:
        if new:
            history.insert_job(
                employee,
                effective=event.effective,
                changes=new,
                change_type=event_type.change_type,
                note=event.note,
                by=by,
                event=event,
            )
        if salary is not None:
            history.insert_salary(
                employee,
                effective=event.effective,
                amount=salary,
                change_type=event_type.change_type,
                note=event.note,
                by=by,
                event=event,
            )
    except HistoryError as exc:
        raise EventError({"__all__": str(exc)}) from exc
    # Marked applied before the production copy: the flags (fired reason, died, leave) read the applied events.
    event.applied_at = timezone.now()
    event.save(update_fields=["applied_at"])
    _mark_pensioner(employee, event)
    macs_writes.sync_current(employee, timezone.localdate())
    employee.refresh_from_db()  # the production row now carries the change: the snapshot must read it
    event.employee = employee
    macs_writes.write_event_rows(event)
    _log_applied(
        employee,
        by=by,
        message=_applied_message(event, signed=True),
        job_diffs=job_diffs,
        salary=salary,
        old_salary=old_salary,
    )


def leave_until(employee: Employee, today: date) -> date | None:
    """Planned return of the long leave in force on `today` (None if not on leave or not given)."""
    job = history.job_on(employee, today)
    if job is None or job.status != JobStatus.LONG_LEAVE:
        return None
    start = (
        employee.events.applied()
        .filter(type=EventType.LEAVE_START, cancelled_at__isnull=True, effective__lte=today)
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
    # A waiting change (no signed order yet) can always be cancelled: nothing was written for it. An applied one only
    # while it is still scheduled (its date is in the future).
    if event.status(timezone.localdate()) not in ("scheduled", "awaiting_signature"):
        raise EventError({"__all__": "Зөвхөн төлөвлөсөн үйл явдлыг цуцлах боломжтой."})
    was_applied = event.applied_at is not None  # read before the writes below
    job_records = list(event.job_records.all())
    salary_records = list(event.salary_records.all())
    if event.applied_at is not None:
        macs_writes.delete_event_rows(event)
        try:
            history.undo([*job_records, *salary_records])
        except HistoryError as exc:
            raise EventError({"__all__": str(exc)}) from exc
    event.cancelled_at, event.cancelled_by, event.cancel_reason = timezone.now(), by, reason
    event.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])
    try:
        orders.cancel_for_event(event, reason=reason, cancel_order_no=cancel_order_no, by=by)
    except OrderError as exc:
        raise EventError(exc.errors) from exc
    if was_applied and event.pension and event.type == EventType.CONTRACT:
        # Still a pensioner only if another live contract event says so. A waiting event never set the flag.
        ext = ensure_ext(event.employee)
        ext.is_pensioner = event.employee.events.filter(
            type=EventType.CONTRACT, pension=True, cancelled_at__isnull=True, applied_at__isnull=False
        ).exists()
        ext.save(update_fields=["is_pensioner"])
    message = f"Цуцалсан: {event.get_type_display()} ({event.effective:%Y-%m-%d}) — {reason}"
    waiting = event.applied_at is None
    proposed = (event.proposed or {}) if waiting else {}
    waiting_job = waiting and bool(proposed.get("job"))
    waiting_salary = waiting and proposed.get("salary") is not None
    if job_records or waiting_job or not (salary_records or waiting_salary):
        ActivityEntry.objects.create(employee=event.employee, by=by, kind=ActivityKind.CANCELLED, message=message)
    if waiting_salary and not salary_records:
        ActivityEntry.objects.create(
            employee=event.employee, by=by, kind=ActivityKind.CANCELLED, sensitive=True, message=message
        )
    if salary_records:
        ActivityEntry.objects.create(
            employee=event.employee,
            by=by,
            kind=ActivityKind.CANCELLED,
            sensitive=True,
            message=message,
            changes=[{"field": SALARY_FIELD, "old": str(r.base_salary), "new": ""} for r in salary_records],
        )
    return event
