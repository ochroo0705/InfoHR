"""The order pop-ups as the React page calls them, on an employee the user may see:

- GET /api/v1/employees/{pk}/orders/{order_id}/edit: the edit pop-up (number, date, summary, issued by).
- POST /api/v1/employees/{pk}/orders/{order_id}/edit (JSON `values`): saves the edit. A refusal answers 200 with ok
  false and writes nothing; on success the MACS number-clash note is kept for the next employee page.
- GET /api/v1/employees/{pk}/orders/{order_id}/upload: the upload pop-up (one file box, multipart).
- POST /api/v1/employees/{pk}/orders/{order_id}/upload (multipart `file`): attaches the signed scan.
- GET/POST /api/v1/employees/{pk}/orders/{order_id}/cancel: the cancel pop-up (reason) of a registered order with no
  change behind it; a refusal answers 200 with ok false.
- GET/POST /api/v1/employees/{pk}/orders/{order_id}/sign: the signing pop-up (title, saved signature flag) and the
  signing (saved or drawn); a refusal answers 200 with ok false and the messages.
- GET /api/v1/employees/{pk}/orders/{order_id}/history: the order's activity, newest first (read-only).
- GET /api/v1/employees/{pk}/orders/{order_id}/detail: the whole order pop-up (facts, change rows, status chips, links,
  history and the buttons the user may press), built by employees.services.order_detail_page.

The rules are employees.services.order_popups; this module reads the request, resolves the employee and the order
(404 outside the user's scope or for an order of another employee) and presents the service's result.
"""

from typing import Any

from django.http import HttpRequest
from django.utils import timezone
from employees.models import Employee, HrOrder, OrderState
from employees.services import order_detail_page, order_popups, order_signing
from employees.services.order_popups import OrderPopup
from employees.views import _remember_warning
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.security import django_auth

from api.employee import ChipOut
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


class OrderSignIn(Schema):
    mode: str  # "saved" (the user's saved signature) or "drawn" (the picture on the pad)
    signature: str = ""  # the drawn picture as a PNG data URL; "" for a saved signature
    remember: bool = False  # keep the drawn picture as the user's saved signature


class OrderSignOut(Schema):
    title: str
    has_saved: bool
    saved_url: str  # the saved signature picture's API path, "" when there is none


class OrderSignResultOut(Schema):
    ok: bool
    errors: list[str]  # the messages to show; [] on success


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


class OrderDetailRowOut(Schema):
    label: str
    value: str  # a plain fact; "" on an arrow row
    before: str  # arrow rows only ("before → after"); "" otherwise
    after: str


class OrderDetailScanOut(Schema):
    note: str  # the text shown (the link text when url is set)
    url: str  # the scan's API path, or "" when there is no link


class OrderDetailSigningOut(Schema):
    text: str  # "<signer> · <Y-m-d H:i> · <method>"
    image_url: str  # the signature picture's API path


class OrderDetailLinkRowOut(Schema):
    label: str  # «Цуцалсан» or «Цуцалсан тушаал»
    reason: str  # the cancel reason shown first («Цуцалсан» only), else ""
    text_prefix: str  # text between the reason and the link (" · цуцлах тушаал: "), else ""
    order_pk: int | None  # the linked order's pk; None when there is no link
    link_text: str  # "№ N" (the link text, or the plain number when not linked)
    suffix: str  # text after the link (" тушаалыг цуцалсан"), else ""


class OrderDetailActionsOut(Schema):
    word_url: str  # the Word draft's API path, or "" when the button is hidden
    pdf_url: str  # the PDF's API path, or "" when the button is hidden
    upload: bool
    edit: bool
    cancel_event_id: int | None  # the change's event id for «Цуцлах» (a change), else None
    cancel_order: bool  # «Тушаал цуцлах» (a registered order without a change)
    sign: bool


class OrderDetailOut(Schema):
    title: str
    employee_pk: int
    employee_name: str
    employee_code: str
    status_chip: ChipOut | None  # the change's status chip; None for a hire or an effective change
    awaiting_note: str  # "" unless the change waits for its signed order
    change_rows: list[OrderDetailRowOut]  # «Өөрчлөлт», in the template's order
    order_heading: str  # "Тушаал № N / YYYY"
    state_chip: ChipOut
    order_rows: list[OrderDetailRowOut]  # Төрөл, Огноо, Агуулга, Гаргасан (before and after are "")
    scan: OrderDetailScanOut
    signing: OrderDetailSigningOut | None
    cancel_rows: list[OrderDetailLinkRowOut]
    entries: list[OrderHistoryEntryOut]  # newest first
    actions: OrderDetailActionsOut


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


