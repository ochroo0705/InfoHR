"""The life cycle of HR orders (тушаал): pending -> registered -> signed, or cancelled with its change."""

import datetime
from typing import Any

from accounts.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import connection, transaction
from macs.models import Command

from employees.models import (
    ActivityEntry,
    ActivityKind,
    CompanySettings,
    Employee,
    Event,
    EventType,
    HrOrder,
    JobRecord,
    OrderState,
    OrderType,
)
from employees.services import macs_writes

# Fixed key for the advisory lock that serialises order-number checks (same pattern as history.HIRE_LOCK_KEY).
ORDER_NUMBER_LOCK_KEY = 7302
NUMBER_MAX = 10
SUMMARY_MAX = 50
ISSUED_BY_MAX = 25
SIGNED_CANCEL_NEEDS_NUMBER = "Гарын үсэгтэй тушаалыг цуцлахад цуцлах шинэ тушаалын дугаар заавал."


class OrderError(Exception):
    """A refused order action; `errors` maps field name -> message ("__all__" for general)."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def classify(event: Event, old: dict[str, Any], new: dict[str, Any]) -> int | None:
    """The order type a change needs, or None when it needs no order (Global Constraints priority)."""
    return classify_parts(event.type, event.pension, old, new)


def classify_parts(event_type: str, pension: bool, old: dict[str, Any], new: dict[str, Any]) -> int | None:
    """`classify` for a change that is not saved yet: the event type and pension flag instead of the Event."""
    if pension:
        return OrderType.PENSION.value
    if event_type == EventType.TERMINATION:
        return OrderType.FIRED.value
    if event_type == EventType.REHIRE:
        return OrderType.HIRED.value
    if old.get("department_id") != new.get("department_id"):
        return OrderType.DEPARTMENT.value
    if old.get("position_id") != new.get("position_id"):
        return OrderType.POSITION.value
    if old.get("emptype") != new.get("emptype"):
        return OrderType.TYPE_CHANGED.value
    return None


def candidate_job(
    employee: Employee, current: JobRecord, new: dict[str, Any], event_type: str, pension: bool
) -> JobRecord:
    """`current` with the proposed changes `new` applied, as an unsaved JobRecord (no pk, nothing is written). Read
    with `macs_writes.state_of` to know the state a change would give."""
    fields = {f.attname: getattr(current, f.attname) for f in JobRecord._meta.concrete_fields if not f.primary_key}
    candidate = JobRecord(**fields)  # no pk: unsaved
    candidate.employee = employee
    candidate.event = Event(type=event_type, pension=pension)  # unsaved: the proposed event, as change_job sets it
    for field, value in new.items():
        setattr(candidate, field, value)
    return candidate


def order_type_for(
    event_type: str,
    pension: bool,
    current: JobRecord,
    new: dict[str, Any],
    employee: Employee,
    day: datetime.date,
) -> int | None:
    """The order type a proposed change needs, decided before anything is written. It gives the same answer as
    `classify` after `events.record` does, because `current` is the job on `day` as it is now and `new` is the diff
    `events._validate` returns. Nothing is saved: the new state is read from an unsaved copy of `current`."""
    # Local import: history imports this module, so a top-level import would be circular.
    from employees.services.history import job_on

    candidate = candidate_job(employee, current, new, event_type, pension)
    previous = day - datetime.timedelta(days=1)
    new_state = macs_writes.state_of(employee, candidate, day)
    before = job_on(employee, previous)
    old_state = macs_writes.state_of(employee, before, previous) if before is not None else new_state
    return classify_parts(event_type, pension, old_state, new_state)


def _key(number: str) -> str:
    return number.strip().casefold()


def _label(order: HrOrder) -> str:
    return f"№ {order.number}" if order.number else "(дугаар хүлээгдэж байна)"


def _log(
    order: HrOrder,
    by: User | None,
    message: str,
    changes: list[dict[str, str]] | None = None,
    kind: ActivityKind = ActivityKind.CHANGED,
) -> None:
    """One line of the order's history, also shown in the employee's activity drawer."""
    ActivityEntry.objects.create(
        employee=order.employee,
        by=by,
        kind=kind,
        message=f"Тушаал {_label(order)} ({order.get_order_type_display()}): {message}",
        changes=changes or [],
        order=order,
    )


def cancellation_links(orders_of_employee: list[HrOrder]) -> dict[int, dict[str, Any]]:
    """For each order: `cancelled_by` (the order whose number was typed as the cancelling one, if it is one of
    this employee's) and `cancels` (their orders that name this one as the cancelling order)."""
    by_key: dict[str, list[HrOrder]] = {}
    for order in orders_of_employee:
        if order.number_key:
            by_key.setdefault(order.number_key, []).append(order)
    links: dict[int, dict[str, Any]] = {o.pk: {"cancelled_by": None, "cancels": []} for o in orders_of_employee}
    for order in orders_of_employee:
        if order.state != OrderState.CANCELLED or not order.cancel_order_no.strip():
            continue
        matches = [m for m in by_key.get(_key(order.cancel_order_no), []) if m.pk != order.pk]
        if matches:
            newest = max(matches, key=lambda m: (m.date or datetime.date.min, m.pk))
            links[order.pk]["cancelled_by"] = newest
            links[newest.pk]["cancels"].append(order)
    return links


def legacy_clash_warning(number: str, day: datetime.date | None, exclude_command_id: int | None = None) -> str:
    """Warning text when an old-program command row (not one of ours) has this number in that year, else ''."""
    if day is None or not number.strip():
        return ""
    ours = set(HrOrder.objects.filter(command_id__isnull=False).values_list("command_id", flat=True))
    if exclude_command_id is not None:
        ours.add(exclude_command_id)
    key = _key(number)
    for cmd in Command.objects.filter(number__iexact=number.strip()).exclude(pk__in=ours):
        if cmd.date is not None and cmd.date.year == day.year and _key(cmd.number) == key:
            return f"Хуучин програмд {day.year} онд ийм дугаартай тушаал байна."
    return ""


def suggest_number(day: datetime.date) -> str:
    """The next order number for `day`'s year: the highest all-digit number used that year plus one, else ''.
    Numbers with letters (e.g. "А/12") are ignored; a year with no orders starts at 1. Only a suggestion:
    HR may overwrite it, and `_validate` still refuses a repeat."""
    used = list(HrOrder.objects.filter(date__year=day.year).values_list("number", flat=True))
    used += [c.number for c in Command.objects.filter(date__year=day.year)]
    plain = [n.strip() for n in used]
    if any(n and not n.isdecimal() for n in plain) and not any(n.isdecimal() for n in plain):
        return ""  # the year is numbered with letters only: guessing would be wrong
    top = max((int(n) for n in plain if n.isdecimal()), default=0)
    suggestion = str(top + 1)
    return suggestion if len(suggestion) <= NUMBER_MAX else ""


def _validate(number: str, date: datetime.date | None, summary: str, issued_by: str, pk: int | None) -> None:
    errors: dict[str, str] = {}
    if not number:
        errors["number"] = "Тушаалын дугаарыг оруулна уу."
    elif len(number) > NUMBER_MAX:
        errors["number"] = f"Дугаар {NUMBER_MAX} тэмдэгтээс хэтрэхгүй."
    if date is None:
        errors["date"] = "Тушаалын огноог оруулна уу."
    if len(summary) > SUMMARY_MAX:
        errors["summary"] = f"Агуулга {SUMMARY_MAX} тэмдэгтээс хэтрэхгүй."
    if len(issued_by) > ISSUED_BY_MAX:
        errors["issued_by"] = f"Гаргасан хүний нэр {ISSUED_BY_MAX} тэмдэгтээс хэтрэхгүй."
    if errors:
        raise OrderError(errors)
    assert date is not None  # noqa: S101
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ORDER_NUMBER_LOCK_KEY])
    taken = HrOrder.objects.filter(number_key=_key(number), date__year=date.year)
    if pk is not None:
        taken = taken.exclude(pk=pk)
    if taken.exists():
        raise OrderError({"number": f"Энэ дугаар {date.year} онд аль хэдийн ашиглагдсан."})


