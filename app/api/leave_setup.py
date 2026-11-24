"""Leave setup API under /api/v1/leave: the public holidays page, the leave settings page and the leave-type pop-up.

GET /leave/holidays?year= and its three writes (add, delete, prefill); GET /leave/settings with the approval and
auto-grant saves; GET /leave/settings/types/{pk} with the create, update and delete of a leave type. The rules come
from leave.services.holiday_page, leave.services.settings_page and leave.services.writes; this module reads the request
and presents the answer. Rights: leave.manage_leave_settings (403 "forbidden" otherwise); every route needs a signed-in
session (401 without one). A type that does not exist is 404. Reads answer Cache-Control no-store. Writes answer 200
with LeaveWriteResultOut: ok true, or ok false with the service's message (error) or the form's errors (field_errors,
form_errors). A refused write changes nothing.
"""

from typing import Any

from accounts.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from employees.services.macs_writes import ListEntryInUse
from leave import access
from leave.forms import ApprovalSettingsForm, LeaveTypeForm
from leave.models import LeaveSettings, LeaveTypeExt, type_ext
from leave.services import writes
from leave.services.holiday_page import apply_holiday_action, holiday_page, parse_year
from leave.services.settings_page import (
    approval_choices,
    approval_initial,
    ext_values,
    save_approval,
    save_auto_grant,
    type_rows,
)
from macs.models import LeaveTypeRow
from ninja import Router, Schema
from ninja.security import django_auth

from api.errors import ApiError, form_error_payload
from api.leave import LeaveWriteResultOut
from api.popups import FORBIDDEN, request_user, service_errors

leave_setup_router = Router(tags=["leave"])

HOLIDAY_EMPTY_TEXT = "Бүртгээгүй"  # the holidays list's text when the year has none (holidays.html)


class LeaveHolidayOut(Schema):
    date: str  # YYYY-MM-DD
    name: str


class LeaveHolidaysOut(Schema):
    year: int
    holidays: list[LeaveHolidayOut]  # every holiday day of the year, in date order
    fixed_count: int  # how many fixed-date holidays the prefill adds at most
    empty_text: str


class LeaveHolidayAddIn(Schema):
    year: int | str | None = None  # the year the date must belong to; null or junk is this year
    date: str  # YYYY-MM-DD
    name: str


class LeaveHolidayDeleteIn(Schema):
    year: int | str | None = None
    date: str  # YYYY-MM-DD; a bad date changes nothing


class LeaveHolidayPrefillIn(Schema):
    year: int | str | None = None


class LeaveStringChoiceOut(Schema):
    value: str
    label: str


class LeaveApprovalOut(Schema):
    step1: str  # the stored first step, as the choice value («» when none)
    step2: str


class LeaveTypeOut(Schema):
    id: int
    name: str
    is_paid: bool
    uses_annual_balance: bool
    is_active: bool
    order: int
    staff_may_request: bool


class LeaveSettingsOut(Schema):
    types: list[LeaveTypeOut]  # sorted by order, then name
    auto_annual_grant: bool
    approval: LeaveApprovalOut
    step1_choices: list[LeaveStringChoiceOut]
    step2_choices: list[LeaveStringChoiceOut]


class LeaveApprovalIn(Schema):
    step1: str  # a choice value: «» (no approval), «manager» or «group:<id>»
    step2: str


class LeaveAutoIn(Schema):
    auto_annual_grant: bool


class LeaveTypeIn(Schema):
    name: str
    is_paid: bool
    uses_annual_balance: bool
    is_active: bool
    order: int  # 0..32767, checked by the form
    staff_may_request: bool


def _manager(request: HttpRequest) -> User:
    user = request_user(request)
    if not access.can_manage_settings(user):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return user


def _body_year(raw: int | str | None) -> int:
    return parse_year(None if raw is None else str(raw), timezone.localdate().year)


def _type_row(pk: int) -> LeaveTypeRow:
    """The leave type with this id; 404 when there is none (the same text as the other pages)."""
    with service_errors():
        return get_object_or_404(LeaveTypeRow, pk=pk)


def _type_out(row: LeaveTypeRow, ext: LeaveTypeExt) -> LeaveTypeOut:
    return LeaveTypeOut(
        id=row.pk,
        name=row.name,
        is_paid=ext.is_paid,
        uses_annual_balance=ext.uses_annual_balance,
        is_active=ext.is_active,
        order=ext.order,
        staff_may_request=ext.staff_may_request,
    )


def _type_data(payload: LeaveTypeIn) -> dict[str, Any]:
    """The type form as the browser would send it: booleans as checked or not, numbers as numbers."""
    return {
        "name": payload.name,
        "is_paid": payload.is_paid,
        "uses_annual_balance": payload.uses_annual_balance,
        "is_active": payload.is_active,
        "order": payload.order,
        "staff_may_request": payload.staff_may_request,
    }


def _saved() -> dict[str, Any]:
    return {"ok": True, "error": "", "form_errors": [], "field_errors": {}}


def _refused_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message, "form_errors": [], "field_errors": {}}


def _refused_form(form: ApprovalSettingsForm | LeaveTypeForm) -> dict[str, Any]:
    payload = form_error_payload(form)
    return {"ok": False, "error": "", "form_errors": payload["form_errors"], "field_errors": payload["field_errors"]}


# --- holidays ------------------------------------------------------------------------------------------------------


