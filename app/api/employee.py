"""GET /api/v1/employees/{pk}: the employee page's header, rail and rights, as the React employee page calls it.

The facts come from employees.services.detail_page.detail_facts (the same dict the Django page renders). This module
only presents them: the display strings (dates, «Хугацаагүй», the period text), the state label and tone, the header's
latest-activity line, and the one-time login that the hire form leaves in the session. The Work, Salary, Personal and
Activity parts have their own endpoints.
"""

from datetime import date
from typing import Any, Literal

from accounts.models import User
from checklists.models import ChecklistState
from django.http import HttpRequest, HttpResponse
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator
from employees import access, sections, stale
from employees.models import ActivityEntry, ContractType, Employee, Event, OrderState, ext_of
from employees.services.detail_page import ACTIVITY_BATCH, detail_facts
from employees.services.form_schema import describe_field
from employees.templatetags.hr import day_label, mnt, thumb
from employees.views import ONE_TIME_LOGIN_KEY, ORDER_WARNING_KEY
from leave.models import GrantKind
from leave.services import entitlement
from lists.registry import QUICK, QUICK_BY_MODEL
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from api.popups import FieldAddOut

employee_router = Router(tags=["employees"])

_NOT_FOUND = "Хуудас олдсонгүй"
_OPEN_ENDED_LABEL = "Хугацаагүй"
_ACTIVITY_HEADER_CHARS = 70  # the header's «Сүүлийн өөрчлөлт» line is cut to this many characters (truncatechars:70)

# The `_state.html` tone classes, copied verbatim. A state outside the first three is «Гарсан» (the template's else).
_STATE_TONE = {
    "upcoming": "rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 "
    "ring-1 ring-inset ring-amber-300",
    "active": "rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800",
    "long_leave": "rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-900 ring-1 ring-inset ring-sky-300",
    "left": "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700",
}


class FactsOut(Schema):
    position: str  # "" when no job on today's date
    department: str
    position_line: str  # the header's «position · department» line (_header.html), "" without a job on today's date
    manager: str  # the manager's full name, "" without one (the rail)
    manager_label: (
        str  # the manager as Employee.__str__ writes it («CODE Full Name»), "" without one (the mobile strip)
    )
    first_hire_date: str  # YYYY-MM-DD, "" when none
    work_phone: str
    employee_type: str  # the type's name, "" when none
    contract_end: str  # YYYY-MM-DD; «Хугацаагүй» for an open-ended contract; "" otherwise


class StateOut(Schema):
    key: str  # upcoming | active | long_leave | left
    label: str
    tone: str  # the badge's class string


class NextEventOut(Schema):
    text: str  # «<change type> · YYYY-MM-DD»


class LatestActivityOut(Schema):
    by: str  # the person's name, or «Систем»
    at: str  # «өнөөдөр HH:MM» or «YYYY-MM-DD HH:MM»
    text: str  # the first change as «field: old → new», or the message cut to 70 characters


class SetupItemOut(Schema):
    key: str
    label: str
    done: bool
    auto: bool  # set by the system (the bank item); cannot be ticked
    note: str  # «<who> · YYYY-MM-DD HH:MM» for a ticked item by a person, "" otherwise


class SetupOut(Schema):
    items: list[SetupItemOut]
    done: int
    total: int
    complete: bool
    percent: int  # the progress bar's width: Django's widthratio done total 100, rounded
    progress_text: str  # «done/total хийгдсэн» (the card's text while incomplete)


class EventMenuItemOut(Schema):
    value: str
    label: str


class CanOut(Schema):
    manage: bool
    create_login: bool  # «Нэвтрэх эрх үүсгэх»: may manage and the employee has no login yet
    view_salary: bool
    manage_salary: bool
    view_personal: bool
    record_leave: bool


class OneTimeLoginOut(Schema):
    username: str
    password: str


class EmployeeHeadOut(Schema):
    pk: int
    full_name: str
    family_name: str  # raw names: the header's inputs when the user may manage
    given_name: str
    given_initial: str  # the first letter of the given name (the placeholder square)
    code: str
    email: str
    photo_url: str  # "" when there is no photo
    photo_srcset: str  # the 2x and 3x thumbnails of the header photo, "" when there is no photo
    facts: FactsOut
    state: StateOut
    next_event: NextEventOut | None
    leave_left: str | None  # the current leave period's days left; None without the leave right or a period
    latest_activity: LatestActivityOut | None
    activity_count: int
    setup: SetupOut | None  # None: the onboarding checklist is not shown to this user
    event_menu: list[EventMenuItemOut]
    can: CanOut
    one_time_login: OneTimeLoginOut | None  # once: the hire form's password, removed from the session on this read


class ChipOut(Schema):
    label: str
    tone: str  # the chip's class string, copied from the template it mirrors


class JobRowOut(Schema):
    pk: int | None  # the history row's job record (None for a cancelled change, which has none)
    event_id: int | None  # the change behind the row (the «Цуцлах» link's id); None without one
    label: str
    scheduled: bool  # «Төлөвлөсөн» badge
    is_cancelled: bool  # struck-through row: position, department and status show «—»
    position: str
    department: str
    status: str
    order_no: str  # «№ N / YYYY», «—» without an order
    cancel_note: str  # «(цуцалсан: № N)» when the order is cancelled and names its cancelling order, else ""
    order_pk: int | None  # the row opens this order's React pop-up
    order_chip: ChipOut | None
    period_text: str  # the period text, e.g. «2026-01-05 – одоо» or «2026-01-05 – 2026-06-30»
    period_note: str  # the grey note after the text, «(2026-08-01 буцна)» on a long leave, else ""
    cancellable: bool  # «Цуцлах» button, opens the React cancel pop-up
    correctable: bool  # «Засвар» button, opens the React edit pop-up
    clickable: bool  # the row opens its order's React pop-up: the row has an order
    order_no_muted: bool  # the order cell shows the grey «—» (no order, or an order without a number)


class WaitingOut(Schema):
    event_pk: int
    label: str
    effective: str  # YYYY-MM-DD
    order_no: str
    order_pk: int | None
    chip: ChipOut  # «Гарын үсэг хүлээж байна»
    cancellable: bool
    clickable: bool  # the row opens its order's React pop-up: the row has an order
    order_no_muted: bool  # the order cell shows the grey «—»


class CancelOut(Schema):
    order_pk: int
    text_prefix: str  # «(№ N тушаалыг цуцалсан: » before the link
    link_text: str  # «харах»: the link to the cancelling order's popup (legacy)
    suffix: str  # «)»


class OtherOrderOut(Schema):
    order_pk: int | None  # None for a MACS command row (read-only)
    legacy: bool
    number: str  # «№ N / YYYY», «—» without a number
    number_muted: bool  # the number cell shows the grey «—»
    date: str  # YYYY-MM-DD or «—»
    type_label: str  # the order type's label, «—» for a MACS row
    hire_note: str  # «(ажилд авсан)» (its own grey span) for a hire, else ""
    summary: str
    cancel_prefix: str  # «(цуцлах тушаал: » when cancelled with a cancelling number, else ""
    cancel_number: str  # «№ N», the link to the cancelling order (legacy) when cancelled_by_pk is set, else plain text
    cancel_suffix: str  # «)» when cancel_prefix is set, else ""
    cancelled_by_pk: int | None  # the cancelling order is one of ours (its React pop-up opens from the link)
    cancels: list[CancelOut]
    chip: ChipOut
    cancelled: bool  # struck-through row
    can_edit: bool  # the row opens the React edit pop-up
    can_upload: bool  # «Файл хавсаргах» in the actions menu, opens the React upload pop-up
    scan_url: str  # «Файл харах» target, "" when not shown
    word_url: str  # «Word татах», "" when not shown
    pdf_url: str  # «PDF татах», "" when not shown


class LeaveLineOut(Schema):
    label: str  # «Авсан»
    text: str  # «YYYY-MM-DD – YYYY-MM-DD, N өдөр»
    old_chip: bool  # «Хуучин системээс»


class LeaveGrantOut(Schema):
    label: str  # the grant kind's label
    days: str  # «N хоног»
    breakdown: str
    comment: str
    old_chip: bool


class OldAbsenceOut(Schema):
    date: str  # «from» or «from – to»
    name: str
    note: str


class LeavePeriodOut(Schema):
    period_text: str  # «YYYY-MM-DD – YYYY-MM-DD»
    row_class: str  # the year's <tbody> class string (the current year is tinted)
    period_class: str  # the period text's class: «font-semibold» when current, else «font-medium»
    badge: ChipOut | None  # «Одоо» or «Ирэх»
    current: bool
    old: bool  # an earlier year: folded away when there is a current or upcoming year
    granted: str
    taken: str
    left: str
    left_tone: str
    doubled_note: str  # the warning line when two grants share the period, else ""
    grants: list[LeaveGrantOut]
    leaves: list[LeaveLineOut]