def _apply(
    order: HrOrder, number: str, date: datetime.date | None, summary: str, issued_by: str, by: User | None
) -> HrOrder:
    number, summary = number.strip(), summary.strip()
    issued_by = issued_by.strip() or CompanySettings.get().director_name[:ISSUED_BY_MAX]
    _validate(number, date, summary, issued_by, order.pk)
    was_pending = order.state == OrderState.PENDING
    before = {
        "Дугаар": order.number,
        "Огноо": str(order.date or ""),
        "Агуулга": order.summary,
        "Гаргасан": order.issued_by,
    }
    order.number, order.number_key, order.date = number, _key(number), date
    order.summary, order.issued_by, order.state = summary, issued_by, OrderState.REGISTERED
    order.save()
    macs_writes.write_order(order)
    after = {"Дугаар": number, "Огноо": str(date or ""), "Агуулга": summary, "Гаргасан": issued_by}
    if was_pending:
        _log(order, by, "бүртгэсэн", [{"field": k, "old": "", "new": v} for k, v in after.items() if v])
    elif changes := [{"field": k, "old": before[k], "new": v} for k, v in after.items() if before[k] != v]:
        _log(order, by, "засварласан", changes)
    order.warning = legacy_clash_warning(number, date, order.command_id)  # type: ignore[attr-defined]
    return order


@transaction.atomic
def create_for_change(
    *,
    employee: Employee,
    event: Event | None,
    is_hire: bool,
    order_type: int,
    number: str,
    date: datetime.date | None,
    summary: str,
    issued_by: str,
    by: User | None,
) -> HrOrder:
    """A new order for a change (or the hire): registered when a number and date are given, else pending."""
    number = number.strip()
    if (number or date is not None) and (not number or date is None):  # both or neither, before anything is saved
        raise OrderError({"number" if not number else "date": "Дугаар болон огноог хамт оруулна уу."})
    order = HrOrder.objects.create(
        employee=employee, event=event, is_hire=is_hire, order_type=order_type, created_by=by
    )
    if number and date is not None:
        return _apply(order, number, date, summary, issued_by, by)
    return order


