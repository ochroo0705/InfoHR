"""Leave API under /api/v1/leave: the leave list screen and the read side of the add, edit and cancel pop-ups.

GET /leave (one batch of the list, with the banners and the rights the page needs), GET /leave/options (the choices and
the first values of the add pop-up), GET /leave/{pk} (the edit pop-up's first values and the row as loaded) and
GET /leave/{pk}/cancel (what the cancel pop-up asks). Rules come from leave.services.list_page and leave.services.
form_page; this module reads the request and presents the answer. Rights: leave.view_leave for the list (403
"forbidden" otherwise), leave.record_leave for the rest; a leave the user may not see is 404, as the Django views.
Every route needs a signed-in session (401 without one).
"""

from datetime import date
from typing import Any

from accounts.models import User
from config import batching
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils import timezone
from employees import access as employee_access
from employees.models import Employee
from leave import access
from leave.forms import CancelForm, LeaveForm, active_types
from leave.services import records, writes
from leave.services.form_page import (
    add_initial,
    assisted_lines,
    cancel_info,
    check_for,
    edit_initial,
    own_leave,
)
from leave.services.list_page import banners, list_batch, not_configured_text, parse_filter
from leave.services.rows import LeaveRow, State
from macs.models import LeaveAssign, LeaveTypeRow
from ninja import Query, Router, Schema
from ninja.security import django_auth

from api.errors import ApiError, form_error_payload
from api.params import batch_offset
from api.popups import FORBIDDEN, request_user, service_errors

leave_router = Router(tags=["leave"])

EMPTY_LIST_TEXT = "Чөлөө бүртгэгдээгүй"  # the list's text when no row matches (_rows.html)
CANCEL_MISTAKE_LABEL = "Буруу гэж тэмдэглэх"  # a leave that has started (_rows.html)
CANCEL_LABEL = "Цуцлах"  # a leave that has not started yet
CHIP_STATES = (State.MISTAKE, State.REJECTED)  # the states the row shows as a chip
REPORT_NAME = "annual-leave"


class LeaveChoiceOut(Schema):
    value: int
    label: str


class LeaveFiltersOut(Schema):
    q: str  # the search words (the full name of the person the `employee` link chose)
    employee: int | None  # the link's id, kept even when that person is not visible (rows then empty)
    status: str  # recorded (default), cancelled, mistake, rejected, all, or any other text (matches nothing)
    type_id: int | None
    date_from: str  # YYYY-MM-DD or ""
    date_to: str  # YYYY-MM-DD or ""


class LeaveRowOut(Schema):
    id: int
    employee_id: int
    employee_name: str  # «<family> <given>»
    leave_type: str
    state: str  # the state's label (Бүртгэсэн, Цуцалсан, Буруу бүртгэсэн, Татгалзсан)
    state_chip: bool  # the state is shown as a chip after the type (mistake or rejected)
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    days: int  # working days
    comment: str  # the full text; the screen truncates it
    counts: bool  # False for a cancelled or rejected row: drawn struck through, with no buttons
    cancel_label: str | None  # the cancel button's text; None unless the user may record and the row counts


class LeaveMissingYearOut(Schema):
    year: int
    can_register: bool  # the user may open the public holidays page of that year


class LeaveListOut(Schema):
    filters: LeaveFiltersOut
    rows: list[LeaveRowOut]
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    can_record: bool
    report_url: str | None  # the annual leave report; None without the reports right
    not_configured: str  # «» when the annual leave type is set
    missing_holidays: list[LeaveMissingYearOut]
    types: list[LeaveChoiceOut]
    empty_text: str
    can_settings: bool  # the «Тохиргоо» menu: the user may manage leave settings (perms.leave.manage_leave_settings)


class LeaveAssistedOut(Schema):
    person_line: str  # the chosen person: name, then position and department
    filled_line: str  # what the assistant's sentence filled in


class LeaveOptionsInitialOut(Schema):
    employee: int | None
    leave_type: int | None
    start_date: str  # YYYY-MM-DD or ""
    end_date: str  # YYYY-MM-DD or ""


