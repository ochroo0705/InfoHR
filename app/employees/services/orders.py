"""The life cycle of HR orders (тушаал): pending -> registered -> signed, or cancelled with its change."""

import datetime
from typing import Any

from accounts.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import connection, transaction
from macs.models import Command

from employees.models import CompanySettings, Employee, Event, EventType, HrOrder, OrderState, OrderType
from employees.services import macs_writes

# Fixed key for the advisory lock that serialises order-number checks (same pattern as history.HIRE_LOCK_KEY).
ORDER_NUMBER_LOCK_KEY = 7302
NUMBER_MAX = 10
SUMMARY_MAX = 50
ISSUED_BY_MAX = 25
SIGNED_CANCEL_NEEDS_NUMBER = "Гарын үсэгтэй тушаалыг цуцлахад цуцалсан тушаалын дугаар заавал."


class OrderError(Exception):
    """A refused order action; `errors` maps field name -> message ("__all__" for general)."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def classify(event: Event, old: dict[str, Any], new: dict[str, Any]) -> int | None:
    """The order type a change needs, or None when it needs no order (Global Constraints priority)."""
    if event.pension:
        return OrderType.PENSION.value
    if event.type == EventType.TERMINATION:
        return OrderType.FIRED.value
    if event.type == EventType.REHIRE:
        return OrderType.HIRED.value
    if old.get("department_id") != new.get("department_id"):
        return OrderType.DEPARTMENT.value
    if old.get("position_id") != new.get("position_id"):
        return OrderType.POSITION.value
    if old.get("emptype") != new.get("emptype"):
        return OrderType.TYPE_CHANGED.value
    return None


def _key(number: str) -> str:
    return number.strip().casefold()


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
    order.number, order.number_key, order.date = number, _key(number), date
    order.summary, order.issued_by, order.state = summary, issued_by, OrderState.REGISTERED
    order.save()
    macs_writes.write_order(order)
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
    order = HrOrder.objects.create(
        employee=employee, event=event, is_hire=is_hire, order_type=order_type, created_by=by
    )
    number = number.strip()
    if number or date is not None:
        if not number or date is None:
            raise OrderError({"number" if not number else "date": "Дугаар болон огноог хамт оруулна уу."})
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
    """Attach the signed scan to a registered order, which locks it. Content checks belong to the form."""
    order = HrOrder.objects.select_for_update().get(pk=order.pk)
    if order.state != OrderState.REGISTERED:
        raise OrderError({"__all__": "Зөвхөн бүртгэсэн тушаалд гарын үсэгтэй файл хавсаргана."})
    order.file.save(upload.name or "order", upload, save=False)
    order.state = OrderState.SIGNED
    order.save()
    return order


@transaction.atomic
def cancel_for_event(event: Event, *, reason: str, cancel_order_no: str) -> None:
    """Cancel the order of a cancelled change. The number stays taken and the command row is kept."""
    order = HrOrder.objects.select_for_update().filter(event=event).first()
    if order is None or order.state == OrderState.CANCELLED:
        return
    cancel_order_no = cancel_order_no.strip()
    if order.state == OrderState.SIGNED and not cancel_order_no:
        raise OrderError({"cancel_order_no": SIGNED_CANCEL_NEEDS_NUMBER})
    if len(cancel_order_no) > NUMBER_MAX:
        raise OrderError({"cancel_order_no": f"Дугаар {NUMBER_MAX} тэмдэгтээс хэтрэхгүй."})
    order.state, order.cancel_reason, order.cancel_order_no = OrderState.CANCELLED, reason[:200], cancel_order_no
    order.save()
    macs_writes.point_employee_to_latest_order(order.employee)