@transaction.atomic
def register(order: HrOrder, *, number: str, date: datetime.date, summary: str, issued_by: str, by: User) -> HrOrder:
    """Give (or change) the number, date and text of a pending or registered order; writes production."""
    order = HrOrder.objects.select_for_update().get(pk=order.pk)
    if order.state not in (OrderState.PENDING, OrderState.REGISTERED):
        raise OrderError({"__all__": "Энэ тушаалыг засах боломжгүй."})
    return _apply(order, number, date, summary, issued_by, by)


@transaction.atomic
def attach_signed_file(order: HrOrder, upload: UploadedFile, *, by: User) -> HrOrder:
    """Attach the signed scan to a registered order, which locks it, and apply the change it waits for (at its own
    date). If that is refused, the scan and the state change roll back and the order stays registered."""
    # Local import: events imports this module, so a top-level import would be circular.
    from employees.services import events

    # Lock order: the employee first, then the order (events.cancel takes employee, event, then order).
    Employee.objects.select_for_update().get(pk=order.employee_id)
    order = HrOrder.objects.select_for_update().get(pk=order.pk)
    if order.state != OrderState.REGISTERED:
        raise OrderError({"__all__": "Зөвхөн бүртгэсэн тушаалд гарын үсэгтэй файл хавсаргана."})
    # Apply first, so a refused change writes no scan to storage (apply_waiting reads neither the state nor the file).
    if order.event_id is not None:
        event = Event.objects.get(pk=order.event_id)
        if event.applied_at is None and event.cancelled_at is None:
            try:
                events.apply_waiting(event, by=by)
            except events.EventError as exc:
                raise OrderError({"__all__": " ".join(exc.errors.values())}) from exc
    order.file.save(upload.name or "order", upload, save=False)
    order.state = OrderState.SIGNED
    order.save()
    if order.command_id:
        # The change was applied just now, so its production row exists only from here: link it to this order
        # (idempotent; also re-points the employee to this order).
        macs_writes.write_order(order)
    _log(order, by, "гарын үсэгтэй файл хавсаргасан, түгжсэн")
    return order


def _cancel(order: HrOrder, reason: str, cancel_order_no: str, by: User | None) -> None:
    """Mark an order cancelled: the number stays taken, the production `command` row is kept, and the employee's
    pointer goes back to their latest order that still counts."""
    cancel_order_no = cancel_order_no.strip()
    if order.state == OrderState.SIGNED and not cancel_order_no:
        raise OrderError({"cancel_order_no": SIGNED_CANCEL_NEEDS_NUMBER})
    if len(cancel_order_no) > NUMBER_MAX:
        raise OrderError({"cancel_order_no": f"Дугаар {NUMBER_MAX} тэмдэгтээс хэтрэхгүй."})
    if cancel_order_no:  # the cancelling order is a new one: its number must not belong to any order already
        year = datetime.date.today().year
        if HrOrder.objects.filter(number_key=_key(cancel_order_no), date__year=year).exists():
            raise OrderError({"cancel_order_no": f"Энэ дугаар {year} онд аль хэдийн ашиглагдсан."})
    order.state, order.cancel_reason, order.cancel_order_no = OrderState.CANCELLED, reason[:200], cancel_order_no
    order.save()
    note = f"цуцалсан. Шалтгаан: {reason[:200]}" if reason else "цуцалсан"
    _log(
        order,
        by,
        note + (f". Цуцлах тушаал № {cancel_order_no}" if cancel_order_no else ""),
        kind=ActivityKind.CANCELLED,
    )
    macs_writes.point_employee_to_latest_order(order.employee)


@transaction.atomic
def cancel_for_event(event: Event, *, reason: str, cancel_order_no: str, by: User | None = None) -> None:
    """Cancel the order of a cancelled change."""
    order = HrOrder.objects.select_for_update().filter(event=event).first()
    if order is None or order.state == OrderState.CANCELLED:
        return
    _cancel(order, reason, cancel_order_no, by)


@transaction.atomic
def cancel_order(order: HrOrder, *, reason: str, by: User) -> HrOrder:
    """Cancel a registered (not yet signed) order that has no change behind it (the hire order) with a reason. A
    change's order is cancelled with its change (`cancel_for_event`); a signed order is never cancelled here, and a
    pending one was never issued."""
    order = HrOrder.objects.select_for_update().get(pk=order.pk)
    if order.state != OrderState.REGISTERED:
        raise OrderError({"__all__": "Зөвхөн гарын үсэг зураагүй, бүртгэсэн тушаалыг цуцална."})
    if order.event_id is not None:
        raise OrderError({"__all__": "Өөрчлөлтийн тушаал өөрчлөлттэйгөө хамт цуцлагдана."})
    _cancel(order, reason, "", by)
    return order