class LeaveOptionsOut(Schema):
    employees: list[LeaveChoiceOut]
    types: list[LeaveChoiceOut]
    initial: LeaveOptionsInitialOut
    assisted: LeaveAssistedOut | None  # set only when the page was opened from the assistant
    not_configured: str


class LeaveLoadedOut(Schema):
    """The row as the edit and cancel pop-ups loaded it; sent back unchanged so a save refuses a row someone changed."""

    leave_type: int
    date1: str  # YYYY-MM-DD
    date2: str  # YYYY-MM-DD
    status: int | None
    adays: int | None
    comment: str | None  # None when the stored comment is NULL


class LeaveEditInitialOut(Schema):
    employee: int
    leave_type: int
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    note: str
    override_reason: str


class LeaveEditOut(Schema):
    id: int
    initial: LeaveEditInitialOut
    loaded: LeaveLoadedOut
    types: list[LeaveChoiceOut]  # the active types, plus the leave's own type even when it is inactive
    employees: list[LeaveChoiceOut]
    not_configured: str


class LeaveCancelInfoOut(Schema):
    label: str  # the leave type's name
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    mistake: bool  # the leave has started: the cancel marks it «Буруу бүртгэсэн» instead of removing it
    restores_balance: bool  # the type uses the annual balance, so the days come back
    loaded: LeaveLoadedOut


class LeaveWriteIn(Schema):
    """The add and edit forms as posted. Every box may be empty: React sends null, and the form gives its own texts."""

    employee: int | None = None
    leave_type: int | None = None
    start_date: str | None = None  # YYYY-MM-DD
    end_date: str | None = None  # YYYY-MM-DD
    note: str = ""
    override_reason: str = ""


class LeaveUpdateIn(LeaveWriteIn):
    loaded: Any = None  # any JSON value: a non-object or incomplete one is refused as stale


class LeaveCheckIn(LeaveWriteIn):
    leave_id: int | None = None  # the leave being edited; any other id is ignored


class LeaveCancelIn(Schema):
    reason: str = ""
    loaded: Any = None  # any JSON value: a non-object or incomplete one is refused as stale


class LeaveWriteResultOut(Schema):
    ok: bool
    error: str  # the service's message for a refused save («» when none)
    form_errors: list[str]
    field_errors: dict[str, list[str]]


class LeaveCheckPeriodOut(Schema):
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD


class LeaveCheckOut(Schema):
    valid: bool  # False for an invalid form (empty lists and zero days then)
    working_days: int
    balance_after: int | None
    period: LeaveCheckPeriodOut | None
    errors: list[str]
    warnings: list[str]


def _viewer(request: HttpRequest) -> User:
    user = request_user(request)
    if not access.can_view(user):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return user


def _recorder(request: HttpRequest) -> User:
    user = request_user(request)
    if not access.can_record(user):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return user


def _day(value: date | None) -> str:
    return value.isoformat() if value is not None else ""


def _query(**values: str | None) -> dict[str, str]:
    """The typed parameters that were sent (an absent one is left out, as the Django address leaves it out)."""
    return {name: value for name, value in values.items() if value is not None}


def _choices(people: list[Employee]) -> list[LeaveChoiceOut]:
    return [LeaveChoiceOut(value=person.pk, label=str(person)) for person in people]


def _loaded_out(snapshot: writes.AssignSnapshot) -> LeaveLoadedOut:
    return LeaveLoadedOut(
        leave_type=snapshot.leave_type_id,
        date1=snapshot.date1.isoformat(),
        date2=snapshot.date2.isoformat(),
        status=snapshot.status,
        adays=snapshot.adays,
        comment=snapshot.comment,
    )


def _own_leave(user: User, pk: int) -> tuple[LeaveAssign, LeaveRow]:
    """A leave the user may see, with its row; 404 for an invisible or unusable one (form_page.own_leave)."""
    with service_errors():
        return own_leave(user, pk)