class LeaveOut(Schema):
    visible: bool
    configured: bool
    start_missing: bool  # no start date: no leave year can be counted
    periods: list[LeavePeriodOut]
    old_count: int  # the periods folded away (old ones)
    fold_old: bool  # the fold toggle shows: there are old periods and at least one other period
    fold_show_label: str  # the toggle while the old years are folded: «Өмнөх N жил харах ▾», "" when no fold
    fold_hide_label: str  # the toggle while they are open: «Өмнөх жилүүдийг нуух ▴», "" when no fold
    no_year_started: bool  # «Ажлын жил эхлээгүй байна.» (no period, configured, start known)
    nowhere: list[LeaveLineOut]
    old_absences: list[OldAbsenceOut]
    can_record: bool  # «Чөлөө бүртгэх» (legacy popup)
    can_manage_settings: bool
    settings_url: str
    all_leaves_url: str


class EmployeeTaskOut(Schema):
    title: str
    required: bool
    owner_label: str
    due_on: str
    overdue: bool
    done: bool
    done_label: str  # «Хийгдсэн» (emphasised green) when done, else ""
    done_rest: str  # « · name, YYYY-MM-DD» when done, else «—»
    title_class: str  # the title cell's class: «text-slate-500» when done, else ""
    due_class: str  # the due-date cell's class string (red and bold when overdue)
    can_tick: bool  # «Хийгдсэн» button (legacy)
    can_untick: bool  # «Буцаах» button (legacy)


class PanelOut(Schema):
    kind: str
    heading: str
    caption: str  # «<template> · <date caption> YYYY-MM-DD», "" without a checklist
    checklist: bool  # False: the start form (or nothing)
    completed: bool
    progress: str  # «done / total», "" without a checklist
    today: str  # ISO day the start form pre-fills (the page's today)
    can_start: bool  # start form (legacy)
    can_cancel: bool  # «Цуцлах» (legacy)
    rows: list[EmployeeTaskOut]


class WorkFieldOut(Schema):
    name: str  # the form field's HTML name (the page-form field the soft box posts, e.g. «office», «sector_years»)
    kind: str  # the widget the Django soft box renders: "select", "date" or "number" (_tab_work.html)
    value: str  # the box's raw value: a select's stored code (a foreign key's pk), an ISO date, a number; "" if empty
    choice: str  # a select's current option text (the combo box's text; "" for the blank option); "" for other kinds
    combo: bool  # a select with a quick-add list: Django draws it as a combo text box, not a native select
    text: str  # the read-only text the template prints when the user cannot manage («—» default)
    aria_label: str  # the form field's accessible name (Django's label, e.g. «Салбарт ажилласан жил»)
    add: FieldAddOut | None = None  # the quick-add list behind «+ нэмэх»; null when the field is not addable


class EmployeeWorkOut(Schema):
    order_warning: str  # one-shot warning from a number clash; read and removed on this request
    can_manage: bool  # the soft (edit-on-the-spot) fields show as inputs, readOnly until step 3b
    transfer_chip: bool  # «өөрчлөх» chips beside position, department and manager (legacy)
    position: str
    department: str
    manager: str
    second_position: WorkFieldOut
    office: WorkFieldOut
    section: WorkFieldOut
    branch: WorkFieldOut
    employee_type: str
    contract_type: str
    contract_no: str
    contract_chip: bool  # «өөрчлөх» chip beside the contract (legacy)
    contract_start: str
    contract_end: str  # the contract's end date, "" when none
    contract_end_label: str  # «Гэрээ дуусах»: date, «Хугацаагүй» or «—»
    probation_end: WorkFieldOut
    first_hire_date: WorkFieldOut | None  # the soft box, only when can_manage (None otherwise)
    job_type: WorkFieldOut
    job_figure: WorkFieldOut
    work_conditions: WorkFieldOut
    work_schedule: WorkFieldOut
    sector_years: WorkFieldOut
    macs_contract_no: str
    macs_contract_period: str
    macs_taken_leave: str
    macs_leave_type: str
    macs_probation_months: str
    macs_last_order_no: str
    macs_last_order_text: str
    waiting: list[WaitingOut]
    jobs: list[JobRowOut]
    orders_count: int  # the «Бусад тушаал» heading count
    orders: list[OtherOrderOut]
    leave: LeaveOut
    checklist_visible: bool
    checklists: list[PanelOut]


class EmployeeSalaryRowOut(Schema):
    pk: int  # the SalaryRecord (the «Засвар» link's id)
    event_id: int | None  # the change behind the row (the «Цуцлах» link's id); None without one
    period_text: str  # «YYYY-MM-DD – YYYY-MM-DD», «YYYY-MM-DD – одоо», or «YYYY-MM-DD –» for a scheduled open end
    amount: str  # the pay as mnt, e.g. «2,500,000₮»
    label: str  # the change's name
    scheduled: bool  # starts after today
    scheduled_label: str  # «Төлөвлөсөн» for a scheduled row, "" otherwise
    cancellable: bool  # the user may cancel the change
    correctable: bool  # the «Засвар» button is shown
    action_label: str  # «Цуцлах», «Засвар», or "" when the row has no button
    action_class: str  # the button's class string («Цуцлах» red, «Засвар» violet); "" without a button


class EmployeeBankFieldOut(Schema):
    name: str  # the form field's HTML name, «si-» prefixed (e.g. «si-bank», «si-account_no»)
    label: str  # the row's label, in template order
    aria_label: str  # the form field's accessible name (Django's label, e.g. «НДД-ийн дугаар»)
    kind: Literal["select", "text", "checkbox"]  # the soft box Django renders: a select, a text box or a checkbox
    value: str  # the box's raw value: a select's stored pk, a text box's text, "" when empty
    choice: str  # a select's current option label («---------» when none); "" for the other kinds
    text: str  # the read-only text shown when the user cannot manage («—» default; «Тийм» / «Үгүй» for the flag)
    checked: bool  # the checkbox state (kind == checkbox)
    add: FieldAddOut | None = None  # the select's quick-add info; null when the box is not addable


class EmployeeSalaryOut(Schema):
    current: str | None  # today's pay as mnt; None when not set
    missing_label: str  # «тогтоогоогүй» when no current pay, "" otherwise
    rows: list[EmployeeSalaryRowOut]
    has_rows: bool
    can_set: bool  # the «Цалин тогтоох» button: may manage salary and there is no history yet
    set_label: str  # «Цалин тогтоох» when can_set, "" otherwise
    editable: bool  # the «Банк, даатгал» fields show as soft inputs (readOnly until step 3b)
    bank_fields: list[EmployeeBankFieldOut]  # in template order


_ORDER_TONE = {
    "registered": "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-900",
    "signed": "seal",
}
_ORDER_TONE_DEFAULT = "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700"
_AWAITING_CHIP = ChipOut(
    label="Гарын үсэг хүлээж байна",
    tone="whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs "
    "text-amber-900 no-underline",
)
_DOUBLED_NOTE = "Энэ хугацаанд давхардсан эрх байна. Үлдэгдлийг бүртгэдэг системд засна уу."
_OLD_CHIP_COMMENT = "Хуучин системээс"


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _iso(value: date | None) -> str:
    return value.isoformat() if value is not None else ""


def _fk_text(obj: Any) -> str:
    """A related record's text, "" when the foreign key is empty (never the text «None»)."""
    return str(obj) if obj is not None else ""


def _facts_out(employee: Employee, job: Any) -> dict[str, str]:
    if job is None:
        contract_end = ""
    elif job.contract_end:
        contract_end = job.contract_end.isoformat()
    elif job.contract_type == ContractType.OPEN_ENDED:
        contract_end = _OPEN_ENDED_LABEL
    else:
        contract_end = ""
    position = _fk_text(job.position) if job is not None else ""
    department = _fk_text(job.department) if job is not None else ""
    return {
        "position": position,
        "department": department,
        # _header.html: position, then ` · department` when a job is in force today (none without one)
        "position_line": f"{position} · {department}" if job is not None else "",
        "manager": job.manager.full_name if job is not None and job.manager is not None else "",
        "manager_label": str(job.manager) if job is not None and job.manager is not None else "",
        "first_hire_date": _iso(employee.first_hire_date),
        "work_phone": employee.work_phone or "",
        "employee_type": job.get_employee_type_display() if job is not None and job.employee_type else "",
        "contract_end": contract_end,
    }


