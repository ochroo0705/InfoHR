import logging
from datetime import date
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DataError, IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.vary import vary_on_headers
from leave import access as leave_access
from leave.services import ledger as leave_ledger
from macs.models import Absence, Command

from employees import access, attention, sections, stale
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
from employees.listing import Row, current_salary, employee_rows, row_for
from employees.models import (
    EXT_FIELDS,
    PERSONAL_FIELDS,
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
STATES = {"active": "Ажиллаж байгаа", "upcoming": "Ажилд орох", "long_leave": "Урт чөлөөтэй", "left": "Гарсан"}
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
    all_rows = rows
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
        "states": STATES,
        "departments": Department.objects.exclude(ext__active=False),
        "types": EmployeeType.choices,
        "can_manage": access.can_manage(_user(request)),
    }
    is_partial = bool(request.headers.get("HX-Request")) and not request.headers.get("HX-History-Restore-Request")
    if not is_partial:  # the strip ignores filters (and search): it covers everyone the user can see
        if q:
            all_rows = employee_rows(access.visible_employees(_user(request)).filter(ext__isnull=False), today)
        context.update(_attention_context(_user(request), attention.items(_user(request), all_rows, today)))
    template = "employees/_results.html" if is_partial else "employees/list.html"
    return render(request, template, context)


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
    return event is not None and event.status(today) == "scheduled"


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
    qs = employee.events.filter(cancelled_at__isnull=True, effective__gt=today)
    if not can_salary:  # a scheduled pay change must not leak to people who cannot see pay
        qs = qs.exclude(type=EventType.SALARY_CHANGE)
    return qs.order_by("effective").first()


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
    rows: list[dict[str, Any]] = [{"order": o, "legacy": None} for o in ours]
    rows += [{"order": None, "legacy": c} for c in legacy]
    return rows


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
        "jobs": _mark_scheduled(
            employee.job_records.select_related("position", "department", "manager", "event", "event__order").order_by(
                "-period"
            ),
            user,
            today,
        ),
        "salary": current_salary(employee, today) if can_salary else None,
        "salaries": (
            _mark_scheduled(employee.salary_records.select_related("event").order_by("-period"), user, today)
            if can_salary
            else []
        ),
        "orders": order_rows(employee),
        "order_warning": request.session.pop(ORDER_WARNING_KEY, "") if request.method == "GET" else "",
        "event_menu": menu,
        "event_allowed": {value for value, _ in menu},
        "next_event": _next_event(employee, can_salary, today),
        "leave_until": events.leave_until(employee, today) if row.state == "long_leave" else None,
        "activity": activity.select_related("by")[:100],
        "activity_count": activity.count(),
        "latest_activity": activity.select_related("by").first(),
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


def _modal(request: HttpRequest, title: str, form: object, action: str) -> HttpResponse:
    return render(request, "employees/_modal.html", {"title": title, "form": form, "action": action})


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
    """One section of the personal tab: read mode (GET), edit mode (GET ?edit=1) and its save (POST)."""
    if section not in sections.SECTIONS:
        raise Http404
    employee, user = _employee_for(request, pk), _user(request)
    _personal_access(user, employee)
    names = sections.SECTIONS[section]
    template = f"employees/_section_{section}.html"
    editing = request.GET.get("edit") == "1"
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
                    return render(
                        request, template, _section_context(employee, section, names, form=None, can_manage=can_manage)
                    )
        editing = True  # invalid, conflicting or refused: show the section for editing with its errors
    else:
        form = EmployeeForm(employee=Employee.objects.get(pk=pk))
    return render(request, template, _section_context(employee, section, names, form, editing, can_manage), status=200)


def _section_context(
    employee: Employee,
    section: str,
    names: tuple[str, ...],
    form: EmployeeForm | None,
    editing: bool = False,
    can_manage: bool = False,
) -> dict[str, object]:
    """Context of a section template: its bound fields, or the stored form when the save succeeded (read mode)."""
    if form is None:
        form = EmployeeForm(employee=employee)
    rows = sections.read_rows(employee, section, records.birth_place_text(employee))
    return {
        "employee": employee,
        "section": section,
        "title": sections.TITLES[section],
        "number": sections.NUMBERS[section],
        "form": form,
        "fields": [form[name] for name in names],
        "editing": editing,
        "form_errors": sections.outside_errors(form, names) if editing else [],
        "rows": rows,
        "can_manage": can_manage,
        "personal": _personal_lists(employee) if section in ("contact", "education") else {},
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


@login_required
def personal_add(request: HttpRequest, pk: int, kind: str) -> HttpResponse:
    employee, user = _employee_for(request, pk), _user(request)
    form_cls = _personal_form(kind)
    _personal_access(user, employee)
    if request.method == "POST":
        form = form_cls(request.POST, adding=True)
        if form.is_valid():
            columns, ext = form.values()
            try:
                pw.add(kind, employee, columns, ext, by=user)
            except pw.PersonalConflict as error:
                form.add_error(None, str(error))
            else:
                return _done(employee)
    else:
        form = form_cls(adding=True, initial=_get_override(request, kind))
    return _personal_modal(request, form, f"{pw.TITLES[kind]}: нэмэх")


@login_required
def personal_edit(request: HttpRequest, pk: int, kind: str, key: int) -> HttpResponse:
    employee, user = _employee_for(request, pk), _user(request)
    form_cls = _personal_form(kind)
    _personal_access(user, employee)
    if request.method == "POST":
        form = form_cls(request.POST)
        if form.is_valid():
            columns, ext = form.values()
            try:
                pw.update(kind, employee, key, form.snapshot(), columns, ext, by=user)
            except pw.PersonalConflict as error:
                form.add_error(None, str(error))
            else:
                return _done(employee)
    else:
        row = personal_rows.row(kind, employee, key)
        if row is None:
            raise Http404
        form = form_cls(initial=form_cls.from_snapshot(row.snapshot, row.ext) | _get_override(request, kind))
    delete_url = reverse("employees:personal_delete", args=[employee.pk, kind, key])
    return _personal_modal(request, form, f"{pw.TITLES[kind]}: засах", delete_url)


@login_required
def personal_delete(request: HttpRequest, pk: int, kind: str, key: int) -> HttpResponse:
    employee, user = _employee_for(request, pk), _user(request)
    form_cls = _personal_form(kind)
    _personal_access(user, employee)
    error = ""
    if request.method == "POST":
        form = form_cls(request.POST)  # a delete uses only the loaded values the form carries
        try:
            pw.delete(kind, employee, key, form.snapshot(), by=user)
        except pw.PersonalConflict as conflict:
            error = str(conflict)
        else:
            return _done(employee)
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
    if event.status(timezone.localdate()) != "scheduled":
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
    return _modal(request, f"Цуцлах: {event.get_type_display()} ({event.effective:%Y-%m-%d})", form, request.path)


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
        form = OrderFieldsForm(
            required=True,
            initial={
                "number": order.number,
                "date": order.date,
                "summary": order.summary,
                "issued_by": order.issued_by,
            },
        )
    return _modal(request, f"Тушаал: {order.get_order_type_display()}", form, request.path)


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


def _id_param(value: str | None) -> int | None:
    if not value or len(value) > 12 or not value.isdecimal():
        return None
    number = int(value)
    return number if 0 < number <= 2147483647 else None  # must fit a positive int4


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
    rows = order_register.register_rows(
        _user(request), year=year, order_type=order_type, department_id=department, state=state or None, today=today
    )
    return {
        "rows": rows,
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