def _row_out(row: LeaveRow, person: Employee, may_record: bool, today: date) -> LeaveRowOut:
    cancel_label = None
    if may_record and row.counts:
        cancel_label = CANCEL_MISTAKE_LABEL if row.started(today) else CANCEL_LABEL
    return LeaveRowOut(
        id=row.id,
        employee_id=row.employee_id,
        employee_name=person.full_name,
        leave_type=str(row.leave_type),
        state=row.state.value,
        state_chip=row.state in CHIP_STATES,
        start=row.start.isoformat(),
        end=row.end.isoformat(),
        days=row.days,
        comment=row.comment,
        counts=row.counts,
        cancel_label=cancel_label,
    )


@leave_router.get("", response=LeaveListOut, auth=django_auth)
def leave_list(
    request: HttpRequest,
    response: HttpResponse,
    q: str | None = None,
    employee: str | None = None,
    status: str | None = None,
    type: str | None = None,  # noqa: A002 (the query parameter's name)
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    offset: str = "",
) -> LeaveListOut:
    """One batch of the leave list, newest first. Unknown or junk filter values are dropped, as on the Django page."""
    user = _viewer(request)
    flt = parse_filter(user, _query(q=q, employee=employee, status=status, type=type, to=to, **{"from": from_}))
    today = timezone.localdate()
    start = batch_offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    batch, more = list_batch(user, flt, start, size)
    not_configured, missing = banners(today)
    may_record = access.can_record(user)
    may_settings = access.can_manage_settings(user)
    response["Cache-Control"] = "no-store"
    return LeaveListOut(
        filters=LeaveFiltersOut(
            q=flt.q,
            employee=flt.employee,
            status=flt.status,
            type_id=flt.type_id,
            date_from=_day(flt.start),
            date_to=_day(flt.end),
        ),
        rows=[_row_out(row, person, may_record, today) for row, person in batch],
        next_offset=start + size if more else None,
        can_record=may_record,
        report_url=reverse("reports:report", args=[REPORT_NAME]) if user.has_perm("reports.view_reports") else None,
        not_configured=not_configured,
        missing_holidays=[LeaveMissingYearOut(year=year, can_register=may_settings) for year in missing],
        types=[LeaveChoiceOut(value=t.pk, label=str(t)) for t in LeaveTypeRow.objects.all()],
        empty_text=EMPTY_LIST_TEXT,
        can_settings=may_settings,
    )


# /options is declared before /{pk} so that the word is never read as a leave id.
@leave_router.get("/options", response=LeaveOptionsOut, auth=django_auth)
def leave_options(
    request: HttpRequest,
    employee: str | None = None,
    type: str | None = None,  # noqa: A002 (the query parameter's name)
    start: str | None = None,
    end: str | None = None,
    from_: str | None = Query(None, alias="from"),
) -> LeaveOptionsOut:
    """The choices of the add pop-up and its first values. `from=assistant` adds the assistant's two lines."""
    user = _recorder(request)
    employees = employee_access.visible_employees(user)
    today = timezone.localdate()
    query = _query(employee=employee, type=type, start=start, end=end, **{"from": from_})
    initial, filled = add_initial(query, employees, today)
    employee_pk = initial.get("employee")
    assisted = None
    if query.get("from") == "assistant":
        assisted = LeaveAssistedOut(**assisted_lines(user, employee_pk, filled, today))
    return LeaveOptionsOut(
        employees=_choices(list(employees.order_by("family_name", "given_name"))),
        types=[LeaveChoiceOut(value=t.pk, label=str(t)) for t in active_types()],
        initial=LeaveOptionsInitialOut(
            employee=employee_pk,
            leave_type=initial.get("leave_type"),
            start_date=_day(initial.get("start_date")),
            end_date=_day(initial.get("end_date")),
        ),
        assisted=assisted,
        not_configured=not_configured_text(),
    )