@orders_router.get("/{pk}/orders/{order_id}/cancel", auth=django_auth, response=HrPopupOut)
def order_cancel_form(request: HttpRequest, pk: int, order_id: int) -> dict[str, Any]:
    """The cancel pop-up of a registered order with no change behind it (the reason). 404 for a change's order, a
    signed or pending one; 403 without the manage right."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        popup = order_popups.cancel_popup(user, employee, order)
    return hr_popup_out(popup.title, popup.hint, order_popups.CANCEL_LABEL, popup.form)


@orders_router.post("/{pk}/orders/{order_id}/cancel", auth=django_auth, response=HrPopupResultOut)
def order_cancel_submit(request: HttpRequest, pk: int, order_id: int, payload: OrderPopupValuesIn) -> dict[str, Any]:
    """Cancel the order with the posted reason. A missing reason answers 200 with ok false on the `reason` field; a
    service refusal answers 200 with ok false as a form error. Nothing is written then."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        ok, popup = order_popups.submit_cancel(user, employee, order, payload.values)
    return _result_out(popup, ok)


SIGN_TITLE = "Гарын үсэг зурах"
SAVED_SIGNATURE_PATH = "/api/v1/me/signature"


@orders_router.get("/{pk}/orders/{order_id}/sign", auth=django_auth, response=OrderSignOut)
def order_sign_form(request: HttpRequest, pk: int, order_id: int) -> dict[str, Any]:
    """The signing pop-up's data: the title with the order's number, and whether the user has a saved signature. 403
    without the signing switch or for a hire order whose salary the user may not see; 404 when not registered."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        state = order_signing.signing_state(user, order)
    return {
        "title": f"{SIGN_TITLE} · № {state.number}",
        "has_saved": state.has_saved,
        "saved_url": SAVED_SIGNATURE_PATH if state.has_saved else "",
    }


@orders_router.post("/{pk}/orders/{order_id}/sign", auth=django_auth, response=OrderSignResultOut)
def order_sign_submit(request: HttpRequest, pk: int, order_id: int, payload: OrderSignIn) -> dict[str, Any]:
    """Sign the registered order (saved or drawn). A refusal that writes nothing answers 200 with ok false and the
    messages; the signing is not wrapped in a transaction here (the service makes its own)."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        errors = order_signing.submit_sign(user, order, payload.mode, payload.signature, payload.remember)
    return {"ok": not errors, "errors": errors}


@orders_router.get("/{pk}/orders/{order_id}/history", auth=django_auth, response=OrderHistoryOut)
def order_history_view(request: HttpRequest, pk: int, order_id: int) -> dict[str, Any]:
    """Who created, registered, edited, signed or cancelled this order, and when. Needs only the right to see the
    employee (no manage right)."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    return {"title": order_popups.history_title(order), "entries": order_popups.history_entries(order)}


# The change's status chips: the template's classes and labels (_order_state.html, _awaiting_chip.html). An effective
# change has no chip.
_STATUS_CHIPS: dict[str, dict[str, str]] = {
    "scheduled": {
        "label": "Төлөвлөсөн",
        "tone": "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800",
    },
    "awaiting_signature": {
        "label": "Гарын үсэг хүлээж байна",
        "tone": (
            "whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-900 "
            "no-underline"
        ),
    },
    "cancelled": {
        "label": "Цуцлагдсан",
        "tone": "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700",
    },
}
AWAITING_NOTE = "Тушаал гарын үсэгтэй болмогц хүчин төгөлдөр болно"
NO_SCAN_RIGHT = "Зөвхөн цалингийн эрхтэй хэрэглэгч харна"
NO_SCAN = "хавсаргаагүй"
SCAN_LINK = "Файл харах"


def _state_chip(order: HrOrder) -> dict[str, str]:
    """The order's state chip (_order_state.html without a legacy row): registered sky, signed seal, others slate."""
    if order.state == OrderState.REGISTERED:
        tone = "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-900"
    elif order.state == OrderState.SIGNED:
        tone = "seal"
    else:
        tone = "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700"
    return {"label": order.get_state_display(), "tone": tone}


def _api_path(employee: Employee, order: HrOrder, tail: str) -> str:
    return f"/api/v1/employees/{employee.pk}/orders/{order.pk}/{tail}"


def _row(label: str, value: str = "", before: str = "", after: str = "") -> dict[str, str]:
    return {"label": label, "value": value, "before": before, "after": after}


def _change_rows(context: dict[str, Any], order: HrOrder) -> list[dict[str, str]]:
    """«Өөрчлөлт»: the valid date, then the arrow rows (or the department and position of a hire), then the reason,
    the pension, the note and, for a cancelled change, the cancel reason. Same order as the template."""
    event = order.event
    if event is not None:
        date_value = f"{event.effective:%Y-%m-%d}"
    else:
        date_value = f"{order.date:%Y-%m-%d}" if order.date else "—"
    rows = [_row("Хүчинтэй огноо", value=date_value)]
    if context["change_rows"]:
        rows += [_row(label, before=before, after=after) for label, before, after in context["change_rows"]]
    else:
        department = context["department"] or "—"
        position = context["position"] or "—"
        rows.append(_row("Хэлтэс, албан тушаал", value=f"{department} · {position}"))
    if event is not None:
        if event.fired_reason:
            rows.append(_row("Шалтгаан", value=event.fired_reason.name))
        elif event.reason:
            rows.append(_row("Шалтгаан", value=event.reason))
        if event.pension:
            rows.append(_row("Тэтгэвэр", value="Тэтгэвэрт гарсан"))
        if event.note:
            rows.append(_row("Тайлбар", value=event.note))
    if context["change_status"] == "cancelled":
        rows.append(_row("Цуцалсан шалтгаан", value=(event.cancel_reason or "—") if event is not None else "—"))
    return rows


