import io
import logging
import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from accounts.models import User
from config.params import id_param as _id_param
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DataError, IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.vary import vary_on_headers
from leave import access as leave_access
from leave.services import ledger as leave_ledger
from macs.models import Absence, Command
from reports.registry import can_open
from reports.staff_list import REPORT as STAFF_LIST

from employees import access, attention, palette, sections, stale
from employees import today as facts
from employees.forms import (
    BIRTH_FIELDS,
    FORMS,
    AddressRowForm,
    CancelEventForm,
    CreateLoginForm,
    EmployeeForm,
    EventForm,
    HireAddressForm,
    HireContactForm,
    HireExtrasForm,
    HireJobForm,
    HirePersonForm,
    JobCorrectionForm,
    OrderFieldsForm,
    OrderUploadForm,
    PersonalRowForm,
    SalaryCorrectionForm,
    SalaryInsuranceForm,
    SetSalaryForm,
)
from employees.listing import STATE_LABELS, Row, current_salary, employee_rows, row_for
from employees.models import (
    EXT_FIELDS,
    PERSONAL_FIELDS,
    ActivityEntry,
    ChangeType,
    CompanySettings,
    Department,
    Employee,
    EmployeeType,
    Event,
    EventType,
    HrOrder,
    JobRecord,
    OrderState,
    OrderType,
    ext_of,
)
from employees.services import (
    events,
    history,
    logins,
    macs_writes,
    order_docs,
    order_register,
    orders,
    personal_rows,
    records,
    setup,
)
from employees.services import personal_writes as pw
from employees.services.events import ALLOWED_FIELDS, SALARY_TYPES, EventError
from employees.services.history import HistoryError, salary_on
from employees.services.orders import OrderError
from employees.validators import normalize_register_no

logger = logging.getLogger(__name__)
NO_DEPARTMENT = "Хэлтэсгүй"