# /check is declared before /{pk} so that the word is never read as a leave id.
@leave_router.post("/check", response=LeaveCheckOut, auth=django_auth)
def leave_check_form(request: HttpRequest, payload: LeaveCheckIn) -> LeaveCheckOut:
    """The live check of the form as posted: working days, the period and the balance after. An invalid form answers
    valid false with empty lists; a leave_id the user may not see is ignored (check_for)."""
    user = _recorder(request)
    form = LeaveForm(_form_data(payload), employees=employee_access.visible_employees(user))
    found = check_for(user, form, payload.leave_id, timezone.localdate())
    if found is None:
        return LeaveCheckOut(valid=False, working_days=0, balance_after=None, period=None, errors=[], warnings=[])
    period = None
    if found.period is not None:
        period = LeaveCheckPeriodOut(start=found.period.start.isoformat(), end=found.period.end.isoformat())
    return LeaveCheckOut(
        valid=not found.errors,
        working_days=found.working_days,
        balance_after=found.balance_after,
        period=period,
        errors=found.errors,
        warnings=found.warnings,
    )


@leave_router.get("/{pk}", response=LeaveEditOut, auth=django_auth)
def leave_edit_load(request: HttpRequest, response: HttpResponse, pk: int) -> LeaveEditOut:
    """The edit pop-up's first values and the row as loaded. 404 for a leave the user may not see."""
    user = _recorder(request)
    a, row = _own_leave(user, pk)
    employees = employee_access.visible_employees(user)
    first = edit_initial(a, row)
    response["Cache-Control"] = "no-store"
    return LeaveEditOut(
        id=a.pk,
        initial=LeaveEditInitialOut(
            employee=first["employee"],
            leave_type=first["leave_type"],
            start_date=_day(first["start_date"]),
            end_date=_day(first["end_date"]),
            note=first["note"],
            override_reason=first["override_reason"],
        ),
        loaded=_loaded_out(writes.snapshot(a)),
        types=[LeaveChoiceOut(value=t.pk, label=str(t)) for t in active_types(a.leave_type)],
        employees=_choices(list(employees.order_by("family_name", "given_name"))),
        not_configured=not_configured_text(),
    )


@leave_router.get("/{pk}/cancel", response=LeaveCancelInfoOut, auth=django_auth)
def leave_cancel_info(request: HttpRequest, response: HttpResponse, pk: int) -> LeaveCancelInfoOut:
    """What the cancel pop-up asks. 404 for a leave the user may not see."""
    user = _recorder(request)
    a, row = _own_leave(user, pk)
    info = cancel_info(a, row, timezone.localdate())
    response["Cache-Control"] = "no-store"
    return LeaveCancelInfoOut(
        label=info.label,
        start=info.start.isoformat(),
        end=info.end.isoformat(),
        mistake=info.mistake,
        restores_balance=info.restores_balance,
        loaded=_loaded_out(writes.snapshot(a)),
    )


# --- writes -------------------------------------------------------------------------------------------------------
# Every write answers 200 with the one LeaveWriteResultOut shape: ok true, or ok false with the form's own errors
# (field_errors, form_errors) or the service's message (error). A refused write changes nothing.


def _saved() -> dict[str, Any]:
    return {"ok": True, "error": "", "form_errors": [], "field_errors": {}}


def _refused_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message, "form_errors": [], "field_errors": {}}


def _refused_form(form: LeaveForm | CancelForm) -> dict[str, Any]:
    payload = form_error_payload(form)
    return {"ok": False, "error": "", "form_errors": payload["form_errors"], "field_errors": payload["field_errors"]}


def _int_value(raw: Any) -> int:
    """A whole number as the API sends it: a JSON int or a string of digits. Anything else raises ValueError."""
    if isinstance(raw, bool) or not (isinstance(raw, int) or (isinstance(raw, str) and raw.isdecimal())):
        raise ValueError(raw)
    return int(raw)


def _optional_int(raw: Any) -> int | None:
    """None or "" stays None (as forms.loaded_from_post reads an empty hidden field); anything else is a number."""
    if raw is None or raw == "":
        return None
    return _int_value(raw)


