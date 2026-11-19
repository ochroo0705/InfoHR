"""The event pop-up as the React page calls it:

- POST /api/v1/employees/{pk}/events/{type}/form (JSON `values`, `prev_effective`): the form's state for the values
  typed so far. It has no side effects; POST because it carries typed values. An empty `values` with an empty
  `prev_effective` is the first open.
- POST /api/v1/employees/{pk}/events/{type} (JSON `values`): records the change. A refusal answers 200 with ok false and
  writes nothing; a success calls the same MACS number-clash note as the Django view.
- GET /api/v1/employees/{pk}/events/{event_id}/cancel: the cancel pop-up (title, hint, its fields).
- POST /api/v1/employees/{pk}/events/{event_id}/cancel (JSON `values`): cancels the event.

The rules are employees.services.event_page (which fields a type has, the order block, the summary, the past or future
note, the refusals); this module reads the JSON, calls the service and presents the result. The employee is resolved
with access.visible_employees first (404 outside the user's scope), then the service maps its own refusals:
unknown type, non-cancellable event or foreign object 404, missing right 403 (code "forbidden").
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from django.http import HttpRequest
from employees.services import event_page
from employees.services.event_page import EventPage
from employees.views import _remember_warning
from ninja import Router, Schema
from ninja.security import django_auth

from api.employee_writes import _scoped_employee
from api.popups import (
    HrPopupFieldOut,
    HrPopupOut,
    HrPopupResultOut,
    errors_of,
    form_described,
    hr_popup_out,
    order_note,
    request_user,
    service_errors,
)

events_router = Router(tags=["employees"])

CANCEL_LABEL = "Цуцлах"


class EventFormIn(Schema):
    values: dict[str, str] = {}  # the fields typed in the open form, by HTML name; {} on the first open
    prev_effective: str = ""  # the hidden date the page holds (the last real date); "" on the first open


class EventWriteIn(Schema):
    values: dict[str, str]  # the form's fields by HTML name, as the browser posts them


class EventKindOut(Schema):
    value: str
    label: str
    selected: bool


class EventFormOut(Schema):
    title: str
    kinds: list[EventKindOut]  # the placement kinds; empty for a type that is not a placement
    fields: list[HrPopupFieldOut]  # the event's boxes, «effective» first
    order_fields: list[HrPopupFieldOut]  # the order block's boxes (names carry «order-»); [] without an order block
    order_note: str  # the order block's heading note (the text after «· »); "" without an order block
    summary: str  # the change in one line for the values typed so far; "" when there is none
    when: str  # "past", "future" or "" for the effective date
    prev_effective: str  # the hidden value the next change sends back
    reload: bool  # true when an open form was rebuilt (a kind or date change)
    death_unset: bool  # a termination whose «died» meaning is not set yet (a warning on the form)
    errors: dict[str, list[str]]  # field errors of a typed form, by HTML name
    form_errors: list[str]  # the event form's non-field messages (the order's are in order_errors)
    order_errors: list[str]  # the order block's non-field messages, drawn inside the order block


class EventWriteResultOut(HrPopupResultOut):
    order_errors: list[str]  # the order block's non-field messages, drawn inside the order block; never in form_errors
    summary: str  # the summary line the page recomputes after a refusal
    prev_effective: str
    when: str


def _iso(value: object) -> str:
    if value is None or value == "":
        return ""
    return value.isoformat() if isinstance(value, date) else str(value)


def _prev_effective(page: EventPage) -> str:
    """The literal hidden value when the page has one (the view's rule), else the form's effective date as ISO."""
    if page.prev_effective is not None:
        return page.prev_effective
    return _iso(page.form["effective"].value())


def _open_state(payload: EventFormIn) -> tuple[Mapping[str, str] | None, str | None]:
    """(values, prev_effective) as event_page.build_page takes them: a first open passes None for both (the view's
    GET without the parameters). A "" prev_effective with typed values is a real value, as the view reads it."""
    if not payload.values and payload.prev_effective == "":
        return None, None
    return payload.values, payload.prev_effective


def _event_fields(page: EventPage) -> list[dict[str, Any]]:
    fields = form_described(page.form)
    if page.effective_text:  # the service's flag: a date that is not real stays a text box with the text typed
        for field in fields:
            if field["name"] == "effective":
                field["kind"] = "text"
    return fields


def _order_fields(page: EventPage) -> list[dict[str, Any]]:
    return form_described(page.order_form) if page.order_form is not None else []


def _order_note_text(page: EventPage) -> str:
    """The order block's heading note, the same rule as the hire block; "" when the page has no order block."""
    return order_note(page.order_form) if page.order_form is not None else ""


def _page_errors(page: EventPage) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """The event form's and the order block's errors together: field errors by HTML name, the event form's form errors,
    and the order block's form errors. The order's messages go to order_errors only, never to form_errors."""
    form_fields, form_general = errors_of(page.form)
    order_fields, order_general = errors_of(page.order_form)
    return {**form_fields, **order_fields}, form_general, order_general


def _form_out(page: EventPage, summary: str) -> dict[str, Any]:
    errors, form_errors, order_errors = _page_errors(page)
    return {
        "title": page.title,
        "kinds": [{"value": value, "label": label, "selected": selected} for value, label, selected in page.kinds],
        "fields": _event_fields(page),
        "order_fields": _order_fields(page),
        "order_note": _order_note_text(page),
        "summary": summary,
        "when": page.when,
        "prev_effective": _prev_effective(page),
        "reload": page.reload,
        "death_unset": page.form.death_unset,
        "errors": errors,
        "form_errors": form_errors,
        "order_errors": order_errors,
    }


def _write_out(page: EventPage, ok: bool) -> dict[str, Any]:
    errors, form_errors, order_errors = _page_errors(page)
    return {
        "ok": ok,
        "field_errors": errors,
        "form_errors": form_errors,
        "order_errors": order_errors,
        "summary": page.summary,
        "prev_effective": _prev_effective(page),
        "when": page.when,
    }


@events_router.post("/{pk}/events/{type}/form", auth=django_auth, response=EventFormOut)
def event_form(request: HttpRequest, pk: int, type: str, payload: EventFormIn) -> dict[str, Any]:
    """The event form's state for the values typed so far. 404 for an unknown type or an employee outside the user's
    scope, 403 without the right to record this type. Nothing is written."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    values, prev_effective = _open_state(payload)
    with service_errors():
        page = event_page.build_page(user, employee, type, values, prev_effective=prev_effective)
        summary = event_page.summary_line(user, employee, type, payload.values) if _is_summary_refresh(payload) else ""
    return _form_out(page, summary)


def _is_summary_refresh(payload: EventFormIn) -> bool:
    """A pure summary refresh: the posted effective date is the date the page already holds. After a date change the
    boxes are refilled from the new date, so the raw posted values would not match the summary; the summary stays ""
    then (as Django). An empty or unreal prev_effective also gives "" (the first open has no values)."""
    effective = event_page._parse_day(payload.values.get("effective"))
    previous = event_page._parse_day(payload.prev_effective)
    return effective is not None and previous is not None and effective == previous


@events_router.post("/{pk}/events/{type}", auth=django_auth, response=EventWriteResultOut)
def event_submit(request: HttpRequest, pk: int, type: str, payload: EventWriteIn) -> dict[str, Any]:
    """Record the change. A refused or invalid form answers 200 with ok false and nothing is written; on success the
    MACS number-clash note is kept for the next employee page. For a refused save with an unreal date, the hidden
    `prev_effective` must travel inside `values` (the key "prev_effective"), as the page posts it, so the response keeps
    the last real date."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    with service_errors():
        outcome = event_page.submit(user, employee, type, payload.values)
    if outcome.ok:
        _remember_warning(request, outcome.order)
    return _write_out(outcome.page, outcome.ok)


@events_router.get("/{pk}/events/{event_id}/cancel", auth=django_auth, response=HrPopupOut)
def event_cancel_form(request: HttpRequest, pk: int, event_id: int) -> dict[str, Any]:
    """The cancel pop-up. 404 when the event is not cancellable (applied, cancelled) or is not the employee's; 403
    without the right to cancel it."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    with service_errors():
        page = event_page.cancel_page(user, employee, event_id)
    return hr_popup_out(page.title, page.hint, CANCEL_LABEL, page.form)


@events_router.post("/{pk}/events/{event_id}/cancel", auth=django_auth, response=HrPopupResultOut)
def event_cancel(request: HttpRequest, pk: int, event_id: int, payload: EventWriteIn) -> dict[str, Any]:
    """Cancel the event. A refused form (no reason, a signed order without its cancel order number) answers 200 with
    ok false and changes nothing."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    with service_errors():
        ok, form = event_page.submit_cancel(user, employee, event_id, payload.values)
    field_errors, form_errors = errors_of(form)
    return {"ok": ok, "field_errors": field_errors, "form_errors": form_errors}
