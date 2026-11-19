"""The order pop-ups as the React page calls them, on an employee the user may see:

- GET /api/v1/employees/{pk}/orders/{order_id}/edit: the edit pop-up (number, date, summary, issued by).
- POST /api/v1/employees/{pk}/orders/{order_id}/edit (JSON `values`): saves the edit. A refusal answers 200 with ok
  false and writes nothing; on success the MACS number-clash note is kept for the next employee page.
- GET /api/v1/employees/{pk}/orders/{order_id}/upload: the upload pop-up (one file box, multipart).
- POST /api/v1/employees/{pk}/orders/{order_id}/upload (multipart `file`): attaches the signed scan.
- GET /api/v1/employees/{pk}/orders/{order_id}/history: the order's activity, newest first (read-only).

The rules are employees.services.order_popups; this module reads the request, resolves the employee and the order
(404 outside the user's scope or for an order of another employee) and presents the service's result.
"""

from typing import Any

from django.http import HttpRequest
from employees.models import Employee, HrOrder
from employees.services import order_popups
from employees.services.order_popups import OrderPopup
from employees.views import _remember_warning
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.security import django_auth

from api.employee_writes import _scoped_employee
from api.popups import (
    NOT_FOUND,
    HrPopupOut,
    HrPopupResultOut,
    errors_of,
    hr_popup_out,
    request_user,
    service_errors,
)

orders_router = Router(tags=["employees"])

SAVE_LABEL = "Хадгалах"


class OrderPopupValuesIn(Schema):
    values: dict[str, str]  # the edit's fields by HTML name (unprefixed), as the browser posts them


class OrderHistoryEntryChangeOut(Schema):
    field: str
    old: str
    new: str


class OrderHistoryEntryOut(Schema):
    by: str  # the user's name or username, or «Систем»
    at: str  # "Y-m-d H:i" in local time
    message: str
    changes: list[OrderHistoryEntryChangeOut]


class OrderHistoryOut(Schema):
    title: str
    entries: list[OrderHistoryEntryOut]  # newest first


def _order_of(employee: Employee, order_id: int) -> HrOrder:
    """The order of this employee, else 404 (a foreign order is not found, as the Django view's get_object_or_404)."""
    order = employee.hr_orders.filter(pk=order_id).first()
    if order is None:
        raise HttpError(404, NOT_FOUND)
    return order


def _result_out(popup: OrderPopup, ok: bool) -> dict[str, Any]:
    field_errors, form_errors = errors_of(popup.form)
    return {"ok": ok, "field_errors": field_errors, "form_errors": form_errors}


@orders_router.get("/{pk}/orders/{order_id}/edit", auth=django_auth, response=HrPopupOut)
def order_edit_form(request: HttpRequest, pk: int, order_id: int) -> dict[str, Any]:
    """The edit pop-up with the saved values (or a suggested number). 404 for a signed or cancelled order; 403 without
    the manage right."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        popup = order_popups.edit_popup(user, employee, order)
    return hr_popup_out(popup.title, popup.hint, SAVE_LABEL, popup.form)


@orders_router.post("/{pk}/orders/{order_id}/edit", auth=django_auth, response=HrPopupResultOut)
def order_edit_submit(request: HttpRequest, pk: int, order_id: int, payload: OrderPopupValuesIn) -> dict[str, Any]:
    """Save the edit. A refused form answers 200 with ok false and changes nothing; a saved order keeps the MACS
    number-clash note for the next employee page."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        ok, popup, done = order_popups.submit_edit(user, employee, order, payload.values)
    if done is not None:
        _remember_warning(request, done)
    return _result_out(popup, ok)


@orders_router.get("/{pk}/orders/{order_id}/upload", auth=django_auth, response=HrPopupOut)
def order_upload_form(request: HttpRequest, pk: int, order_id: int) -> dict[str, Any]:
    """The upload pop-up: one file box (multipart). 403 without the manage right."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        popup = order_popups.upload_popup(user, order)
    return hr_popup_out(popup.title, popup.hint, SAVE_LABEL, popup.form, multipart=True)


@orders_router.post("/{pk}/orders/{order_id}/upload", auth=django_auth, response=HrPopupResultOut)
def order_upload_submit(
    request: HttpRequest, pk: int, order_id: int, file: File[UploadedFile | None] = None
) -> dict[str, Any]:
    """Attach the signed scan. A missing, wrong or too big file, or an order that is not registered, answers 200 with
    ok false and the message on the form; nothing is attached then. Uploads keep no MACS note."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        ok, popup = order_popups.submit_upload(user, order, file)
    return _result_out(popup, ok)


@orders_router.get("/{pk}/orders/{order_id}/history", auth=django_auth, response=OrderHistoryOut)
def order_history_view(request: HttpRequest, pk: int, order_id: int) -> dict[str, Any]:
    """Who created, registered, edited, signed or cancelled this order, and when. Needs only the right to see the
    employee (no manage right)."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    return {"title": order_popups.history_title(order), "entries": order_popups.history_entries(order)}