def _day_value(raw: Any) -> date:
    if not isinstance(raw, str):
        raise ValueError(raw)
    return date.fromisoformat(raw)


def _loaded_from_api(raw: Any) -> writes.AssignSnapshot | None:
    """The loaded row as the save sends it back, read as forms.loaded_from_post reads the hidden fields. None when
    `raw` is not an object, or a required field is missing or malformed: the caller answers writes.STALE. An absent or
    null comment is NULL; a text (maybe empty) is kept as it is."""
    if not isinstance(raw, dict):
        return None
    try:
        comment = raw.get("comment")
        if comment is not None and not isinstance(comment, str):
            return None
        return writes.AssignSnapshot(
            leave_type_id=_int_value(raw.get("leave_type")),
            date1=_day_value(raw.get("date1")),
            date2=_day_value(raw.get("date2")),
            status=_optional_int(raw.get("status")),
            adays=_optional_int(raw.get("adays")),
            comment=comment,
        )
    except ValueError:
        return None


def _form_data(payload: LeaveWriteIn) -> dict[str, str]:
    """The posted add or edit form as the browser would send it: an empty box is an empty text, not a missing key."""
    return {
        "employee": "" if payload.employee is None else str(payload.employee),
        "leave_type": "" if payload.leave_type is None else str(payload.leave_type),
        "start_date": payload.start_date or "",
        "end_date": payload.end_date or "",
        "note": payload.note,
        "override_reason": payload.override_reason,
    }


@leave_router.post("", response=LeaveWriteResultOut, auth=django_auth)
def leave_create(request: HttpRequest, payload: LeaveWriteIn) -> dict[str, Any]:
    """Record a leave (the add pop-up). The same form and service as the Django add view."""
    user = _recorder(request)
    form = LeaveForm(_form_data(payload), employees=employee_access.visible_employees(user))
    if not form.is_valid():
        return _refused_form(form)
    try:
        records.record(form.draft(), user, timezone.localdate())
    except records.LeaveError as exc:
        return _refused_error(str(exc))
    return _saved()


@leave_router.post("/{pk}", response=LeaveWriteResultOut, auth=django_auth)
def leave_update(request: HttpRequest, pk: int, payload: LeaveUpdateIn) -> dict[str, Any]:
    """Change a recorded leave. A missing or malformed `loaded` or a row another program changed is refused as stale.
    404 for a leave the user may not see (the rights are checked first: 403 for a user who may not record)."""
    user = _recorder(request)
    a, _row = _own_leave(user, pk)
    loaded = _loaded_from_api(payload.loaded)
    if loaded is None:
        return _refused_error(writes.STALE)
    form = LeaveForm(_form_data(payload), employees=employee_access.visible_employees(user), current_type=a.leave_type)
    if not form.is_valid():
        return _refused_form(form)
    try:
        records.update(a, form.draft(leave_id=a.pk, loaded=loaded), user, timezone.localdate())
    except records.LeaveError as exc:
        return _refused_error(str(exc))
    return _saved()


@leave_router.post("/{pk}/cancel", response=LeaveWriteResultOut, auth=django_auth)
def leave_cancel_write(request: HttpRequest, pk: int, payload: LeaveCancelIn) -> dict[str, Any]:
    """Cancel a leave: one not started yet is removed, one that has started is marked «Буруу бүртгэсэн». The same rules
    and messages as the Django cancel view. 404 for a leave the user may not see."""
    user = _recorder(request)
    a, _row = _own_leave(user, pk)
    posted = _loaded_from_api(payload.loaded)
    if posted is None:
        return _refused_error(writes.STALE)
    form = CancelForm({"reason": payload.reason})
    if not form.is_valid():
        return _refused_form(form)
    try:
        records.cancel(a, posted, form.cleaned_data["reason"], user, timezone.localdate())
    except records.LeaveError as exc:
        return _refused_error(str(exc))
    return _saved()