def _state_out(state: str, job: Any, until: date | None) -> dict[str, str]:
    key = state if state in ("upcoming", "active", "long_leave") else "left"
    if key == "upcoming":
        start = job.period.lower if job is not None else None
        label = f"Ажилд орох: {_iso(start)}"
    elif key == "active":
        label = "Ажиллаж байгаа"
    elif key == "long_leave":
        label = "Урт чөлөөтэй" + (f" · {until.isoformat()} хүртэл" if until is not None else "")
    else:
        label = "Гарсан"
    return {"key": key, "label": label, "tone": _STATE_TONE[key]}


def _next_event_out(event: Event | None) -> dict[str, str] | None:
    if event is None:
        return None
    return {"text": f"{event.get_type_display()} · {event.effective.isoformat()}"}


def _latest_out(entry: ActivityEntry | None, today: date) -> dict[str, str] | None:
    if entry is None:
        return None
    if entry.by is not None:
        by = entry.by.get_full_name() or entry.by.username
    else:
        by = "Систем"
    local = timezone.localtime(entry.at)
    at = f"өнөөдөр {local:%H:%M}" if local.date() == today else f"{local:%Y-%m-%d %H:%M}"
    change = entry.header_change
    if change:
        old = f"{change.get('old')} → " if change.get("old") else ""
        text = f"{change.get('field', '')}: {old}{change.get('new') or '(хоосон)'}"
    else:
        text = Truncator(entry.message).chars(_ACTIVITY_HEADER_CHARS)
    return {"by": by, "at": at, "text": text}


def _setup_out(facts: dict[str, Any]) -> dict[str, Any] | None:
    items = facts["setup"]
    if items is None:
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        note = ""
        if item.done and not item.auto:
            by = str(item.done_by) if item.done_by is not None else "—"
            note = f"{by} · {timezone.localtime(item.done_at):%Y-%m-%d %H:%M}"
        out.append({"key": item.key, "label": item.label, "done": item.done, "auto": item.auto, "note": note})
    total = len(items)
    percent = round(facts["setup_done"] / total * 100) if total else 0
    return {
        "items": out,
        "done": facts["setup_done"],
        "total": total,
        "complete": facts["setup_complete"],
        "percent": percent,
        "progress_text": f"{facts['setup_done']}/{total} хийгдсэн",
    }


def _leave_left(facts: dict[str, Any]) -> str | None:
    if not facts.get("leave_visible"):
        return None
    period = next((p for p in facts.get("leave_periods", []) if p.current), None)
    return str(floatformat(period.left, "-1")) if period is not None else None


def _photo(employee: Employee) -> tuple[str, str]:
    """The header photo and its srcset: each size (80, 160, 240) is computed once, and only when there is a photo."""
    photo = thumb(employee, 80)
    if not photo:
        return "", ""
    two_x, three_x = thumb(employee, 160), thumb(employee, 240)
    return photo, f"{two_x} 2x, {three_x} 3x"


def _one_time_login(request: HttpRequest, employee: Employee) -> dict[str, str] | None:
    """The hire form's password: returned once and removed from the session (as employees.views.employee_detail)."""
    pending = request.session.get(ONE_TIME_LOGIN_KEY)
    if not isinstance(pending, dict) or pending.get("employee") != employee.pk:
        return None
    del request.session[ONE_TIME_LOGIN_KEY]
    return {"username": str(pending.get("username", "")), "password": str(pending.get("password", ""))}


@employee_router.get("/{pk}", auth=django_auth, response=EmployeeHeadOut)
def employee_head(request: HttpRequest, response: HttpResponse, pk: int) -> dict[str, Any]:
    """The header, rail and rights of one employee the signed-in user may see (404 otherwise)."""
    user = _user(request)
    employee = access.visible_employees(user).filter(pk=pk).first()
    if employee is None:
        raise HttpError(404, _NOT_FOUND)
    today = timezone.localdate()
    facts = detail_facts(user, employee, today)
    row_job = facts["row"].job
    photo_url, srcset = _photo(employee)
    ext = ext_of(employee)
    has_login = ext is not None and ext.user_id is not None
    one_time = _one_time_login(request, employee)
    if one_time is not None:
        response["Cache-Control"] = "no-store"  # the page must not come back from the Back cache with the password
    return {
        "pk": employee.pk,
        "full_name": employee.full_name,
        "family_name": employee.family_name or "",
        "given_name": employee.given_name or "",
        "given_initial": employee.given_name[:1],
        "code": employee.code or "",
        "email": employee.email or "",
        "photo_url": photo_url,
        "photo_srcset": srcset,
        "facts": _facts_out(employee, row_job),
        "state": _state_out(facts["row"].state, row_job, facts["leave_until"]),
        "next_event": _next_event_out(facts["next_event"]),
        "leave_left": _leave_left(facts),
        "latest_activity": _latest_out(facts["latest_activity"], today),
        "activity_count": facts["activity_count"],
        "setup": _setup_out(facts),
        "event_menu": [{"value": value, "label": label} for value, label in facts["event_menu"]],
        "can": {
            "manage": facts["can_manage"],
            "create_login": facts["can_manage"] and not has_login,
            "view_salary": facts["can_view_salary"],
            "manage_salary": facts["can_manage_salary"],
            "view_personal": facts["can_view_personal"],
            "record_leave": bool(facts.get("can_record_leave", False)),
        },
        "one_time_login": one_time,
    }


def _default(value: Any, fallback: str = "—") -> str:
    """Django's `|default:"—"`: the value's text, or the fallback when the value is empty or None."""
    return str(value) if value else fallback


def _order_no(order: Any) -> str:
    """«№ N / YYYY» of an order (the year only with a date), «—» without an order or a number."""
    if order is None or not order.number:
        return "—"
    return f"№ {order.number}" + (f" / {order.date:%Y}" if order.date else "")


def _order_chip(order: Any) -> ChipOut:
    return ChipOut(label=order.get_state_display(), tone=_ORDER_TONE.get(order.state, _ORDER_TONE_DEFAULT))


def _period_parts(job: Any) -> tuple[str, str]:
    """The history row's period as the template prints it: (text, note). The note is the grey «(… буцна)» of a long
    leave, printed after the text in its own span; "" otherwise. A cancelled change shows its effective date only."""
    if job.is_cancelled:
        return _iso(job.effective), ""
    text = f"{_iso(job.period.lower)} –"
    note = ""
    if job.period.upper:
        text += f" {_iso(job.period.upper)}"
    elif job.status == "long_leave" and job.event is not None and job.event.expected_return:
        note = f"({_iso(job.event.expected_return)} буцна)"
    elif not job.scheduled:
        text += " одоо"
    return text, note


def _job_out(job: Any, can_manage: bool) -> dict[str, Any]:
    cancelled = bool(job.is_cancelled)
    order = job.order
    cancel_note = ""
    if order is not None and order.state == OrderState.CANCELLED and order.cancel_order_no:
        cancel_note = f"(цуцалсан: № {order.cancel_order_no})"
    cancellable = not cancelled and bool(getattr(job, "cancellable", False))  # no «Цуцлах» on a struck-through row
    locked = bool(getattr(job, "locked", False))
    period_text, period_note = _period_parts(job)
    return {
        "pk": getattr(job, "pk", None),
        "event_id": getattr(job, "event_id", None),
        "label": job.label,
        "scheduled": bool(getattr(job, "scheduled", False)),
        "is_cancelled": cancelled,
        "position": "—" if cancelled else str(job.position),
        "department": "—" if cancelled else str(job.department),
        "status": "—" if cancelled else job.get_status_display(),
        "order_no": _order_no(order),
        "cancel_note": cancel_note,
        "order_pk": order.pk if order is not None else None,
        "order_chip": _order_chip(order) if order is not None else None,
        "period_text": period_text,
        "period_note": period_note,
        "cancellable": cancellable,
        "correctable": not cancelled and not cancellable and can_manage and not locked,
        "clickable": order is not None,
        "order_no_muted": _order_no(order) == "—",
    }


def _waiting_out(waiting: Any) -> dict[str, Any]:
    order = waiting.order
    return {
        "event_pk": waiting.event.pk,
        "label": waiting.label,
        "effective": _iso(waiting.event.effective),
        "order_no": _order_no(order),
        "order_pk": order.pk if order is not None else None,
        "chip": _AWAITING_CHIP,
        "cancellable": bool(waiting.cancellable),
        "clickable": order is not None,
        "order_no_muted": _order_no(order) == "—",
    }