def _scan(context: dict[str, Any], employee: Employee, order: HrOrder) -> dict[str, str]:
    if not context["can_open_scan"]:
        return {"note": NO_SCAN_RIGHT, "url": ""}
    if order.file:
        return {"note": SCAN_LINK, "url": _api_path(employee, order, "file")}
    return {"note": NO_SCAN, "url": ""}


def _cancel_rows(context: dict[str, Any], employee: Employee, order: HrOrder) -> list[dict[str, Any]]:
    """«Цуцалсан» (this order was cancelled, by which order) and «Цуцалсан тушаал» (the orders this one cancelled)."""
    rows: list[dict[str, Any]] = []
    links = context["links"]
    if order.state == OrderState.CANCELLED:
        reason = order.cancel_reason or "—"
        if order.cancel_order_no:
            cancelled_by = links["cancelled_by"]
            rows.append(
                {
                    "label": "Цуцалсан",
                    "reason": reason,
                    "text_prefix": " · цуцлах тушаал: ",
                    "order_pk": cancelled_by.pk if cancelled_by is not None else None,
                    "link_text": f"№ {order.cancel_order_no}",
                    "suffix": "",
                }
            )
        else:
            rows.append(
                {
                    "label": "Цуцалсан",
                    "reason": reason,
                    "text_prefix": "",
                    "order_pk": None,
                    "link_text": "",
                    "suffix": "",
                }
            )
    for cancelled in links["cancels"]:
        rows.append(
            {
                "label": "Цуцалсан тушаал",
                "reason": "",
                "text_prefix": "",
                "order_pk": cancelled.pk,
                "link_text": f"№ {cancelled.number}",
                "suffix": " тушаалыг цуцалсан",
            }
        )
    return rows


def _actions(context: dict[str, Any], employee: Employee, order: HrOrder) -> dict[str, Any]:
    """The buttons the template shows, decided here (React draws them as given)."""
    can_manage = context["can_manage"]
    registered = order.state == OrderState.REGISTERED
    documents = can_manage and order.state != OrderState.CANCELLED
    cancel_change = context["cancel_change"]
    return {
        "word_url": _api_path(employee, order, "document") if documents else "",
        "pdf_url": _api_path(employee, order, "document/pdf") if documents else "",
        "upload": can_manage and registered,
        "edit": context["editable"],
        "cancel_event_id": order.event_id if cancel_change else None,
        "cancel_order": can_manage and registered and not order.event_id and not cancel_change,
        "sign": context["can_sign"],
    }


def detail_out(context: dict[str, Any]) -> dict[str, Any]:
    """The order pop-up's response, from the context of employees.services.order_detail_page.build: every text, chip
    and flag is decided here, so React only draws what it gets."""
    employee: Employee = context["employee"]
    order: HrOrder = context["order"]
    event = order.event
    status = context["change_status"]
    if event is not None:
        title = f"{event.get_type_display()} · {event.effective:%Y-%m-%d}"
    else:
        title = "Ажилд авсан"
    heading = "Тушаал"
    if order.number:
        heading += f" № {order.number}"
        if order.date:
            heading += f" / {order.date:%Y}"
    signing = context["signing"]
    signing_out = None
    if signing is not None:
        when = timezone.localtime(signing.signed_at).strftime("%Y-%m-%d %H:%M")
        signing_out = {
            "text": f"{signing.signer_name} · {when} · {signing.get_method_display()}",
            "image_url": _api_path(employee, order, "signing-image"),
        }
    return {
        "title": title,
        "employee_pk": employee.pk,
        "employee_name": employee.full_name,
        "employee_code": employee.code,
        "status_chip": _STATUS_CHIPS.get(status),
        "awaiting_note": AWAITING_NOTE if status == "awaiting_signature" else "",
        "change_rows": _change_rows(context, order),
        "order_heading": heading,
        "state_chip": _state_chip(order),
        "order_rows": [
            _row("Төрөл", value=order.get_order_type_display()),
            _row("Огноо", value=f"{order.date:%Y-%m-%d}" if order.date else "—"),
            _row("Агуулга", value=order.summary or "—"),
            _row("Гаргасан", value=order.issued_by or "—"),
        ],
        "scan": _scan(context, employee, order),
        "signing": signing_out,
        "cancel_rows": _cancel_rows(context, employee, order),
        "entries": order_popups.history_entries(order),
        "actions": _actions(context, employee, order),
    }


@orders_router.get("/{pk}/orders/{order_id}/detail", auth=django_auth, response=OrderDetailOut)
def order_detail_view(request: HttpRequest, pk: int, order_id: int) -> dict[str, Any]:
    """The whole order pop-up. Anyone who may see the employee may open it; the buttons follow the user's rights."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    return detail_out(order_detail_page.build(user, employee, order))
