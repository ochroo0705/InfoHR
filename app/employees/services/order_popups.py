"""The order pop-ups (edit the number, date and text; upload the signed scan; the history), without requests.

The views (`order_edit`, `order_upload`, `order_history`) and the JSON API both build these, so the rights, the states
and the Mongolian texts are written once here. A refusal is a result (`ok` False with the form errors), never a 4xx.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import UploadedFile
from django.http import Http404
from django.utils import timezone

from employees import access
from employees.forms import OrderFieldsForm, OrderUploadForm
from employees.models import Employee, HrOrder, OrderState
from employees.services import orders
from employees.services.orders import OrderError

EDIT_HINT = "Дугаарыг автоматаар санал болгосон, шаардлагатай бол өөрчилнө үү."
UPLOAD_TITLE = "Гарын үсэгтэй файл хавсаргах"
EDITABLE_STATES = (OrderState.PENDING, OrderState.REGISTERED)


@dataclass
class OrderPopup:
    title: str
    hint: str
    form: OrderFieldsForm | OrderUploadForm
    order: HrOrder


def _require_manage(user: User) -> None:
    if not access.can_manage(user):
        raise PermissionDenied


def _check_editable(user: User, employee: Employee, order: HrOrder) -> None:
    _require_manage(user)
    if order.employee_id != employee.pk or order.state not in EDITABLE_STATES:
        raise Http404  # signed and cancelled orders are final; a foreign order is not found


def edit_popup(user: User, employee: Employee, order: HrOrder, values: Mapping[str, str] | None = None) -> OrderPopup:
    """The edit pop-up of an order. Unbound (`values` None) it shows the saved values, or a suggested number when the
    order has none; bound, it checks what was posted (the number and the date are required)."""
    _check_editable(user, employee, order)
    title = f"Тушаал: {order.get_order_type_display()}"
    if values is not None:
        return OrderPopup(title, "", OrderFieldsForm(values, required=True, date_required=True), order)
    suggested = "" if order.number else orders.suggest_number(date.today())
    form = OrderFieldsForm(
        required=True,
        date_required=True,
        initial={
            "number": order.number or suggested,
            "date": order.date,
            "summary": order.summary,
            "issued_by": order.issued_by,
        },
    )
    return OrderPopup(title, EDIT_HINT if suggested else "", form, order)


def submit_edit(
    user: User, employee: Employee, order: HrOrder, values: Mapping[str, str]
) -> tuple[bool, OrderPopup, HrOrder | None]:
    """Check and save the edit. Returns (ok, popup, the registered order or None). A service refusal goes onto the
    form's fields (`number`, `date`, `__all__`...), and nothing is written."""
    popup = edit_popup(user, employee, order, values)
    form = popup.form
    if not isinstance(form, OrderFieldsForm) or not form.is_valid():
        return False, popup, None
    data = form.cleaned_data
    try:
        done = orders.register(
            order,
            number=data["number"],
            date=data["date"],
            summary=data["summary"],
            issued_by=data["issued_by"],
            by=user,
        )
    except OrderError as error:
        form.add_service_errors(error.errors)
        return False, popup, None
    return True, popup, done


def upload_popup(user: User, order: HrOrder) -> OrderPopup:
    _require_manage(user)
    return OrderPopup(UPLOAD_TITLE, "", OrderUploadForm(), order)


def submit_upload(user: User, order: HrOrder, file: UploadedFile | None) -> tuple[bool, OrderPopup]:
    """Attach the signed scan (locks the order). A file the form refuses, or a service refusal, stays on the pop-up
    as a message and nothing is attached."""
    _require_manage(user)
    form = OrderUploadForm({}, {"file": file} if file is not None else {})
    popup = OrderPopup(UPLOAD_TITLE, "", form, order)
    if not form.is_valid():
        return False, popup
    try:
        orders.attach_signed_file(order, form.cleaned_data["file"], by=user)
    except OrderError as error:
        for message in error.errors.values():
            form.add_error(None, message)
        return False, popup
    return True, popup


def history_title(order: HrOrder) -> str:
    number = f" · № {order.number}" if order.number else ""
    return f"Тушаалын түүх: {order.get_order_type_display()}{number}"


def history_entries(order: HrOrder) -> list[dict[str, Any]]:
    """The order's activity, newest first: who (a name, the username, or «Систем»), when, what and the changes."""
    rows = order.activity.select_related("by").order_by("-at", "-id")
    return [
        {
            "by": _who(entry.by),
            "at": timezone.localtime(entry.at).strftime("%Y-%m-%d %H:%M"),
            "message": entry.message,
            "changes": entry.changes,
        }
        for entry in rows
    ]


def _who(user: User | None) -> str:
    if user is None:
        return "Систем"
    return user.get_full_name() or user.username