def _other_order_out(row: dict[str, Any], employee_pk: int, can_manage: bool) -> dict[str, Any]:
    """One row of «Бусад тушаал»: ours (with its menu links) or a MACS command (read-only)."""
    order, legacy = row["order"], row["legacy"]
    if order is None:
        return {
            "order_pk": None,
            "legacy": True,
            "number": f"№ {legacy.number}",
            "number_muted": False,
            "date": _iso(legacy.date) or "—",
            "type_label": "—",
            "hire_note": "",
            "summary": legacy.summary or "",
            "cancel_prefix": "",
            "cancel_number": "",
            "cancel_suffix": "",
            "cancelled_by_pk": None,
            "cancels": [],
            "chip": ChipOut(label="MACS", tone=_ORDER_TONE_DEFAULT),
            "cancelled": False,
            "can_edit": False,
            "can_upload": False,
            "scan_url": "",
            "word_url": "",
            "pdf_url": "",
        }
    cancelled = order.state == OrderState.CANCELLED
    cancel_prefix = cancel_number = cancel_suffix = ""
    cancelled_by_pk = None
    if cancelled and order.cancel_order_no:
        cancel_prefix = "(цуцлах тушаал: "
        cancel_number = f"№ {order.cancel_order_no}"
        cancel_suffix = ")"
        cancelled_by_pk = row["cancelled_by"].pk if row.get("cancelled_by") is not None else None
    documents = can_manage and not cancelled
    scan = bool(order.file) and bool(row.get("scan_ok"))
    return {
        "order_pk": order.pk,
        "legacy": False,
        "number": _order_no(order),
        "number_muted": not order.number,
        "date": _iso(order.date) or "—",
        "type_label": order.get_order_type_display(),
        "hire_note": "(ажилд авсан)" if order.is_hire else "",
        "summary": order.summary or "",
        "cancel_prefix": cancel_prefix,
        "cancel_number": cancel_number,
        "cancel_suffix": cancel_suffix,
        "cancelled_by_pk": cancelled_by_pk,
        "cancels": [
            {
                "order_pk": c.pk,
                "text_prefix": f"(№ {c.number} тушаалыг цуцалсан: ",
                "link_text": "харах",
                "suffix": ")",
            }
            for c in row.get("cancels", [])
        ],
        "chip": _order_chip(order),
        "cancelled": cancelled,
        "can_edit": can_manage and order.state in (OrderState.PENDING, OrderState.REGISTERED),
        "can_upload": can_manage and order.state == OrderState.REGISTERED,
        "scan_url": f"/api/v1/employees/{employee_pk}/orders/{order.pk}/file" if scan else "",
        "word_url": f"/api/v1/employees/{employee_pk}/orders/{order.pk}/document" if documents else "",
        "pdf_url": f"/api/v1/employees/{employee_pk}/orders/{order.pk}/document/pdf" if documents else "",
    }


def _days(value: Any) -> str:
    return str(floatformat(value, "-1"))


def _line_out(label: str, start: Any, end: Any, days: Any, old: bool) -> dict[str, Any]:
    return {"label": label, "text": f"{_iso(start)} – {_iso(end)}, {_days(days)} өдөр", "old_chip": bool(old)}


def _period_out(period: Any) -> dict[str, Any]:
    if period.current:
        badge = ChipOut(
            label="Одоо", tone="ml-2 rounded-full bg-amber-200 px-2 py-0.5 text-xs font-semibold text-amber-900"
        )
    elif period.upcoming:
        badge = ChipOut(label="Ирэх", tone="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600")
    else:
        badge = None
    if period.left < 0:
        tone = "bg-red-100 text-red-700"
    elif period.left > 0:
        tone = "bg-emerald-100 text-emerald-800"
    else:
        tone = "bg-slate-100 text-slate-500"
    return {
        "period_text": f"{_iso(period.start)} – {_iso(period.end)}",
        "row_class": "group border-b border-slate-100 last:border-0" + (" bg-amber-50/60" if period.current else ""),
        "period_class": "font-semibold" if period.current else "font-medium",
        "badge": badge,
        "current": bool(period.current),
        "old": not period.current and not period.upcoming,
        "granted": _days(period.granted),
        "taken": _days(period.taken),
        "left": _days(period.left),
        "left_tone": "inline-block min-w-10 rounded-full px-2 py-0.5 text-center font-semibold " + tone,
        "doubled_note": _DOUBLED_NOTE if period.doubled else "",
        "grants": [
            {
                "label": GrantKind(grant.kind).label,
                "days": f"{_days(grant.days)} хоног",
                "breakdown": grant.breakdown or "",
                "comment": grant.comment or "",
                "old_chip": bool(grant.from_old_system and grant.comment != _OLD_CHIP_COMMENT),
            }
            for grant in period.grants
        ],
        "leaves": [_line_out("Авсан", lv.start, lv.end, lv.days, lv.from_old_system) for lv in period.leaves],
    }


def _leave_out(facts: dict[str, Any], employee: Employee) -> dict[str, Any]:
    if not facts.get("leave_visible"):
        return {
            "visible": False,
            "configured": False,
            "start_missing": False,
            "periods": [],
            "old_count": 0,
            "fold_old": False,
            "fold_show_label": "",
            "fold_hide_label": "",
            "no_year_started": False,
            "nowhere": [],
            "old_absences": [],
            "can_record": False,
            "can_manage_settings": False,
            "settings_url": "",
            "all_leaves_url": "",
        }
    periods = [_period_out(p) for p in facts["leave_periods"]]
    start_missing = entitlement.employment_start(employee) is None
    old_count = sum(1 for p in periods if p["old"])
    fold_old = 0 < old_count < len(periods)
    configured = bool(facts["leave_configured"])
    return {
        "visible": True,
        "configured": configured,
        "start_missing": start_missing,
        "periods": periods,
        "old_count": old_count,
        "fold_old": fold_old,
        "fold_show_label": f"Өмнөх {old_count} жил харах ▾" if fold_old else "",
        "fold_hide_label": "Өмнөх жилүүдийг нуух ▴" if fold_old else "",
        "no_year_started": configured and not start_missing and not periods,
        "nowhere": [_line_out("Авсан", lv.start, lv.end, lv.days, lv.from_old_system) for lv in facts["leave_nowhere"]],
        "old_absences": [
            {
                "date": _iso(a.from_date) + (f" – {_iso(a.to_date)}" if a.to_date else ""),
                "name": a.absence_type.name,
                "note": a.note or "",
            }
            for a in facts["old_absences"]
        ],
        "can_record": bool(facts["can_record_leave"]),
        "can_manage_settings": bool(facts["can_manage_leave_settings"]),
        "settings_url": reverse("leave:settings"),
        "all_leaves_url": f"{reverse('leave:list')}?employee={employee.pk}&status=all",
    }


def _task_out(row: Any) -> dict[str, Any]:
    task = row.task
    done_label, done_rest = "", "—"
    if task.done_at is not None:
        done_by = task.done_by
        name = (done_by.get_full_name() or done_by.username) if done_by is not None else ""
        done_label = "Хийгдсэн"
        done_rest = f" · {name}, {timezone.localtime(task.done_at):%Y-%m-%d}"
    return {
        "title": task.title,
        "required": bool(task.required),
        "owner_label": row.owner_label,
        "due_on": _iso(task.due_on),
        "overdue": bool(row.overdue),
        "done": task.done_at is not None,
        "done_label": done_label,
        "done_rest": done_rest,
        "title_class": "text-slate-500" if task.done_at is not None else "",
        "due_class": "whitespace-nowrap font-medium text-red-700" if row.overdue else "whitespace-nowrap",
        "can_tick": bool(row.can_tick),
        "can_untick": bool(row.can_untick),
    }


def _panel_out(panel: dict[str, Any]) -> dict[str, Any]:
    checklist = panel["checklist"]
    return {
        "kind": panel["kind"],
        "heading": panel["heading"],
        "caption": (
            f"{checklist.template_name} · {panel['date_caption']} {_iso(checklist.anchor_day)}"
            if checklist is not None
            else ""
        ),
        "checklist": checklist is not None,
        "completed": checklist is not None and checklist.state == ChecklistState.COMPLETED,
        "progress": f"{panel['done']} / {panel['total']}" if checklist is not None else "",
        "today": _iso(panel.get("today")),
        "can_start": bool(panel["can_start"]),
        "can_cancel": bool(panel.get("can_cancel", False)),
        "rows": [_task_out(row) for row in panel.get("rows", [])],
    }


_BLANK_CHOICE = "---------"  # Django's empty option label in a select