@leave_setup_router.get("/holidays", response=LeaveHolidaysOut, auth=django_auth)
def leave_holidays(request: HttpRequest, response: HttpResponse, year: str | None = None) -> LeaveHolidaysOut:
    """The holidays of one year. Junk or an out-of-range year is this year."""
    _manager(request)
    page = holiday_page(parse_year(year, timezone.localdate().year))
    response["Cache-Control"] = "no-store"
    return LeaveHolidaysOut(
        year=page.year,
        holidays=[LeaveHolidayOut(date=day.isoformat(), name=name) for day, name in page.holidays],
        fixed_count=page.fixed_count,
        empty_text=HOLIDAY_EMPTY_TEXT,
    )


@leave_setup_router.post("/holidays/add", response=LeaveWriteResultOut, auth=django_auth)
def leave_holiday_add(request: HttpRequest, payload: LeaveHolidayAddIn) -> dict[str, Any]:
    """Set one date's holiday name. The refusal text of the Django page comes back in `error`."""
    user = _manager(request)
    error = apply_holiday_action(_body_year(payload.year), "add", payload.date, payload.name, user)
    return _refused_error(error) if error else _saved()


@leave_setup_router.post("/holidays/delete", response=LeaveWriteResultOut, auth=django_auth)
def leave_holiday_delete(request: HttpRequest, payload: LeaveHolidayDeleteIn) -> dict[str, Any]:
    """Remove one date from the holidays. A bad date or a day not listed changes nothing and is still ok."""
    user = _manager(request)
    apply_holiday_action(_body_year(payload.year), "delete", payload.date, "", user)
    return _saved()


@leave_setup_router.post("/holidays/prefill", response=LeaveWriteResultOut, auth=django_auth)
def leave_holiday_prefill(request: HttpRequest, payload: LeaveHolidayPrefillIn) -> dict[str, Any]:
    """Add the fixed-date holidays that are still missing from the year."""
    user = _manager(request)
    apply_holiday_action(_body_year(payload.year), "prefill", "", "", user)
    return _saved()


# --- settings ------------------------------------------------------------------------------------------------------


def _choices(pairs: list[tuple[str, str]]) -> list[LeaveStringChoiceOut]:
    return [LeaveStringChoiceOut(value=value, label=label) for value, label in pairs]


@leave_setup_router.get("/settings", response=LeaveSettingsOut, auth=django_auth)
def leave_settings_read(request: HttpRequest, response: HttpResponse) -> LeaveSettingsOut:
    """The leave types, the approval steps with their choices, and the auto-grant switch."""
    _manager(request)
    setting = LeaveSettings.get()
    step1, step2 = approval_choices()
    response["Cache-Control"] = "no-store"
    return LeaveSettingsOut(
        types=[_type_out(row, ext) for row, ext in type_rows()],
        auto_annual_grant=setting.auto_annual_grant,
        approval=LeaveApprovalOut(**approval_initial(setting)),
        step1_choices=_choices(step1),
        step2_choices=_choices(step2),
    )


@leave_setup_router.post("/settings/approval", response=LeaveWriteResultOut, auth=django_auth)
def leave_approval_save(request: HttpRequest, payload: LeaveApprovalIn) -> dict[str, Any]:
    """Save the two approval steps. An unknown choice is refused under its field; step 2 is empty when step 1 is."""
    _manager(request)
    form = ApprovalSettingsForm({"step1": payload.step1, "step2": payload.step2})
    if not form.is_valid():
        return _refused_form(form)
    save_approval(LeaveSettings.get(), form.settings_values())
    return _saved()


@leave_setup_router.post("/settings/auto", response=LeaveWriteResultOut, auth=django_auth)
def leave_auto_save(request: HttpRequest, payload: LeaveAutoIn) -> dict[str, Any]:
    """Switch the automatic annual grant on or off."""
    _manager(request)
    save_auto_grant(LeaveSettings.get(), payload.auto_annual_grant)
    return _saved()


# --- leave types ---------------------------------------------------------------------------------------------------


@leave_setup_router.get("/settings/types/{pk}", response=LeaveTypeOut, auth=django_auth)
def leave_type_read(request: HttpRequest, response: HttpResponse, pk: int) -> LeaveTypeOut:
    """One leave type as the pop-up loads it. 404 for an unknown id."""
    _manager(request)
    row = _type_row(pk)
    response["Cache-Control"] = "no-store"
    return _type_out(row, type_ext(row))


@leave_setup_router.post("/settings/types", response=LeaveWriteResultOut, auth=django_auth)
def leave_type_create(request: HttpRequest, payload: LeaveTypeIn) -> dict[str, Any]:
    """Add a leave type. The same form and service as the Django add pop-up."""
    _manager(request)
    form = LeaveTypeForm(_type_data(payload))
    if not form.is_valid():
        return _refused_form(form)
    writes.save_leave_type(form.cleaned_data["name"], ext_values(form.cleaned_data))
    return _saved()


@leave_setup_router.post("/settings/types/{pk}", response=LeaveWriteResultOut, auth=django_auth)
def leave_type_update(request: HttpRequest, pk: int, payload: LeaveTypeIn) -> dict[str, Any]:
    """Change a leave type's name and settings. 404 for an unknown id."""
    _manager(request)
    row = _type_row(pk)
    form = LeaveTypeForm(_type_data(payload))
    if not form.is_valid():
        return _refused_form(form)
    writes.save_leave_type(form.cleaned_data["name"], ext_values(form.cleaned_data), row=row)
    return _saved()


@leave_setup_router.post("/settings/types/{pk}/delete", response=LeaveWriteResultOut, auth=django_auth)
def leave_type_delete(request: HttpRequest, pk: int) -> dict[str, Any]:
    """Remove a leave type no leave or entitlement uses; a type in use is kept and the reason comes back in `error`."""
    _manager(request)
    row = _type_row(pk)
    try:
        writes.delete_leave_type(row)
    except ListEntryInUse as exc:
        return _refused_error(str(exc))
    return _saved()