def _group_by_department(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    buckets: dict[str, list[Row]] = {}
    for row in rows:
        name = (row.job.department.name or "") if row.job else NO_DEPARTMENT
        buckets.setdefault(name, []).append(row)
    return sorted(buckets.items(), key=lambda item: (item[0] == NO_DEPARTMENT, item[0]))


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


@login_required
@vary_on_headers("HX-Request")
def employee_list(request: HttpRequest) -> HttpResponse:
    qs = access.visible_employees(_user(request)).filter(ext__isnull=False)  # only people HR has touched
    q = request.GET.get("q", "").strip()
    if q:
        match = Q(family_name__icontains=q) | Q(given_name__icontains=q) | Q(code__icontains=q)
        match |= Q(work_phone__icontains=q)
        if _user(request).has_perm("macs.view_personal"):  # the register number is personal data
            match |= Q(register_no__icontains=q)
        qs = qs.filter(match)
    today = timezone.localdate()
    rows = employee_rows(qs, today)
    state = request.GET.get("state", "")
    rows = [r for r in rows if r.state == state] if state else [r for r in rows if r.state != "left"]
    dept = request.GET.get("department", "")
    if dept:
        rows = [r for r in rows if r.job and str(r.job.department_id) == dept]
    etype = request.GET.get("type", "")
    if etype:
        rows = [r for r in rows if r.job and r.job.employee_type == etype]
    view = "table" if request.GET.get("view") == "table" else "grid"  # pictures by default
    group = request.GET.get("group") == "1"
    groups = _group_by_department(rows) if group and rows else None
    context: dict[str, Any] = {
        "rows": rows,
        "groups": groups,
        "group": group,
        "view": view,
        "q": q,
        "state": state,
        "department": dept,
        "emp_type": etype,
        "states": STATE_LABELS,
        "departments": Department.objects.exclude(ext__active=False),
        "types": EmployeeType.choices,
        "can_manage": access.can_manage(_user(request)),
        "can_open_staff_report": can_open(_user(request), STAFF_LIST),
    }
    is_partial = bool(request.headers.get("HX-Request")) and not request.headers.get("HX-History-Restore-Request")
    template = "employees/_results.html" if is_partial else "employees/list.html"
    return render(request, template, context)


@login_required
def today_page(request: HttpRequest) -> HttpResponse:
    """Home page: what needs HR's eye today (attention list, who is away, upcoming dates)."""
    user, today = _user(request), timezone.localdate()
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    context: dict[str, Any] = {
        "today": today,
        "headcount": facts.headcount(rows),
        "away": facts.away_on(user, rows, today),
        "pending_orders": facts.pending_orders(user, rows),
        "upcoming": facts.upcoming(user, rows, today),
        "timeline": facts.away_timeline(user, rows, today),
        "can_open_leave": leave_access.can_record(user),
        "attention_open": True,
    }
    context.update(_attention_context(user, attention.items(user, rows, today)))
    context["attention_count"] = len(context["attention"])
    return render(request, "employees/today.html", context)


@login_required
@require_POST
def attention_toggle(request: HttpRequest) -> HttpResponse:
    """ "Мэдлээ" / "Дахин харуулах" on one Анхаарах item; returns the box."""
    user, today = _user(request), timezone.localdate()
    found = attention.items(user, employee_rows(access.visible_employees(user), today), today)
    keys = set(request.POST.getlist("key"))
    picked = [a for a in found if a.key in keys]
    if not picked:
        raise Http404
    for item in picked:
        if request.POST.get("action") == "restore":
            attention.restore(user, item)
        else:  # "dismiss" (one item) or "dismiss_all" (a whole group)
            attention.dismiss(user, item)
    return render(request, "employees/_attention.html", _attention_context(user, found))


def _attention_context(user: User, found: list[attention.Attention]) -> dict[str, object]:
    shown, hidden = attention.split(user, found)
    return {"attention": shown, "attention_groups": attention.group(shown), "attention_hidden": hidden}


def _needs_setup(employee: Employee) -> bool:
    ext = ext_of(employee)
    return ext is not None and ext.setup_required


def _employee_for(request: HttpRequest, pk: int) -> Employee:
    return get_object_or_404(access.visible_employees(_user(request)), pk=pk)


def _employee_form(request: HttpRequest, employee: Employee, data: Any = None, files: Any = None) -> EmployeeForm:
    form = EmployeeForm(data, files, employee=employee)
    if not access.can_view_personal(_user(request), employee):  # those inputs are not on the page
        for name in PERSONAL_FIELDS:
            form.fields.pop(name, None)
    return form


def _salary_form(employee: Employee) -> SalaryInsuranceForm:
    return SalaryInsuranceForm(prefix="si", employee=employee)


def _is_scheduled(event: Event | None, today: date) -> bool:
    """A change that can still be cancelled: scheduled, or waiting for its signed order (any date)."""
    return event is not None and event.status(today) in ("scheduled", "awaiting_signature")


def _mark_scheduled(rows: Any, user: User, today: date) -> list[Any]:
    """Flag history rows of a not-yet-effective event, and whether this user may cancel it."""
    result = list(rows)
    for row in result:
        row.scheduled = row.period.lower > today
        row.locked = _is_scheduled(row.event, today)
        row.cancellable = row.locked and access.can_cancel(user, row.event)
        row.label = row.event.get_type_display() if row.event is not None else row.get_change_type_display()
    return result


def _next_event(employee: Employee, can_salary: bool, today: date) -> Event | None:
    """The next change still to come: applied ones and waiting ones (awaiting their signed order) dated after today."""
    qs = employee.events.filter(cancelled_at__isnull=True, effective__gt=today)
    if not can_salary:  # a scheduled pay change must not leak to people who cannot see pay
        qs = qs.exclude(type=EventType.SALARY_CHANGE)
    return qs.order_by("effective").first()


def _awaiting_rows(employee: Employee, user: User, can_salary: bool) -> list[Any]:
    """The Work tab's «Гарын үсэг хүлээж буй өөрчлөлт» block: changes waiting for their signed order, newest first.
    Each row has `label`, `event`, its `order` (or None) and `cancellable` (the user may cancel it)."""
    qs = employee.events.filter(applied_at__isnull=True, cancelled_at__isnull=True).order_by("-created_at", "-pk")
    if not can_salary:  # a waiting pay change must not leak to people who cannot see pay
        qs = qs.exclude(type=EventType.SALARY_CHANGE)
    events_list = list(qs)
    orders_by_event = {o.event_id: o for o in HrOrder.objects.filter(event_id__in=[e.pk for e in events_list])}
    return [
        SimpleNamespace(
            event=ev,
            label=ev.get_type_display(),
            order=orders_by_event.get(ev.pk),
            cancellable=access.can_cancel(user, ev),
        )
        for ev in events_list
    ]


def leave_today() -> date:
    return timezone.localdate()


def _leave_section(user: User, employee: Employee, today: date) -> dict[str, object]:
    """Context of the employee page's leave block: grant periods read live. Viewing never writes grants."""
    if not leave_access.can_view(user):
        return {"leave_visible": False}
    periods, nowhere = leave_ledger.periods(employee, today)
    return {
        "leave_visible": True,
        "leave_configured": leave_ledger.annual_configured(),
        "leave_periods": periods,
        "leave_nowhere": nowhere,
        "old_absences": list(
            Absence.objects.filter(employee_id=employee.pk).select_related("absence_type").order_by("-from_date", "-pk")
        ),
        "can_record_leave": leave_access.can_record(user),
        "can_manage_leave_settings": leave_access.can_manage_settings(user),
    }


ORDER_WARNING_KEY = "order_warning"  # session: old-program number clash, shown once on the employee page


def order_rows(employee: Employee) -> list[dict[str, Any]]:
    """Our orders (newest first) plus the old program's own command rows (read-only, state «Хуучин програм»)."""
    ours = list(employee.hr_orders.select_related("event").order_by("-date", "-pk"))
    taken = {o.command_id for o in ours if o.command_id}
    legacy = [c for c in Command.objects.filter(employee_id=employee.pk).order_by("-date", "-pk") if c.pk not in taken]
    links = orders.cancellation_links(ours)
    rows: list[dict[str, Any]] = [{"order": o, "legacy": None, **links[o.pk]} for o in ours]
    rows += [{"order": None, "legacy": c} for c in legacy]
    return rows


def change_rows(jobs: list[Any], order_list: list[dict[str, Any]]) -> tuple[list[Any], list[dict[str, Any]]]:
    """The Work tab's one list: each history row carries its order (`row.order`, `row.order_row` with the cancel
    links), and a cancelled change that had an order stays as a struck-through row. Returns (rows newest first,
    the order rows no change claims: old-program commands and the like)."""
    by_event = {r["order"].event_id: r for r in order_list if r["order"] and r["order"].event_id}
    hire = next((r for r in order_list if r["order"] and r["order"].is_hire), None)
    hire_job = next((j for j in reversed(jobs) if j.change_type == ChangeType.HIRE), None)  # `jobs` is newest first
    claimed: set[int] = set()
    for job in jobs:
        link = by_event.get(job.event_id) if job.event_id else (hire if job is hire_job else None)
        job.order_row, job.order = link, link["order"] if link else None
        job.is_cancelled = False
        if link:
            claimed.add(link["order"].pk)
    rows: list[Any] = list(jobs)
    for link in order_list:
        order = link["order"]
        if order and order.pk not in claimed and order.event and order.event.cancelled_at:
            rows.append(
                SimpleNamespace(
                    is_cancelled=True,
                    event=order.event,
                    order=order,
                    order_row=link,
                    label=order.event.get_type_display(),
                    effective=order.event.effective,
                )  # fmt: skip
            )
            claimed.add(order.pk)
    rows.sort(key=lambda r: r.effective if r.is_cancelled else r.period.lower, reverse=True)
    # An order whose change still waits is shown in the «Гарын үсэг хүлээж буй өөрчлөлт» block, not here.
    return rows, [
        r for r in order_list if (not r["order"] or r["order"].pk not in claimed) and not _awaiting(r["order"])
    ]


def _awaiting(order: HrOrder | None) -> bool:
    event = order.event if order is not None else None
    return event is not None and event.applied_at is None and event.cancelled_at is None


def _remember_warning(request: HttpRequest, order: HrOrder | None) -> None:
    """Keep the old-program number-clash note for the next employee page (the pop-up closes with a refresh)."""
    if order is None or not order.number or order.date is None:
        return
    text = orders.legacy_clash_warning(order.number, order.date, order.command_id)
    if text:
        request.session[ORDER_WARNING_KEY] = text


def _personal_sections(employee: Employee, can_manage: bool) -> dict[str, dict[str, object]]:
    """Read-mode context of the four field sections of the personal tab, from one form instance."""
    form = EmployeeForm(employee=employee)
    return {
        name: _section_context(employee, name, names, form, False, can_manage)
        for name, names in sections.SECTIONS.items()
    }


def _section_counts(personal: dict[str, list[personal_rows.PersonalRow]], employee: Employee) -> dict[str, object]:
    """The grey numbers of the personal tab menu: rows per list, addresses for «Холбоо барих, хаяг», and
    filled/total for «Бусад мэдээлэл»."""
    counts: dict[str, object] = {kind: len(rows) for kind, rows in personal.items() if kind != "address"}
    counts["address"] = len(personal.get("address", []))
    filled, total = sections.other_progress(employee)
    counts["other"] = f"{filled}/{total}"
    return counts


def _activity_context(activity: QuerySet[ActivityEntry]) -> dict[str, object]:
    """The activity log as the page shows it: the drawer's entries, the Түүх count and the header's latest line."""
    return {
        "activity": activity.select_related("by")[:100],
        "activity_count": activity.count(),
        "latest_activity": activity.select_related("by").first(),
    }


def _refresh_context(request: HttpRequest, employee: Employee) -> dict[str, object]:
    """What _page_refresh.html needs after a personal-tab write, without rebuilding the whole page (UI_RULES §2f)."""
    activity = access.visible_activity(_user(request), employee)
    return {"employee": employee, "today": timezone.localdate(), **_activity_context(activity)}


def detail_context(request: HttpRequest, employee: Employee) -> dict[str, object]:
    user, today = _user(request), timezone.localdate()
    can_salary = access.can_view_salary(user)
    can_manage = access.can_manage(user)
    can_view_personal = access.can_view_personal(user, employee)
    personal = _personal_lists(employee) if can_view_personal else {}
    activity = access.visible_activity(user, employee)
    ext = ext_of(employee)
    show_setup = ext is not None and ext.setup_required and can_manage
    setup_items = setup.status(employee, user) if show_setup else None
    row = row_for(employee, today)
    jobs = _mark_scheduled(
        employee.job_records.select_related("position", "department", "manager", "event").order_by("-period"),
        user,
        today,
    )
    changes, other_orders = change_rows(jobs, order_rows(employee))
    menu = [
        (t.value, events.PLACEMENT_LABEL if t == EventType.TRANSFER else t.label)
        for t in EventType
        if t in events.AVAILABLE.get(row.state, ())
        and access.can_record_event(user, t.value)
        and t not in events.PLACEMENT_TYPES[1:]  # one item opens all three, see event_form
    ]
    return {
        "employee": employee,
        "birth_place": records.birth_place_text(employee),
        "setup": setup_items,
        "setup_done": sum(i.done for i in setup_items) if setup_items else 0,
        "setup_complete": setup.complete_for(employee, user) if show_setup else False,
        "row": row,
        "jobs": changes,
        "waiting": _awaiting_rows(employee, user, can_salary),
        "salary": current_salary(employee, today) if can_salary else None,
        "salaries": (
            _mark_scheduled(employee.salary_records.select_related("event").order_by("-period"), user, today)
            if can_salary
            else []
        ),
        "orders": other_orders,
        "order_warning": request.session.pop(ORDER_WARNING_KEY, "") if request.method == "GET" else "",
        "event_menu": menu,
        "event_allowed": {value for value, _ in menu},
        "next_event": _next_event(employee, can_salary, today),
        "leave_until": events.leave_until(employee, today) if row.state == "long_leave" else None,
        **_activity_context(activity),
        "can_manage": can_manage,
        **_leave_section(user, employee, leave_today()),
        "can_view_salary": can_salary,
        "can_manage_salary": access.can_manage_salary(user),
        "can_view_personal": can_view_personal,
        "personal": personal,
        "personal_sections": _personal_sections(employee, can_manage) if can_view_personal else {},
        "section_counts": _section_counts(personal, employee) if can_view_personal else {},
        "today": today,
        "form": _employee_form(request, employee) if can_manage else None,
        "si_form": _salary_form(employee) if access.can_manage_salary(user) else None,
    }


@login_required
def employee_detail(request: HttpRequest, pk: int) -> HttpResponse:
    employee = _employee_for(request, pk)
    context = detail_context(request, employee)
    # One-time password from the hire form: shown once, then removed from the session.
    pending = request.session.get(ONE_TIME_LOGIN_KEY)
    if isinstance(pending, dict) and pending.get("employee") == employee.pk:
        del request.session[ONE_TIME_LOGIN_KEY]
        context["one_time_login"] = pending
    response = render(request, "employees/detail.html", context)
    if pending and context.get("one_time_login"):
        response["Cache-Control"] = "no-store"  # the page must not come back from the Back cache with the password
    return response


@login_required
def employee_add(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage(user))
    person = HirePersonForm(request.POST or None, request.FILES or None)
    job = HireJobForm(request.POST or None)
    extras = HireExtrasForm(request.POST or None)
    allow_salary = access.can_manage_salary(user)
    si = SalaryInsuranceForm(request.POST or None, prefix="si") if allow_salary else None
    address = HireAddressForm(request.POST or None, prefix="addr")
    contact = HireContactForm(request.POST or None, prefix="contact")
    order_form = OrderFieldsForm(request.POST or None, prefix="order")
    if (
        request.method == "POST"
        and person.is_valid()
        and order_form.is_valid()
        and job.is_valid()
        and extras.is_valid()
        and (si is None or si.is_valid())
        and address.is_valid()
        and contact.is_valid()
    ):
        salary = extras.cleaned_data["base_salary"] if allow_salary else None
        skip = {*EXT_FIELDS, *PHOTO_FIELDS, *BIRTH_FIELDS}
        columns = {k: person.cleaned_data[k] for k in person.fields if k not in skip}
        ext = {k: person.cleaned_data[k] for k in EXT_FIELDS}
        job_values = {f: job.cleaned_data[f] for f in JobRecord.JOB_FIELDS}
        address_values = address.values()[0] if address.filled() else None
        contact_values = contact.values()[0] if contact.filled() else None
        try:
            with transaction.atomic():
                employee = history.hire(
                    columns,
                    ext,
                    start=job.cleaned_data["start"],
                    job=job_values,
                    salary=salary,
                    by=user,
                    address=address_values,
                    contact=contact_values,
                    order_number=order_form.cleaned_data["number"],
                    order_date=order_form.cleaned_data["date"],
                    order_summary=order_form.cleaned_data["summary"],
                    order_issued_by=order_form.cleaned_data["issued_by"],
                )
                if person.cleaned_data.get("birth_city") is not None:
                    records.set_birth_place(
                        employee,
                        person.cleaned_data["birth_city"],
                        person.cleaned_data["birth_district"],
                        person.cleaned_data["birth_place_text"],
                        user,
                    )
                photo = person.photo_bytes()
                if photo:
                    macs_writes.save_photo(employee, photo)
                if si is not None and si.has_changed():
                    # Salary and insurance are production columns; logged as one sensitive entry.
                    records.update_salary_insurance(employee, {f: si.cleaned_data[f] for f in si.changed_data}, user)
                if extras.cleaned_data["create_login"]:
                    login, password = logins.create_login(employee, extras.cleaned_data["username"], by=user)
                    request.session[ONE_TIME_LOGIN_KEY] = {
                        "employee": employee.pk,
                        "username": login.username,
                        "password": password,
                    }
        except pw.PersonalConflict as error:  # the hire is rolled back with the address or contact
            person.add_error(None, str(error))
            return _hire_form(request, person, job, extras, allow_salary, si, address, contact, order_form, status=400)
        except OrderError as error:  # the hire is rolled back with its order
            order_form.add_service_errors(error.errors)
            return _hire_form(request, person, job, extras, allow_salary, si, address, contact, order_form, status=400)
        except (IntegrityError, DataError) as exc:
            person.add_error(None, DB_REFUSED)
            logger.warning("employee write refused: %s", exc)
            return _hire_form(request, person, job, extras, allow_salary, si, address, contact, order_form, status=400)
        _remember_warning(request, HrOrder.objects.filter(employee=employee, is_hire=True).first())
        if request.headers.get("HX-Request"):  # errors swap in place; success opens the new employee's page
            response = HttpResponse(status=204)
            response["HX-Redirect"] = reverse("employees:detail", args=[employee.pk])
            return response
        return redirect("employees:detail", pk=employee.pk)
    return _hire_form(request, person, job, extras, allow_salary, si, address, contact, order_form)


def _hire_form(
    request: HttpRequest,
    person: EmployeeForm,
    job: HireJobForm,
    extras: HireExtrasForm,
    allow_salary: bool,
    si: SalaryInsuranceForm | None,
    address: HireAddressForm,
    contact: HireContactForm,
    order_form: OrderFieldsForm,
    status: int = 200,
) -> HttpResponse:
    context = {
        "person": person,
        "job": job,
        "extras": extras,
        "allow_salary": allow_salary,
        "si": si,
        "address": address,
        "contact": contact,
        "order_form": order_form,
    }
    # htmx ignores 4xx responses, so the in-place error swap always answers 200 there.
    return render(request, "employees/add.html", context, status=200 if request.headers.get("HX-Request") else status)


@login_required
def login_create(request: HttpRequest, pk: int) -> HttpResponse:
    employee = _employee_for(request, pk)
    user = _user(request)
    _require(access.can_manage(user))
    form = CreateLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            login, password = logins.create_login(employee, form.cleaned_data["username"], by=user)
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            return _password_shown(request, login.username, password)
    return render(
        request,
        "employees/_modal.html",
        {
            "title": "Нэвтрэх эрх үүсгэх",
            "form": form,
            "action": request.path,
            "hint": "Нууц үг автоматаар үүснэ. Гарсны дараа ажилтанд өгнө; анх нэвтрэхдээ солино.",
        },
    )


def _password_shown(request: HttpRequest, username: str, password: str) -> HttpResponse:
    """The one-time password pop-up. The password lives only in this response."""
    response = render(
        request,
        "employees/_password_shown.html",
        {"username": username, "password": password},
    )
    response["Cache-Control"] = "no-store"
    return response


@login_required
def district_options(request: HttpRequest) -> HttpResponse:
    """The hire page's district select for the city posted as addr-city (htmx, on city change): only that city's
    districts; an empty select when no or an unknown city is given."""
    _require(access.can_manage(_user(request)))
    form = HireAddressForm({"addr-city": request.GET.get("addr-city", "")}, prefix="addr")
    return render(request, "employees/_district_field.html", {"field": form["district"]})


@login_required
def check_register(request: HttpRequest) -> HttpResponse:
    _require(access.can_manage(_user(request)))
    value = normalize_register_no(request.GET.get("register_no", ""))
    match = Employee.objects.filter(register_no=value).first() if value else None
    return render(request, "employees/_register_check.html", {"match": match})


# --- Task 10: htmx modals ---
def _done(employee: Employee) -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"  # reload keeps the #tab in the URL, so the same tab stays open
    return response


def _modal(request: HttpRequest, title: str, form: object, action: str, hint: str = "") -> HttpResponse:
    return render(request, "employees/_modal.html", {"title": title, "form": form, "action": action, "hint": hint})


def _require(allowed: bool) -> None:
    if not allowed:
        raise PermissionDenied


DB_REFUSED = "Мэдээллийг хадгалж чадсангүй: утга хэт урт эсвэл зөвшөөрөгдөөгүй байна."
PHOTO_FIELDS = ("photo", "photo_clear")
ONE_TIME_LOGIN_KEY = "one_time_login"  # session key: {employee, username, password} shown once on the detail page
TABS = ("work", "personal", "salary")
WORK_TAB_FIELDS = frozenset(
    {
        "first_hire_date",
        "work_conditions",
        "work_schedule",
        "probation_end",
        "job_type",
        "job_figure",
        "second_position",
        "office",
        "section",
        "branch",
        "sector_years",
    }
)


def _error_tab(form: EmployeeForm | None, si_form: SalaryInsuranceForm | None, posted: str) -> str:
    """The tab to open after a failed save, so the first error is not hidden behind another tab."""
    if si_form is not None and si_form.errors:
        return "salary"
    errors = set(form.errors) if form is not None else set()
    if errors & (PERSONAL_FIELDS | set(BIRTH_FIELDS)):
        return "personal"
    if errors & WORK_TAB_FIELDS:
        return "work"
    return posted if posted in TABS else "work"


@login_required
@require_POST
def employee_save(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    employee = _employee_for(request, pk)
    can_manage, can_salary = access.can_manage(user), access.can_manage_salary(user)
    _require(can_manage or can_salary)
    # Fresh instance for the form so update_employee can diff against the unmodified `employee`.
    form = None
    if can_manage:  # the Ажил tab posts no personal fields: they are completed from the stored values
        stored = Employee.objects.get(pk=pk)
        posted = sections.complete_post(EmployeeForm(employee=stored), request.POST)
        form = _employee_form(request, stored, posted, request.FILES)
    si_form = None
    if can_salary:  # without the permission, salary POST data is ignored entirely
        si_form = SalaryInsuranceForm(request.POST, prefix="si", employee=employee)
    tab = request.POST.get("tab", "")
    valid = (form is None or form.is_valid()) and (si_form is None or si_form.is_valid())
    changes: dict[str, Any] = {}
    si_changes: dict[str, Any] = {}
    if valid:
        # Only what this user changed is written; a field the old program changed meanwhile is asked about.
        if form is not None:
            columns, ext = form.values()
            changes = stale.resolve(form, employee, {**columns, **ext})
        if si_form is not None:
            si_changes = stale.resolve(si_form, employee, {f: si_form.cleaned_data[f] for f in si_form.changed_data})
        valid = not getattr(form, "conflicts", None) and not getattr(si_form, "conflicts", None)
    if valid:
        try:
            with transaction.atomic():
                if form is not None:
                    records.update_employee(employee, changes, user)
                    place = form.birth_place()
                    if place is not None:
                        records.set_birth_place(employee, *place, user)
                    photo = form.photo_bytes()
                    if photo is not None:
                        records.set_photo(employee, photo or None, by=user)
                if si_changes:
                    records.update_salary_insurance(employee, si_changes, user)
        except (IntegrityError, DataError) as exc:
            target = form if form is not None else si_form  # an accountant's save has only the salary form
            if target is not None:
                target.add_error(None, DB_REFUSED)
            logger.warning("employee write refused: %s", exc)
        else:
            if request.headers.get("HX-Request"):  # reload in place: no extra history step, the tab (#hash) stays
                response = HttpResponse(status=204)
                response["HX-Refresh"] = "true"
                return response
            url = reverse("employees:detail", args=[pk])
            return HttpResponseRedirect(f"{url}#{tab}" if tab in TABS else url, status=303)
    context = detail_context(request, employee) | {
        "form": form,
        "si_form": si_form,
        "tab": _error_tab(form, si_form, tab),
    }
    # htmx swaps only <main> with the errors (status 200: htmx ignores 4xx), so the URL and history stay as they were.
    status = 200 if request.headers.get("HX-Request") else 400
    return render(request, "employees/detail.html", context, status=status)


@login_required
def personal_section(request: HttpRequest, pk: int, section: str) -> HttpResponse:
    """One section of the personal tab (GET), its field block (GET ?fields=1) and its save (POST)."""
    if section not in sections.SECTIONS:
        raise Http404
    employee, user = _employee_for(request, pk), _user(request)
    _personal_access(user, employee)
    names = sections.SECTIONS[section]
    # Sections are edited on the spot (UI_RULES §2f): a save and «Болих» (?fields=1) answer with the field block only.
    fields_only = request.method == "POST" or request.GET.get("fields") == "1"
    template = "employees/_on_spot_fields.html" if fields_only else f"employees/_section_{section}.html"
    editing = False
    form: EmployeeForm | None = None
    can_manage = access.can_manage(user)
    if request.method == "POST":
        # Same flow as employee_save: fresh instance for the form, the visible one for the stale check and the write.
        stored = Employee.objects.get(pk=pk)
        form = EmployeeForm(sections.section_data(EmployeeForm(employee=stored), request.POST, names), employee=stored)
        sections.only_section_required(form, names)
        if form.is_valid():
            columns, ext = form.values()
            changes = stale.resolve(form, employee, {**columns, **ext})
            if not getattr(form, "conflicts", None):
                try:
                    with transaction.atomic():
                        records.update_employee(employee, changes, user)
                        place = form.birth_place()
                        if place is not None:
                            records.set_birth_place(employee, *place, user)
                except (IntegrityError, DataError) as exc:
                    form.add_error(None, DB_REFUSED)
                    logger.warning("employee section write refused: %s", exc)
                else:
                    employee = Employee.objects.get(pk=pk)
                    context = _section_context(employee, section, names, None, can_manage=can_manage, with_lists=False)
                    context |= {**_refresh_context(request, employee), "oob": True}
                    if section == "other":  # its menu entry counts filled fields
                        filled, total = sections.other_progress(employee)
                        context |= {"menu_sec": section, "menu_count": f"{filled}/{total}"}
                    return render(request, template, context)
        editing = True  # invalid, conflicting or refused: show the section for editing with its errors
    else:
        form = EmployeeForm(employee=Employee.objects.get(pk=pk))
    context = _section_context(employee, section, names, form, editing, can_manage, with_lists=not fields_only)
    return render(request, template, context, status=200)


def _section_context(
    employee: Employee,
    section: str,
    names: tuple[str, ...],
    form: EmployeeForm | None,
    editing: bool = False,
    can_manage: bool = False,
    with_lists: bool = True,
) -> dict[str, object]:
    """Context of a section template: its bound fields, or the stored form when the save succeeded (read mode)."""
    if form is None:
        form = EmployeeForm(employee=employee)
    rows = sections.read_rows(employee, section, records.birth_place_text(employee))
    return {
        "employee": employee,
        "section": section,
        "name": section,
        "title": sections.TITLES[section],
        "form": form,
        "fields": [form[name] for name in names],
        "editing": editing,
        "form_errors": sections.outside_errors(form, names) if editing else [],
        "rows": rows,
        "can_manage": can_manage,
        "personal": _personal_lists(employee) if with_lists and section in ("contact", "education") else {},
    }


@login_required
@require_POST
def add_note(request: HttpRequest, pk: int) -> HttpResponse:
    employee = _employee_for(request, pk)
    _require(access.can_manage(_user(request)))
    text = request.POST.get("text", "").strip()
    if text:
        records.add_note(employee, text=text, by=_user(request))
    return render(request, "employees/_activity.html", detail_context(request, employee) | {"oob": True})


@login_required
@require_POST
def toggle_setup(request: HttpRequest, pk: int, key: str) -> HttpResponse:
    employee = _employee_for(request, pk)
    _require(access.can_manage(_user(request)) and _needs_setup(employee))
    try:
        setup.toggle(employee, key, by=_user(request))
    except ValueError:
        return HttpResponse(status=400)
    return render(request, "employees/_setup.html", detail_context(request, employee))


@login_required
def correct_job(request: HttpRequest, pk: int, record_id: int) -> HttpResponse:
    employee = _employee_for(request, pk)
    _require(access.can_manage(_user(request)))
    record = get_object_or_404(employee.job_records.select_related("event"), pk=record_id)
    _require(not _is_scheduled(record.event, timezone.localdate()))  # scheduled rows are cancelled, not corrected
    form = JobCorrectionForm(request.POST or None, instance=JobRecord.objects.get(pk=record.pk))
    if request.method == "POST" and form.is_valid():
        changes = {f: form.cleaned_data[f] for f in JobRecord.JOB_FIELDS}
        try:
            history.correct_job(record, changes=changes, reason=form.cleaned_data["reason"], by=_user(request))
            return _done(employee)
        except HistoryError as error:
            form.add_error(None, str(error))
    return _modal(request, "Ажлын түүх засварлах", form, request.path)


@login_required
def correct_salary(request: HttpRequest, pk: int, record_id: int) -> HttpResponse:
    employee = _employee_for(request, pk)
    _require(access.can_manage_salary(_user(request)))
    record = get_object_or_404(employee.salary_records.select_related("event"), pk=record_id)
    _require(not _is_scheduled(record.event, timezone.localdate()))
    form = SalaryCorrectionForm(request.POST or None, initial={"amount": record.base_salary})
    if request.method == "POST" and form.is_valid():
        try:
            history.correct_salary(
                record, amount=form.cleaned_data["amount"], reason=form.cleaned_data["reason"], by=_user(request)
            )
            return _done(employee)
        except HistoryError as error:
            form.add_error(None, str(error))
    return _modal(request, "Цалин засварлах", form, request.path)


@login_required
def set_salary(request: HttpRequest, pk: int) -> HttpResponse:
    employee = _employee_for(request, pk)
    _require(access.can_manage_salary(_user(request)))
    _require(not employee.salary_records.exists())  # later changes go through corrections
    form = SetSalaryForm(request.POST or None, initial={"effective": employee.first_hire_date})
    if request.method == "POST" and form.is_valid():
        try:
            history.change_salary(
                employee,
                effective=form.cleaned_data["effective"],
                amount=form.cleaned_data["amount"],
                change_type="hire",
                note="",
                by=_user(request),
                first_only=True,
            )
            return _done(employee)
        except HistoryError as error:
            form.add_error(None, str(error))
    return _modal(request, "Цалин тогтоох", form, request.path)


# --- Personal tab: per-row add, edit and delete on the production tables (spec §4-§6) ---
def _personal_form(kind: str) -> type[PersonalRowForm]:
    if kind not in FORMS:
        raise Http404
    return FORMS[kind]


def _personal_lists(employee: Employee) -> dict[str, list[personal_rows.PersonalRow]]:
    return {kind: personal_rows.rows(kind, employee) for kind in pw.KINDS}


def _personal_modal(request: HttpRequest, form: PersonalRowForm, title: str, delete_url: str = "") -> HttpResponse:
    if isinstance(form, AddressRowForm):  # a city change re-fetches the modal, so the districts follow it
        form.fields["city"].widget.attrs.update(
            {
                "hx-get": request.path,
                "hx-trigger": "change",
                "hx-target": "closest div.fixed",
                "hx-swap": "outerHTML",
                "hx-include": "closest form",
                "hx-params": "not csrfmiddlewaretoken",
            }
        )
    context = {
        "title": title,
        "form": form,
        "action": request.path,
        "empty_lists": form.empty_lists(),
        "delete_url": delete_url,
    }
    return render(request, "employees/_personal_row_form.html", context)


def _get_override(request: HttpRequest, kind: str) -> dict[str, str]:
    """Values a GET request may set on a personal form. Only the address's visible fields (city, district, street),
    so a city change (htmx re-fetch) keeps what the user typed. Loaded_* values and every other kind come from
    the database."""
    if kind != "address":
        return {}
    return {name: request.GET[name] for name in ("city", "district", "street") if name in request.GET}


def _personal_access(user: User, employee: Employee) -> None:
    _require(access.can_manage(user) and access.can_view_personal(user, employee))


def _inline(request: HttpRequest, kind: str) -> bool:
    """The request comes from an inline list (UI_RULES §2f): answer with the list, not a pop-up or a reload."""
    return request.GET.get("inline") == "1" and kind in sections.INLINE_LISTS


def _auto_id(request: HttpRequest, kind: str) -> str:
    """An inline row's own element ids (inline-<kind>-<field>), so rows open in two lists never share one;
    Django's default for the pop-up."""
    return f"inline-{kind}-%s" if _inline(request, kind) else "id_%s"


def _inline_list(
    request: HttpRequest,
    employee: Employee,
    kind: str,
    open_key: object = None,
    form: PersonalRowForm | None = None,
    error: str = "",
    wrote: bool = False,
) -> HttpResponse:
    """The inline list block. After a write it also carries the activity log, the header's latest line and the
    menu count (out of band), so nothing on the page shows the old rows."""
    rows = personal_rows.rows(kind, employee)
    context = sections.inline_context(employee, kind, rows, True, open_key, form, error)
    if wrote:
        context |= {**_refresh_context(request, employee), "oob": True}
    return render(request, "employees/_inline_list.html", context)


@login_required
def personal_list(request: HttpRequest, pk: int, kind: str) -> HttpResponse:
    """An inline list with no row open (its ✕ / Esc)."""
    employee, user = _employee_for(request, pk), _user(request)
    if kind not in sections.INLINE_LISTS:
        raise Http404
    _personal_access(user, employee)
    return _inline_list(request, employee, kind)


@login_required
def personal_add(request: HttpRequest, pk: int, kind: str) -> HttpResponse:
    employee, user = _employee_for(request, pk), _user(request)
    form_cls = _personal_form(kind)
    _personal_access(user, employee)
    if request.method == "POST":
        form = form_cls(request.POST, adding=True, auto_id=_auto_id(request, kind))
        if form.is_valid():
            columns, ext = form.values()
            try:
                pw.add(kind, employee, columns, ext, by=user)
            except pw.PersonalConflict as error:
                form.add_error(None, str(error))
            else:
                return _inline_list(request, employee, kind, wrote=True) if _inline(request, kind) else _done(employee)
    else:
        form = form_cls(adding=True, initial=_get_override(request, kind), auto_id=_auto_id(request, kind))
    if _inline(request, kind):
        return _inline_list(request, employee, kind, open_key="new", form=form)
    return _personal_modal(request, form, f"{pw.TITLES[kind]}: нэмэх")


@login_required
def personal_edit(request: HttpRequest, pk: int, kind: str, key: int) -> HttpResponse:
    employee, user = _employee_for(request, pk), _user(request)
    form_cls = _personal_form(kind)
    _personal_access(user, employee)
    if request.method == "POST":
        form = form_cls(request.POST, auto_id=_auto_id(request, kind))
        if form.is_valid():
            columns, ext = form.values()
            try:
                pw.update(kind, employee, key, form.snapshot(), columns, ext, by=user)
            except pw.PersonalConflict as error:
                form.add_error(None, str(error))
            else:
                return _inline_list(request, employee, kind, wrote=True) if _inline(request, kind) else _done(employee)
    else:
        row = personal_rows.row(kind, employee, key)
        if row is None:
            raise Http404
        form = form_cls(
            initial=form_cls.from_snapshot(row.snapshot, row.ext) | _get_override(request, kind),
            auto_id=_auto_id(request, kind),
        )
    if _inline(request, kind):
        return _inline_list(request, employee, kind, open_key=key, form=form)
    delete_url = reverse("employees:personal_delete", args=[employee.pk, kind, key])
    return _personal_modal(request, form, f"{pw.TITLES[kind]}: засах", delete_url)


@login_required
def personal_delete(request: HttpRequest, pk: int, kind: str, key: int) -> HttpResponse:
    employee, user = _employee_for(request, pk), _user(request)
    form_cls = _personal_form(kind)
    _personal_access(user, employee)
    error = ""
    if request.method == "POST":
        form = form_cls(
            request.POST, auto_id=_auto_id(request, kind)
        )  # a delete uses only the loaded values the form carries
        try:
            pw.delete(kind, employee, key, form.snapshot(), by=user)
        except pw.PersonalConflict as conflict:
            error = str(conflict)
        else:
            return _inline_list(request, employee, kind, wrote=True) if _inline(request, kind) else _done(employee)
        if _inline(request, kind):  # the row stays open with the message
            return _inline_list(request, employee, kind, open_key=key, form=form, error=error)
    else:
        row = personal_rows.row(kind, employee, key)
        if row is None:
            raise Http404
        form = form_cls(initial=form_cls.from_snapshot(row.snapshot, row.ext))
    context = {"title": f"{pw.TITLES[kind]}: устгах", "form": form, "action": request.path, "error": error}
    return render(request, "employees/_personal_delete.html", context)


# --- Events ---
# Types whose change can need an order (the service decides; a pay or leave change never does).
ORDER_TYPES = frozenset(EventType.values) - {EventType.SALARY_CHANGE, EventType.LEAVE_START, EventType.LEAVE_RETURN}


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _event_initial(employee: Employee, type: str, effective: date, with_salary: bool) -> dict[str, Any]:
    """The values in force on `effective`, so the form shows what would change."""
    initial: dict[str, Any] = {"effective": effective}
    job = history.job_on(employee, effective)
    if job is not None:
        for name in ALLOWED_FIELDS[type]:
            initial[name] = getattr(job, f"{name}_id" if name in ("position", "department", "manager") else name)
    current = salary_on(employee, effective) if with_salary else None
    if current is not None:
        initial["salary"] = current.base_salary
    return initial


def _event_summary(employee: Employee, form: EventForm) -> str:
    """'Нягтлан → Ахлах нягтлан · 2026-11-01-нээс' for the values typed so far."""
    data = getattr(form, "cleaned_data", {})
    effective = data.get("effective")
    job = history.job_on(employee, effective) if effective else None
    if effective is None or job is None:
        return ""
    new = {f: data[f] for f in form.job_fields if f in data and getattr(job, f) != data[f]}
    parts = [f"{d['old']} → {d['new']}" for d in events._diffs(job, new)]
    salary = data.get("salary")
    current = salary_on(employee, effective)
    if form.with_salary and isinstance(salary, Decimal) and (current is None or current.base_salary != salary):
        parts.append(f"{current.base_salary if current else '—'} → {salary}")
    return f"{'; '.join(parts)} · {effective:%Y-%m-%d}-нээс" if parts else ""


@login_required
def event_form(request: HttpRequest, pk: int, type: str) -> HttpResponse:
    employee, user, today = _employee_for(request, pk), _user(request), timezone.localdate()
    if type not in EventType.values:
        raise Http404
    _require(access.can_record_event(user, type))
    with_salary = access.can_manage_salary(user) and type in SALARY_TYPES
    missing = events.start_placement_missing(employee)  # QC 1d: MACS-only employee with no department/position
    effective: date | None
    order_form = None
    if type in ORDER_TYPES:
        # A form rebuilt from an open one (kind change) keeps the order fields already typed, unvalidated.
        typed_order = {
            name: request.GET[f"order-{name}"]
            for name in OrderFieldsForm.base_fields
            if "prev_effective" in request.GET and f"order-{name}" in request.GET
        }
        order_form = OrderFieldsForm(request.POST or None, prefix="order", initial=typed_order)
    if request.method == "POST":
        form = EventForm(type, request.POST, with_salary=with_salary, start_missing=missing)
        if form.is_valid() and (order_form is None or order_form.is_valid()):
            data = form.cleaned_data
            salary = data.get("salary") if with_salary else None
            current = salary_on(employee, data["effective"])
            if salary is not None and type != EventType.SALARY_CHANGE and current and current.base_salary == salary:
                salary = None  # the form is pre-filled with the current pay; untouched means no pay change
            order_kwargs: dict[str, Any] = (
                {
                    "order_number": order_form.cleaned_data["number"],
                    "order_date": order_form.cleaned_data["date"],
                    "order_summary": order_form.cleaned_data["summary"],
                    "order_issued_by": order_form.cleaned_data["issued_by"],
                }
                if order_form is not None
                else {}
            )
            try:
                event = events.record(
                    employee,
                    type=type,
                    effective=data["effective"],
                    changes={f: data[f] for f in form.job_fields},
                    salary=salary,
                    reason=data.get("reason", ""),
                    fired_reason=data.get("fired_reason"),
                    pension=bool(data.get("pension")),
                    note=data["note"],
                    by=user,
                    expected_return=data.get("expected_return"),
                    start_department=data.get("start_department"),
                    start_position=data.get("start_position"),
                    **order_kwargs,
                )
                _remember_warning(request, HrOrder.objects.filter(event=event).first())
                return _done(employee)
            except EventError as error:
                for name, message in error.errors.items():
                    if name.startswith("order_") and order_form is not None:
                        order_form.add_service_errors({name: message})
                    else:
                        form.add_error(name if name in form.fields else None, message)
        effective = form.cleaned_data.get("effective") if hasattr(form, "cleaned_data") else None
        summary = _event_summary(employee, form)
    elif request.GET.get("summary"):
        form = EventForm(type, request.GET, with_salary=with_salary, start_missing=missing)
        form.full_clean()
        return render(request, "employees/_event_summary.html", {"summary": _event_summary(employee, form)})
    else:
        effective = _parse_day(request.GET.get("effective")) or today
        initial = _event_initial(employee, type, effective, with_salary)
        initial["reason"] = request.GET.get("reason", "")
        initial["note"] = request.GET.get("note", "")
        previous = _parse_day(request.GET.get("prev_effective"))
        if previous is not None:
            # The date was changed in an open form: keep what the user edited, refill
            # the rest with the values in force on the new date.
            typed = EventForm(type, request.GET, with_salary=with_salary, start_missing=missing)
            before = _event_initial(employee, type, previous, with_salary)
            for name, field in typed.fields.items():
                if name not in ("effective", "reason", "note") and name in request.GET:
                    value = typed[name].data
                    if field.has_changed(before.get(name), value):
                        initial[name] = value
        form = EventForm(type, initial=initial, with_salary=with_salary, start_missing=missing)
        summary = ""
    form.fields["effective"].widget.attrs.update(
        {
            "hx-get": request.path,
            "hx-trigger": "change",
            # Only the date, its note and the fields change with the date; the pop-up itself stays.
            "hx-target": "#event-body",
            "hx-select": "#event-body",
            "hx-swap": "outerHTML",
            "hx-include": "closest form",
            "hx-params": "not csrfmiddlewaretoken",
        }
    )
    placement = type in events.PLACEMENT_TYPES
    context = {
        "title": events.PLACEMENT_LABEL if placement else EventType(type).label,
        "kinds": [
            (reverse("employees:event", args=[employee.pk, t.value]), t.label, t == type)
            for t in events.PLACEMENT_TYPES
        ]
        if placement
        else [],
        "form": form,
        "order_form": order_form,
        "action": request.path,
        "summary": summary,
        # Rebuilt from an open form (kind change or a failed save): no open animation.
        "reload": request.method == "POST" or "prev_effective" in request.GET,
        "when": "past" if effective and effective < today else "future" if effective and effective > today else "",
    }
    return render(request, "employees/_event_form.html", context)


@login_required
def event_cancel(request: HttpRequest, pk: int, event_id: int) -> HttpResponse:
    employee = _employee_for(request, pk)
    event: Event = get_object_or_404(employee.events, pk=event_id)
    _require(access.can_cancel(_user(request), event))
    if event.status(timezone.localdate()) not in ("scheduled", "awaiting_signature"):
        raise Http404
    order = HrOrder.objects.filter(event=event).first()
    form = CancelEventForm(request.POST or None, signed=order is not None and order.state == OrderState.SIGNED)
    if request.method == "POST" and form.is_valid():
        try:
            events.cancel(
                event,
                reason=form.cleaned_data["reason"],
                by=_user(request),
                cancel_order_no=form.cleaned_data.get("cancel_order_no", ""),
            )
            return _done(employee)
        except EventError as error:
            for name, message in error.errors.items():
                form.add_error(name if name in form.fields else None, message)
    hint = ""
    if order is not None and order.state == OrderState.SIGNED:
        hint = f"Цуцлах дугаар нь № {order.number} тушаалыг хүчингүй болгосон ШИНЭ тушаалын дугаар."
    return _modal(request, f"Цуцлах: {event.get_type_display()} ({event.effective:%Y-%m-%d})", form, request.path, hint)


# --- Orders (тушаал) ---
def _order_for(request: HttpRequest, pk: int, order_id: int) -> tuple[Employee, HrOrder]:
    employee = _employee_for(request, pk)
    return employee, get_object_or_404(employee.hr_orders, pk=order_id)


@login_required
def order_edit(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    employee, order = _order_for(request, pk, order_id)
    _require(access.can_manage(_user(request)))
    if order.state not in (OrderState.PENDING, OrderState.REGISTERED):
        raise Http404  # signed and cancelled orders are final
    suggested = ""
    if request.method == "POST":
        form = OrderFieldsForm(request.POST, required=True)
        if form.is_valid():
            data = form.cleaned_data
            try:
                done = orders.register(
                    order,
                    number=data["number"],
                    date=data["date"],
                    summary=data["summary"],
                    issued_by=data["issued_by"],
                    by=_user(request),
                )
                _remember_warning(request, done)
                return _done(employee)
            except OrderError as error:
                form.add_service_errors(error.errors)
    else:
        suggested = "" if order.number else orders.suggest_number(date.today())
        form = OrderFieldsForm(
            required=True,
            initial={
                "number": order.number or suggested,
                "date": order.date,
                "summary": order.summary,
                "issued_by": order.issued_by,
            },
        )
    hint = "Дугаарыг автоматаар санал болгосон, шаардлагатай бол өөрчилнө үү." if suggested else ""
    return _modal(request, f"Тушаал: {order.get_order_type_display()}", form, request.path, hint)


@login_required
def order_upload(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    employee, order = _order_for(request, pk, order_id)
    _require(access.can_manage(_user(request)))
    form = OrderUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            orders.attach_signed_file(order, form.cleaned_data["file"], by=_user(request))
            return _done(employee)
        except OrderError as error:
            for message in error.errors.values():
                form.add_error(None, message)
    return _modal(request, "Гарын үсэгтэй файл хавсаргах", form, request.path)


FILE_TYPES = ((b"%PDF-", "application/pdf", ".pdf"), (b"\x89PNG", "image/png", ".png"))


def _order_download(request: HttpRequest, pk: int, order_id: int, pdf: bool) -> FileResponse:
    """The order filled from its Word template, as .docx or .pdf (a draft to print and sign)."""
    _, order = _order_for(request, pk, order_id)
    _require(access.can_manage(_user(request)))
    if order.state == OrderState.CANCELLED:
        raise Http404
    try:
        data = (order_docs.render_pdf if pdf else order_docs.render_order)(order, _user(request))
    except order_docs.OrderDocError:
        raise Http404 from None
    name = re.sub(r"[^\w-]", "_", order.number) if order.number else f"id{order.pk}"
    return FileResponse(
        io.BytesIO(data),
        as_attachment=True,
        filename=f"tushaal-{name}.{'pdf' if pdf else 'docx'}",
        content_type=order_docs.PDF_TYPE if pdf else order_docs.DOCX_TYPE,
    )


@login_required
def order_document(request: HttpRequest, pk: int, order_id: int) -> FileResponse:
    return _order_download(request, pk, order_id, pdf=False)


@login_required
def order_document_pdf(request: HttpRequest, pk: int, order_id: int) -> FileResponse:
    return _order_download(request, pk, order_id, pdf=True)


@login_required
def order_detail(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """Everything about one order in a pop-up (opened from the register): facts, links, history, actions."""
    employee, order = _order_for(request, pk, order_id)
    can_manage = access.can_manage(_user(request))
    siblings = list(employee.hr_orders.order_by("-date", "-pk"))
    job = order_docs.build_context(order, _user(request))  # department and position as the order document shows them
    event = order.event
    context = {
        "change_status": event.status(timezone.localdate()) if event else "effective",
        "cancel_change": event is not None
        and event.cancelled_at is None
        and event.status(timezone.localdate()) in ("scheduled", "awaiting_signature")
        and access.can_cancel(_user(request), event),
        "employee": employee,
        "order": order,
        "can_manage": can_manage,
        "links": orders.cancellation_links(siblings)[order.pk],
        "entries": order.activity.select_related("by").order_by("-at", "-id"),
        "department": job["department"],
        "position": job["position"],
        "editable": can_manage and order.state in (OrderState.PENDING, OrderState.REGISTERED),
    }
    return render(request, "employees/_order_detail.html", context)


@login_required
def order_cancel(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """Cancel one registered (not yet signed) order that has no change behind it (the hire order) with a reason.
    A change's order is cancelled together with the change (`event_cancel`)."""
    employee, order = _order_for(request, pk, order_id)
    _require(access.can_manage(_user(request)))
    if order.state != OrderState.REGISTERED or order.event_id is not None:
        raise Http404  # pending: never issued; signed or cancelled: final; a change's order goes with its change
    form = CancelEventForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            orders.cancel_order(order, reason=form.cleaned_data["reason"], by=_user(request))
            return _done(employee)
        except OrderError as error:
            form.add_error(None, "; ".join(error.errors.values()))
    hint = "Өөрчлөлт өөрөө хэвээр үлдэнэ."
    return _modal(
        request, f"Тушаал цуцлах: {order.get_order_type_display()} № {order.number}", form, request.path, hint
    )


@login_required
def order_history(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """Who created, registered, edited, signed or cancelled this order, and when (read-only pop-up)."""
    employee, order = _order_for(request, pk, order_id)
    entries = order.activity.select_related("by").order_by("-at", "-id")
    return render(request, "employees/_order_history.html", {"employee": employee, "order": order, "entries": entries})


@login_required
def order_file(request: HttpRequest, pk: int, order_id: int) -> FileResponse:
    _, order = _order_for(request, pk, order_id)  # visible employees only: anyone else gets 404
    if not order.file:
        raise Http404
    try:
        handle = order.file.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    head = handle.read(8)
    handle.seek(0)
    content_type, ext = next(((t, e) for magic, t, e in FILE_TYPES if head.startswith(magic)), ("image/jpeg", ".jpg"))
    response = FileResponse(handle, content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = f'inline; filename="order-{order.pk}{ext}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _register_context(request: HttpRequest) -> dict[str, Any]:
    get = request.GET
    state = get.get("state", "")
    valid_states = {s.value for s in OrderState} | {order_register.LEGACY}
    state = state if state in valid_states else ""
    year, order_type, department = (
        _id_param(get.get("year")),
        _id_param(get.get("order_type")),
        _id_param(get.get("department")),
    )
    if order_type is not None and order_type not in OrderType.values:
        order_type = None
    if year is not None and not 1 <= year <= 9999:
        year = None
    today = timezone.localdate()
    q = get.get("q", "").strip()[:100]
    rows = order_register.register_rows(
        _user(request),
        year=year,
        order_type=order_type,
        department_id=department,
        state=state or None,
        today=today,
        q=q,
    )
    return {
        "rows": rows,
        "q": q,
        "year": year,
        "order_type": order_type,
        "department": department,
        "state": state,
        "types": OrderType.choices,
        "states": [*OrderState.choices, (order_register.LEGACY, "Хуучин програм")],
        "departments": Department.objects.exclude(ext__active=False),
        "years": list(range(today.year, today.year - 12, -1)),
        "querystring": request.GET.urlencode(),
        "today": today,
    }


@login_required
def order_suggest(request: HttpRequest) -> JsonResponse:
    """`{number, date}` for the «Санал болгох» button: the next number of the year of `?date=` (else today)
    and the date to use when the form's date is still empty. `number` is '' when no number can be guessed."""
    _require(access.can_manage(_user(request)))
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = date.today()
    return JsonResponse({"number": orders.suggest_number(day), "date": day.isoformat()})


@login_required
@vary_on_headers("HX-Request")
def orders_page(request: HttpRequest) -> HttpResponse:
    context = _register_context(request)
    is_partial = bool(request.headers.get("HX-Request")) and not request.headers.get("HX-History-Restore-Request")
    return render(request, "employees/_order_register_rows.html" if is_partial else "employees/orders.html", context)


@login_required
def orders_print(request: HttpRequest) -> HttpResponse:
    context = _register_context(request)
    buckets: dict[str, list[order_register.RegisterRow]] = {}
    for row in sorted(context["rows"], key=lambda r: (r.date is None, r.date)):
        buckets.setdefault(row.department or NO_DEPARTMENT, []).append(row)
    context["groups"] = sorted(buckets.items(), key=lambda item: (item[0] == NO_DEPARTMENT, item[0]))
    context["company"] = CompanySettings.get().name
    return render(request, "employees/orders_print.html", context)


# --- Ctrl+K command palette ---
def _palette_page_pk(path: str) -> int | None:
    """The pk of the employee record the palette was opened on, from the page path the browser sends. Only the
    employee detail page counts (matched by the resolver, not by the text); anything else is None."""
    if not path or len(path) > palette.FROM_LIMIT:
        return None
    try:
        match = resolve(path)
    except Resolver404:
        return None
    if match.app_name != "employees" or match.url_name != "detail":
        return None
    pk = match.kwargs.get("pk")
    return pk if isinstance(pk, int) else None


@login_required
@require_GET
def palette_search(request: HttpRequest) -> HttpResponse:
    """The palette's answers for the typed query: an HTML fragment the palette script swaps in. Never cached,
    because the answer depends on who asks (what they may open or see)."""
    user = _user(request)
    q = request.GET.get("q", "")
    today = timezone.localdate()
    people = palette.people(user, q, today)
    single = people[0] if len(people) == 1 else None  # the person's own actions only when exactly one person matched
    # The remembered items are shown only in the empty box; the browser sends them, the server re-checks each one.
    recent = palette.recent(user, palette.parse_refs(request.GET.get("recent", "")), today) if not q.split() else []
    # On an employee's record page the empty box starts with that person's actions. A typed query never has this group.
    page_pk = None if q.split() else _palette_page_pk(request.GET.get("from", ""))
    current = palette.current(user, page_pk, today) if page_pk is not None else None
    response = render(
        request,
        "employees/_palette_results.html",
        {
            "recent": recent,
            "current": current,
            "current_actions": palette.person_actions(user, current) if current else [],
            "screens": palette.screens(user, q),
            "fixed_urls": palette.fixed_urls(user),  # only these pages get a data-palette-ref (what can be recalled)
            "actions": palette.actions(user, q),
            "people": people,
            "words": q[: palette.QUERY_LIMIT].split(),  # highlighted in the rows; empty for the empty box
            "orders": palette.orders(user, q),
            "person": single,
            "person_actions": palette.person_actions(user, single) if single else [],
        },
    )
    response["Cache-Control"] = "no-store"
    return response