def _aria(field: dict[str, Any], label: str) -> dict[str, Any]:
    """A soft box with its accessible name: the form field's label, which can differ from the row's text."""
    return {**field, "aria_label": label}


def _select_field(obj: Any) -> dict[str, Any]:
    """A foreign key's soft select: the stored pk, the current option's label, the read-only text."""
    label = _fk_text(obj)
    return {
        "kind": "select",
        "value": str(obj.pk) if obj is not None else "",
        "choice": label or _BLANK_CHOICE,
        "text": _default(label),
    }


def _quick_add(model: Any) -> dict[str, Any] | None:
    """The quick-add info of a model's list (the same {slug, modal, parent} that form widgets get from mark_addable),
    or None when the model has no quick-add list. The work tab has no form widget, so it reads the registry."""
    slug = QUICK_BY_MODEL.get(model)
    if slug is None:
        return None
    spec = QUICK[slug]
    return {"slug": slug, "modal": spec.modal, "parent": spec.parent or None}


def _fk_select(employee: Any, name: str) -> dict[str, Any]:
    """A foreign key's soft select on the Work tab. Django draws it as a combo text box (select.js) when its model has a
    quick-add list; the box shows the current option's text, and the blank option's label is empty."""
    field = employee._meta.get_field(name)
    label = _fk_text(getattr(employee, name))
    pk = getattr(employee, field.attname)
    add = _quick_add(field.related_model)
    return {
        "name": name,
        "kind": "select",
        "value": "" if pk is None else str(pk),
        "choice": label,
        "combo": add is not None,
        "text": _default(label),
        "add": add,
    }


def _choice_field(employee: Any, name: str, text: str) -> dict[str, Any]:
    """A soft select over a model's choices: the stored code and its label. `text` is the template's read-only text."""
    value = getattr(employee, name)
    if value is None or value == "":
        return {"name": name, "kind": "select", "value": "", "choice": "", "combo": False, "text": text}
    labels = dict(employee._meta.get_field(name).flatchoices)
    return {
        "name": name,
        "kind": "select",
        "value": str(value),
        "choice": str(labels.get(value, "")),
        "combo": False,
        "text": text,
    }


def _date_field(name: str, value: date | None) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "date",
        "value": _iso(value),
        "choice": "",
        "combo": False,
        "text": _iso(value) or "—",
    }


def _number_field(name: str, value: int | None) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "number",
        "value": "" if value is None else str(value),
        "choice": "",
        "combo": False,
        "text": "" if value is None else str(value),
    }


@employee_router.get("/{pk}/work", auth=django_auth, response=EmployeeWorkOut)
def employee_work(request: HttpRequest, response: HttpResponse, pk: int) -> dict[str, Any]:
    """The Work tab of one employee the signed-in user may see (404 otherwise): job, contract, MACS fields, the
    history, the waiting changes, the other orders, the leave block and the checklist panels."""
    user = _user(request)
    employee = access.visible_employees(user).filter(pk=pk).first()
    if employee is None:
        raise HttpError(404, _NOT_FOUND)
    today = timezone.localdate()
    facts = detail_facts(user, employee, today)
    can_manage = bool(facts["can_manage"])
    warning = request.session.pop(ORDER_WARNING_KEY, "")  # one-shot, as employees.views.detail_context
    if warning:
        response["Cache-Control"] = "no-store"
    job = facts["row"].job
    ext = ext_of(employee)
    transfer = "transfer" in facts["event_allowed"]
    contract_end_label = "—"
    if job is not None and job.contract_end:
        contract_end_label = _iso(job.contract_end)
    elif job is not None and job.contract_type == ContractType.OPEN_ENDED:
        contract_end_label = _OPEN_ENDED_LABEL
    return {
        "order_warning": str(warning or ""),
        "can_manage": can_manage,
        "transfer_chip": transfer,
        "position": _default(job.position if job is not None else None),
        "department": _default(job.department if job is not None else None),
        "manager": _default(job.manager.full_name if job is not None and job.manager is not None else None),
        "second_position": _aria(_fk_select(employee, "second_position"), "Албан тушаал (хавсарсан)"),
        "office": _aria(_fk_select(employee, "office"), "Алба"),
        "section": _aria(_fk_select(employee, "section"), "Хэсэг"),
        "branch": _aria(_fk_select(employee, "branch"), "Салбар"),
        "employee_type": _default(job.get_employee_type_display() if job is not None and job.employee_type else None),
        "contract_type": _default(job.get_contract_type_display() if job is not None else None),
        "contract_no": job.contract_no if job is not None else "",
        "contract_chip": "contract" in facts["event_allowed"],
        "contract_start": _iso(job.contract_start if job is not None else None) or "—",
        "contract_end": _iso(job.contract_end if job is not None else None),
        "contract_end_label": contract_end_label,
        "probation_end": _aria(
            _date_field("probation_end", ext.probation_end if ext is not None else None), "Туршилтын хугацаа дуусах"
        ),
        "first_hire_date": _aria(_date_field("first_hire_date", employee.first_hire_date), "Анх ажилд орсон огноо")
        if can_manage
        else None,
        "job_type": _aria(
            _choice_field(employee, "job_type", _default(employee.get_job_type_display())), "Ажлын төрөл"
        ),
        "job_figure": _aria(
            _choice_field(employee, "job_figure", _default(employee.get_job_figure_display())), "Ажлын хэлбэр"
        ),
        # Django prints «None» here too
        "work_conditions": _aria(
            _choice_field(employee, "work_conditions", str(employee.get_work_conditions_display())), "Ажлын нөхцөл"
        ),
        "work_schedule": _aria(_fk_select(employee, "work_schedule"), "Ажлын цагийн хуваарь"),
        "sector_years": _aria(_number_field("sector_years", employee.sector_years), "Салбарт ажилласан жил"),
        "macs_contract_no": _default(employee.contract_no),
        "macs_contract_period": f"{_iso(employee.contract_start) or '—'} – {_iso(employee.contract_end)}",
        "macs_taken_leave": "Тийм" if employee.taken_leave == 1 else ("Үгүй" if employee.taken_leave == 0 else "—"),
        "macs_leave_type": _default(employee.get_leave_type_display() if employee.leave_type else None),
        "macs_probation_months": _default(employee.probation_months),
        "macs_last_order_no": _default(employee.last_order_no),
        "macs_last_order_text": _default(employee.last_order_text),
        "waiting": [_waiting_out(w) for w in facts["waiting"]],
        "jobs": [_job_out(j, can_manage) for j in facts["jobs"]],
        "orders_count": len(facts["orders"]),
        "orders": [_other_order_out(r, employee.pk, can_manage) for r in facts["orders"]],
        "leave": _leave_out(facts, employee),
        "checklist_visible": bool(facts["checklist_visible"]),
        "checklists": [_panel_out(p) for p in facts["checklist_panels"]],
    }


_FORBIDDEN = "Хандах эрх байхгүй."
_NO_SALARY = "тогтоогоогүй"
_SET_SALARY_LABEL = "Цалин тогтоох"
_CANCEL_CLASS = "rounded px-2 py-1 text-red-600 hover:bg-red-50"  # the «Цуцлах» button of _tab_salary.html
_CORRECT_CLASS = "text-violet-700 hover:underline"  # the «Засвар» link of _tab_salary.html


def _salary_period_text(row: Any) -> str:
    """Salary.html's period: «from –», then « to» when closed, « одоо» when open and not yet scheduled."""
    text = f"{_iso(row.period.lower)} –"
    if row.period.upper:
        text += f" {_iso(row.period.upper)}"
    elif not row.scheduled:
        text += " одоо"
    return text


def _salary_row_out(row: Any, can_manage: bool) -> dict[str, Any]:
    cancellable = bool(row.cancellable)
    correctable = not cancellable and can_manage and not bool(row.locked)  # the template's elif branch
    action_label = "Цуцлах" if cancellable else ("Засвар" if correctable else "")
    action_class = _CANCEL_CLASS if cancellable else (_CORRECT_CLASS if correctable else "")
    scheduled = bool(row.scheduled)
    return {
        "pk": row.pk,
        "event_id": row.event_id,
        "period_text": _salary_period_text(row),
        "amount": mnt(row.base_salary),
        "label": row.label,
        "scheduled": scheduled,
        "scheduled_label": "Төлөвлөсөн" if scheduled else "",
        "cancellable": cancellable,
        "correctable": correctable,
        "action_label": action_label,
        "action_class": action_class,
    }


def _text_bank_field(name: str, label: str, aria: str, raw: Any) -> dict[str, Any]:
    """A plain text soft box (a text input), its form name, accessible name and its read-only text («—» when empty)."""
    value = str(raw) if raw else ""
    return {
        "name": name,
        "label": label,
        "aria_label": aria,
        "kind": "text",
        "value": value,
        "choice": "",
        "text": _default(raw),
        "checked": False,
    }


def _bank_fields(employee: Employee) -> list[dict[str, Any]]:
    """The «Банк, даатгал» block in template order: each box's kind, raw value, option label and read-only text.
    `label` is the row's text; `aria_label` is the form field's name (Django's accessible name)."""
    disability = bool(employee.has_disability)
    bank = _aria(_select_field(employee.bank), "Банк")
    insured = _aria(_select_field(employee.insured_category), "Даатгуулагчийн төрөл")
    return [
        {
            "name": "si-bank",
            "label": "Банк",
            **bank,
            "checked": False,
            "add": _quick_add(Employee._meta.get_field("bank").related_model),
        },
        _text_bank_field("si-account_no", "Дансны дугаар", "Дансны дугаар", employee.account_no),
        _text_bank_field("si-social_insurance_no", "НДД", "НДД-ийн дугаар", employee.social_insurance_no),
        _text_bank_field("si-health_insurance_no", "ЭМДД", "ЭМДД-ийн дугаар", employee.health_insurance_no),
        {
            "name": "si-insured_category",
            "label": "Даатгуулагчийн төрөл",
            **insured,
            "checked": False,
            "add": _quick_add(Employee._meta.get_field("insured_category").related_model),
        },
        _text_bank_field("si-taxpayer_no", "ТТД", "Татвар төлөгчийн дугаар", employee.taxpayer_no),
        {
            "name": "si-has_disability",
            "label": "Хөгжлийн бэрхшээл",
            "aria_label": "Хөгжлийн бэрхшээлтэй",
            "kind": "checkbox",
            "value": "",
            "choice": "",
            "text": "Тийм" if disability else "Үгүй",
            "checked": disability,
        },
    ]


@employee_router.get("/{pk}/salary", auth=django_auth, response=EmployeeSalaryOut)
def employee_salary(request: HttpRequest, pk: int) -> dict[str, Any]:
    """The Salary tab of one employee the signed-in user may see (404 otherwise; 403 without the salary right):
    today's pay, the pay history rows and the «Банк, даатгал» block."""
    user = _user(request)
    employee = access.visible_employees(user).filter(pk=pk).first()
    if employee is None:
        raise HttpError(404, _NOT_FOUND)
    if not access.can_view_salary(user):
        raise HttpError(403, _FORBIDDEN)
    facts = detail_facts(user, employee, timezone.localdate())
    salary = facts["salary"]
    current = mnt(salary.base_salary) if salary is not None and salary.base_salary else None
    can_manage = bool(facts["can_manage_salary"])
    rows = [_salary_row_out(row, can_manage) for row in facts["salaries"]]
    can_set = can_manage and not rows
    return {
        "current": current,
        "missing_label": "" if current is not None else _NO_SALARY,
        "rows": rows,
        "has_rows": bool(rows),
        "can_set": can_set,
        "set_label": _SET_SALARY_LABEL if can_set else "",
        "editable": can_manage,
        "bank_fields": _bank_fields(employee),
    }


class EmployeePersonalChipOut(Schema):
    key: str
    label: str
    count_text: str  # the grey number, e.g. «2» or «3/12»
    visible: bool  # the chip shows only when the count is not zero (and «Бусад мэдээлэл» once a field is filled)
    tone: str  # the chip's class string (_personal_group_chip.html)


class EmployeePersonalGroupOut(Schema):
    key: str  # basic | edu | award | health | other
    title: str
    open_by_default: bool  # «Үндсэн мэдээлэл» is open; the other groups open by hand
    chips: list[EmployeePersonalChipOut]


class EmployeePersonalRowOut(Schema):
    label: str
    display: str  # the value, or «—» when empty
    empty: bool  # the «—» is muted (text-slate-300)


class EmployeePersonalChoiceOut(Schema):
    value: str
    label: str


class EmployeePersonalFieldOut(Schema):
    name: str
    label: str
    required: bool  # the label gets «*»
    kind: Literal["text", "textarea", "number", "date", "select", "checkbox"]
    value: str  # the box's text as posted ("" when empty; the chosen value for a select)
    checked: bool  # the checkbox state (kind == checkbox)
    placeholder: str  # a text box's «—» (or its placeholder), a select's data-placeholder, "" for a checkbox
    choice: str  # a select's current option label ("" when none, as the blank entry shows); "" for the other kinds
    combo: bool  # select.js turns it into a combo text box: a quick-add list, data-search on, or 8+ options (not off)
    choices: list[EmployeePersonalChoiceOut]  # a select's options, the blank entry first
    add: FieldAddOut | None = None  # the quick-add info; null when the field is not addable


class EmployeePersonalSectionOut(Schema):
    name: str  # identity | contact | education | other
    title: str
    group: str  # the topic group the section sits in (basic | edu | award | health | other)
    editable: bool  # the fields show as soft boxes (readOnly until step 3b); otherwise the read rows show
    rows: list[EmployeePersonalRowOut]  # read mode
    fields: list[EmployeePersonalFieldOut]  # the soft boxes, only when editable
    loaded: str  # the stale-check snapshot (JSON) of the personal form, posted back on save; "" when not editable


class EmployeePersonalColumnOut(Schema):
    header: str
    field: str  # the form field this column's box edits (InlineColumn.field); "" for pop-up lists
    head_class: str  # the <th> class string, "" when none
    cell_class: str  # the <td> class string, "" when none


class EmployeePersonalListRowOut(Schema):
    key: str  # the row's id (the pop-up or the inline row's URL key)
    cells: list[str]  # one display text per column, «—» when empty


class EmployeePersonalListOut(Schema):
    kind: str
    title: str
    group: str  # the topic group the list sits in (basic | edu | award | health | other)
    parent: str | None  # the section key the list sits in (the two contact lists: «contact»), else None
    inline: bool  # edited in its own rows (_inline_list.html) rather than a pop-up
    editable: bool  # the «+ нэмэх» button and the row clicks show (can_manage)
    count: int
    empty_label: str  # «бүртгэгдээгүй» when the list has no rows, "" otherwise
    columns: list[EmployeePersonalColumnOut]
    rows: list[EmployeePersonalListRowOut]


class EmployeePersonalOut(Schema):
    editable: bool  # can_manage: the field sections and the lists are editable (until step 3b)
    groups: list[EmployeePersonalGroupOut]
    counts: dict[str, str]  # _section_counts as display text, keyed as the chips' count keys
    sections: list[EmployeePersonalSectionOut]
    lists: list[EmployeePersonalListOut]


# The personal tab's topic groups and their chips, copied from _tab_personal.html and _personal_group_summary.html:
# (group key, title, open by default, ((chip key, label, count key, filled only), ...)).
_PERSONAL_GROUPS: tuple[tuple[str, str, bool, tuple[tuple[str, str, str, bool], ...]], ...] = (
    (
        "basic",
        "Үндсэн мэдээлэл",
        True,
        (
            ("contact", "Холбоо барих, хаяг", "address", False),
            ("family", "Гэр бүл", "family", False),
            ("relative", "Хамаатан садан", "relative", False),
        ),
    ),
    (
        "edu",
        "Боловсрол, туршлага",
        False,
        (
            ("education", "Боловсрол", "education", False),
            ("before_work", "Ажлын туршлага", "before_work", False),
            ("certificate", "Мэргэшил, сертификат", "certificate", False),
            ("training", "Сургалт", "training", False),
            ("language", "Гадаад хэл", "language", False),
            ("talent", "Авьяас", "talent", False),
            ("skill", "Ур чадварын даалгавар", "skill", False),
        ),
    ),
    (
        "award",
        "Шагнал, сахилга",
        False,
        (
            ("award", "Шагнал урамшил", "award", False),
            ("discipline", "Сахилгын шийтгэл", "discipline", False),
            ("complaint", "Үйлчлүүлэгчийн гомдол", "complaint", False),
            ("gift", "Олгосон бэлэг", "gift", False),
            ("material_help", "Буцалтгүй тусламж", "material_help", False),
        ),
    ),
    (
        "health",
        "Эрүүл мэнд, цэрэг",
        False,
        (
            ("body", "Эрүүл мэндийн үзлэг", "body", False),
            ("driver", "Жолоо", "driver", False),
            ("military", "Цэргийн алба", "military", False),
            ("army_rank", "Цэргийн цол", "army_rank", False),
        ),
    ),
    ("other", "Бусад", False, (("other", "Бусад мэдээлэл", "other", True),)),
)
# The group of each section, and of each list (by its chip's count key). The contact lists sit in the «contact» section.
_SECTION_GROUP = {"identity": "basic", "contact": "basic", "education": "edu", "other": "other"}
_KIND_GROUP: dict[str, str] = {count: key for key, _, _, chips in _PERSONAL_GROUPS for _, _, count, _ in chips}
_KIND_GROUP["contact"] = "basic"  # the emergency-contact list (its chip is absent)
_KIND_PARENT = {"address": "contact", "contact": "contact", "education": "education"}
_CHIP_TONE = (
    "inline-flex items-center gap-1 rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700 tabular-nums "
    "has-[.invisible]:hidden"
)
# The personal tab's lists in template order. The inline ones come from sections.INLINE_LISTS; these are the table ones:
# (title, ((header, th class, td class), ...)), copied from each _section_<kind>.html.
_TABLE_LISTS: dict[str, tuple[str, tuple[tuple[str, str, str], ...]]] = {
    "relative": (
        "Хамаатан садан",
        (
            ("Нэр", "", ""),
            ("Эцэг/эхийн нэр", "", ""),
            ("Ажилтны хэн болох", "", ""),
            ("Утас", "", ""),
            ("Ажилладаг салбар", "", ""),
            ("Хэлтэс", "", ""),
            ("Албан тушаал", "", ""),
        ),
    ),
    "before_work": (
        "Ажлын туршлага",
        (("Газар", "", ""), ("Мэргэжил", "", ""), ("Хугацаа", "", ""), ("Гарсан шалтгаан", "", "")),
    ),
    "certificate": (
        "Мэргэшил, сертификат",
        (
            ("Төрөл", "", ""),
            ("Байгууллага", "", ""),
            ("Мэргэжил", "", ""),
            ("Сертификат №", "", ""),
            ("Огноо", "", ""),
            ("Он", "", ""),
        ),
    ),
    "education": (
        "Сурсан сургууль",
        (
            ("Сургууль", "", ""),
            ("Улс", "", ""),
            ("Он", "", "whitespace-nowrap"),
            ("Боловсрол", "", ""),
            ("Мэргэжил", "", ""),
            ("Мэргэшил", "", ""),
            ("Зэрэг", "", ""),
            ("Голч", "text-right", "text-right"),
            ("Диплом №", "pl-6", "pl-6"),
        ),
    ),
    "training": (
        "Сургалт",
        (
            ("Он", "", ""),
            ("Сургалт", "", ""),
            ("Төв", "", ""),
            ("Хэлбэр", "", ""),
            ("Хоног", "", ""),
            ("Төлбөр", "text-right", "text-right"),
            ("Төлсөн", "pl-6", "pl-6"),
        ),
    ),
    "gift": (
        "Олгосон бэлэг",
        (
            ("Огноо", "", ""),
            ("Бэлгийн төрөл", "", ""),
            ("Бэлэглэсэн он", "", ""),
            ("Хүүхдийн тоо", "", ""),
            ("Хүүхдийн нас", "", ""),
            ("Үнэ", "text-right", "text-right"),
            ("Өгсөн эсэх", "pl-6", "pl-6"),
            ("Тайлбар", "", ""),
        ),
    ),
    "body": (
        "Эрүүл мэндийн үзлэг",
        (
            ("Үзлэгийн огноо", "", ""),
            ("Үзлэгийн төрөл", "", ""),
            ("Дуусах хугацаа", "", ""),
            ("Дүгнэлт", "pl-6", "pl-6"),
        ),
    ),
    "address": ("Хаяг", (("Аймаг, хот", "", ""), ("Сум, дүүрэг", "", ""), ("Хаяг", "", ""))),
}
_TAB_LIST_ORDER = (
    "address",
    "contact",
    "family",
    "relative",
    "education",
    "before_work",
    "certificate",
    "training",
    "language",
    "talent",
    "skill",
    "award",
    "discipline",
    "complaint",
    "gift",
    "material_help",
    "body",
    "driver",
    "military",
    "army_rank",
)
_NO_ROWS = "бүртгэгдээгүй"


def _plain(value: Any) -> str:
    """A value as Django's `{{ value }}` writes it: None shows as «None» (no default filter)."""
    return "None" if value is None else str(value)


def _if_none(value: Any, fallback: str = "—") -> str:
    """Django's `|default_if_none:"—"`: only None takes the fallback."""
    return fallback if value is None else str(value)


def _date_text(value: Any) -> str:
    """Django's `|date:"Y-m-d"`: a date as ISO, anything else as "" (the default filter then shows its fallback)."""
    return value.isoformat() if isinstance(value, date) else ""


def _table_cells(kind: str, row: Any) -> list[str]:
    """The cells of one table list row, as the kind's _section_<kind>.html template shows them."""
    v = row.values
    if kind == "relative":
        return [
            _default(v.get("given_name")),
            _default(v.get("father_name")),
            _default(v.get("description")),
            _default(v.get("phone")),
            _plain(v.get("branch")),
            _plain(v.get("department")),
            _plain(v.get("position")),
        ]
    if kind == "before_work":
        if v.get("start_text") or v.get("end_text"):  # the old program's month text, when there is one
            period = f"{_default(v.get('start_text'), '…')} – {_default(v.get('end_text'), '…')}"
        else:
            period = f"{_default(v.get('start_year'), '…')} – {_default(v.get('end_year'), '…')}"
        return [
            _default(v.get("worked_place")),
            _default(v.get("profession")),
            period,
            _default(v.get("shaltgaan")),
        ]
    if kind == "certificate":
        return [
            _default(v.get("cert_type")),
            _plain(v.get("org_edu")),
            _default(v.get("profession")),
            _default(v.get("certify_number")),
            _default(_date_text(v.get("certify_date"))),
            _plain(v.get("certify_year")),
        ]
    if kind == "education":
        return [
            _plain(v.get("org_name")),
            _plain(v.get("country_name")),
            f"{_plain(v.get('start_year'))}–{_plain(v.get('end_year'))}",
            _default(v.get("edu_level")),
            _default(v.get("profession_type")),
            _default(v.get("qualification_type")),
            _default(v.get("grade")),
            _if_none(v.get("credit_score")),
            _default(v.get("diplom_number")),
        ]
    if kind == "training":
        return [
            _plain(v.get("start_year")),
            _plain(v.get("description")),
            _default(v.get("training_center")),
            _plain(v.get("tr_type_label")),
            _if_none(v.get("days")),
            mnt(v.get("amount")),
            _plain(v.get("pay_type_label")),
        ]
    if kind == "gift":
        return [
            _default(_date_text(v.get("pdate"))),
            _plain(v.get("present_type")),
            _plain(v.get("given_year")),
            _plain(v.get("childqty")),
            _plain(v.get("child_age")),
            mnt(v.get("price")),
            "Тийм" if v.get("given") == 1 else "Үгүй",
            _default(row.ext.get("note")),
        ]
    if kind == "body":
        return [
            _default(_date_text(v.get("inserted_ognoo"))),
            _default(v.get("term_type")),
            _default(_date_text(v.get("end_date"))),
            _default(v.get("conclusion")),
        ]
    # address
    return [_plain(v.get("city")), _plain(v.get("district")), _default(v.get("street"))]


def _personal_list_out(employee: Employee, kind: str, rows: list[Any], can_manage: bool) -> dict[str, Any]:
    if kind in sections.INLINE_LISTS:
        spec = sections.INLINE_LISTS[kind]
        items = sections.inline_context(employee, kind, rows, can_manage)["items"]
        columns = [
            {"header": col.header, "field": col.field, "head_class": "", "cell_class": ""} for col in spec.columns
        ]
        out_rows = [{"key": str(item["key"]), "cells": [_default(cell) for cell in item["cells"]]} for item in items]
        title, inline = spec.title, True
    else:
        title, cols = _TABLE_LISTS[kind]
        columns = [{"header": h, "field": "", "head_class": hc, "cell_class": cc} for h, hc, cc in cols]
        out_rows = [{"key": str(r.key), "cells": _table_cells(kind, r)} for r in rows]
        inline = False
    return {
        "kind": kind,
        "title": title,
        "group": _KIND_GROUP[kind],
        "parent": _KIND_PARENT.get(kind),
        "inline": inline,
        "editable": can_manage,
        "count": len(rows),
        "empty_label": "" if rows else _NO_ROWS,
        "columns": columns,
        "rows": out_rows,
    }


def _chip_out(key: str, label: str, count: Any, filled_only: bool) -> dict[str, Any]:
    """A group chip: shown while its count is not zero; «Бусад мэдээлэл» («filled/total») only once a field is set."""
    text = str(count)
    shown = bool(count) and not (filled_only and text[:2] == "0/")
    return {"key": key, "label": label, "count_text": text, "visible": shown, "tone": _CHIP_TONE}


def _personal_section_out(name: str, ctx: dict[str, Any], can_manage: bool) -> dict[str, Any]:
    return {
        "name": name,
        "title": str(ctx["title"]),
        "group": _SECTION_GROUP[name],
        "editable": can_manage,
        "rows": [
            {"label": label, "display": str(value) if value else "—", "empty": not value}
            for label, value in ctx["rows"]
        ],
        "fields": [describe_field(bound) for bound in ctx["fields"]] if can_manage else [],
        "loaded": stale.snapshot(ctx["form"]) if can_manage else "",
    }


@employee_router.get("/{pk}/personal", auth=django_auth, response=EmployeePersonalOut)
def employee_personal(request: HttpRequest, pk: int) -> dict[str, Any]:
    """The personal tab of one employee the signed-in user may see (404 otherwise; 403 without the personal right):
    the topic groups with their chips, the four field sections, and the personal lists."""
    user = _user(request)
    employee = access.visible_employees(user).filter(pk=pk).first()
    if employee is None:
        raise HttpError(404, _NOT_FOUND)
    if not access.can_view_personal(user, employee):
        raise HttpError(403, _FORBIDDEN)
    facts = detail_facts(user, employee, timezone.localdate())
    can_manage = bool(facts["can_manage"])
    counts: dict[str, Any] = facts["section_counts"]
    personal: dict[str, list[Any]] = facts["personal"]
    field_sections: dict[str, dict[str, Any]] = facts["personal_sections"]
    return {
        "editable": can_manage,
        "groups": [
            {
                "key": key,
                "title": title,
                "open_by_default": open_default,
                "chips": [
                    _chip_out(ck, label, counts.get(count_key, 0), filled) for ck, label, count_key, filled in chips
                ],
            }
            for key, title, open_default, chips in _PERSONAL_GROUPS
        ],
        "counts": {key: str(value) for key, value in counts.items()},
        "sections": [_personal_section_out(name, field_sections[name], can_manage) for name in sections.SECTIONS],
        "lists": [_personal_list_out(employee, kind, personal.get(kind, []), can_manage) for kind in _TAB_LIST_ORDER],
    }


class EmployeeActivityChangeOut(Schema):
    field: str
    old: str  # "" when none: the struck-through text before the arrow
    new: str  # «(хоосон)» when empty


class EmployeeActivityEntryOut(Schema):
    day: str  # YYYY-MM-DD, the entry's local day
    starts_day: bool  # a new day group opens here (the template's ifchanged); the batch's first entry always does
    day_heading: str  # «Өнөөдөр», «Өчигдөр» or YYYY-MM-DD; "" when no heading shows
    time: str  # HH:MM
    by: str  # the person's name, or «Систем»
    kind: str  # the raw kind: created, changed, note, ...
    kind_label: str  # the kind's Mongolian name (the badge text)
    dot_class: str  # the timeline dot's full class string
    badge_class: str  # the kind badge's full class string
    is_note: bool  # a note: the message is a sky box
    message: str
    message_class: str  # the message paragraph's full class string
    changes: list[EmployeeActivityChangeOut]


class EmployeeActivityOut(Schema):
    entries: list[EmployeeActivityEntryOut]  # one batch, newest first
    prev_day: str  # YYYY-MM-DD of the entry just above this batch (its heading is not repeated); "" when none
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    empty_label: str  # «Бүртгэл алга» when there are no entries at all, "" otherwise
    log_url: str  # the «Бүрэн харах» link: the employee log with this person preset; "" without macs.view_employees


# The timeline dot and the kind badge, by kind (the template's if-chain in _activity_entries.html, copied verbatim).
_ACTIVITY_DOT = "absolute top-1.5 -left-[5px] h-2.5 w-2.5 rounded-full border-2 border-surface "
_ACTIVITY_BADGE = "shrink-0 rounded px-1.5 py-0.5 text-xs "
_ACTIVITY_TONE = {
    "correction": ("bg-amber-500", "bg-amber-50 text-amber-700"),
    "history": ("bg-violet-500", "bg-violet-50 text-violet-700"),
    "note": ("bg-sky-500", "bg-sky-50 text-sky-700"),
    "created": ("bg-emerald-500", "bg-emerald-50 text-emerald-700"),
    "added": ("bg-emerald-500", "bg-emerald-50 text-emerald-700"),
    "deleted": ("bg-red-400", "bg-red-50 text-red-700"),
    "cancelled": ("bg-red-400", "bg-red-50 text-red-700"),
}
_ACTIVITY_TONE_DEFAULT = ("bg-slate-400", "bg-slate-100 text-slate-600")
_ACTIVITY_EMPTY = "Бүртгэл алга"
_NO_CHANGE_TEXT = "(хоосон)"


def _local_day(value: Any) -> str:
    return timezone.localtime(value).strftime("%Y-%m-%d")


def _activity_change_out(change: dict[str, Any]) -> dict[str, str]:
    """One «field: old → new» line: the old value only when there is one, «(хоосон)» for an empty new value."""
    old = _plain(change.get("old")) if change.get("old") else ""
    new = _plain(change.get("new")) if change.get("new") else _NO_CHANGE_TEXT
    return {"field": _plain(change.get("field")), "old": old, "new": new}


def _activity_entry_out(entry: ActivityEntry, starts_day: bool, day_heading: str) -> dict[str, Any]:
    kind = entry.kind
    dot, badge = _ACTIVITY_TONE.get(kind, _ACTIVITY_TONE_DEFAULT)
    is_note = kind == "note"
    if is_note:
        message_class = "mt-1 rounded-lg bg-sky-50 px-3 py-2 whitespace-pre-line"
    elif kind == "correction":
        message_class = "mt-0.5 text-amber-700"
    else:
        message_class = "mt-0.5 text-slate-700"
    if entry.by is not None:
        by = entry.by.get_full_name() or entry.by.username
    else:
        by = "Систем"
    return {
        "day": _local_day(entry.at),
        "starts_day": starts_day,
        "day_heading": day_heading,
        "time": timezone.localtime(entry.at).strftime("%H:%M"),
        "by": by,
        "kind": kind,
        "kind_label": entry.get_kind_display(),
        "dot_class": _ACTIVITY_DOT + dot,
        "badge_class": _ACTIVITY_BADGE + badge,
        "is_note": is_note,
        "message": entry.message,
        "message_class": message_class,
        "changes": [_activity_change_out(c) for c in (entry.changes or [])],
    }


@employee_router.get("/{pk}/activity", auth=django_auth, response=EmployeeActivityOut)
def employee_activity(request: HttpRequest, response: HttpResponse, pk: int, offset: str = "") -> dict[str, Any]:
    """One batch of the «Түүх» drawer for an employee the signed-in user may see (404 otherwise), as activity_more:
    50 entries from `offset` (a junk offset is 0), the day heading of the entry above, and the next offset."""
    user = _user(request)
    employee = access.visible_employees(user).filter(pk=pk).first()
    if employee is None:
        raise HttpError(404, _NOT_FOUND)
    # Only a plain run of up to 9 digits is an offset; anything longer (or not digits) is 0, so no DB overflow.
    start = int(offset) if offset.isascii() and offset.isdigit() and len(offset) <= 9 else 0
    today = timezone.localdate()
    entries = access.visible_activity(user, employee).select_related("by")
    total = entries.count()
    shown = list(entries[start : start + ACTIVITY_BATCH])
    before = entries[start - 1] if 0 < start <= total else None
    prev_day = _local_day(before.at) if before is not None else ""
    out: list[dict[str, Any]] = []
    last_day = None
    for index, entry in enumerate(shown):
        day = _local_day(entry.at)
        starts_day = index == 0 or day != last_day
        heading = ""
        if starts_day and not (index == 0 and day == prev_day):  # the first entry repeats the day above: no heading
            heading = day_label(entry.at, today)
        out.append(_activity_entry_out(entry, starts_day, heading))
        last_day = day
    response["Cache-Control"] = "no-store"
    return {
        "entries": out,
        "prev_day": prev_day,
        "next_offset": start + ACTIVITY_BATCH if total > start + ACTIVITY_BATCH else None,
        "empty_label": "" if out else _ACTIVITY_EMPTY,
        "log_url": f"{reverse('logs:employee')}?employee={employee.pk}" if user.has_perm("macs.view_employees") else "",
    }
