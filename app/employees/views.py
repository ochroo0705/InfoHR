from datetime import date
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.vary import vary_on_headers

from employees import access, attention
from employees.forms import (
    CancelEventForm,
    EducationFormSet,
    EmployeeForm,
    EventForm,
    FamilyFormSet,
    GiftFormSet,
    HireExtrasForm,
    HireJobForm,
    HirePersonForm,
    JobCorrectionForm,
    SalaryCorrectionForm,
    SalaryInsuranceForm,
    SetSalaryForm,
    TalentFormSet,
)
from employees.listing import Row, employee_rows, row_for
from employees.models import (
    PERSONAL_FIELDS,
    ActivityEntry,
    ActivityKind,
    Department,
    Employee,
    EmployeeType,
    Event,
    EventType,
    JobRecord,
    SalaryInsurance,
)
from employees.services import events, history, records, setup
from employees.services.events import ALLOWED_FIELDS, SALARY_TYPES, EventError
from employees.services.history import HistoryError, salary_on
from employees.validators import normalize_register_no

STATES = {"active": "Ажиллаж байгаа", "upcoming": "Ажилд орох", "long_leave": "Урт чөлөөтэй", "left": "Гарсан"}
NO_DEPARTMENT = "Хэлтэсгүй"


def _group_by_department(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    buckets: dict[str, list[Row]] = {}
    for row in rows:
        name = row.job.department.name if row.job else NO_DEPARTMENT
        buckets.setdefault(name, []).append(row)
    return sorted(buckets.items(), key=lambda item: (item[0] == NO_DEPARTMENT, item[0]))


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


@login_required
@vary_on_headers("HX-Request")
def employee_list(request: HttpRequest) -> HttpResponse:
    qs = access.visible_employees(_user(request))
    q = request.GET.get("q", "").strip()
    if q:
        match = (
            Q(family_name__icontains=q) | Q(given_name__icontains=q) | Q(code__icontains=q) | Q(work_phone__icontains=q)
        )
        if _user(request).has_perm("employees.view_personal"):
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
    view = "grid" if request.GET.get("view") == "grid" else "table"
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
        "departments": Department.objects.all(),
        "types": EmployeeType.choices,
        "can_manage": access.can_manage(_user(request)),
    }
    is_partial = bool(request.headers.get("HX-Request")) and not request.headers.get("HX-History-Restore-Request")
    if not is_partial:  # the strip ignores filters (and search): it covers everyone the user can see
        if q:
            all_rows = employee_rows(access.visible_employees(_user(request)), today)
        context["attention"], context["attention_hidden"] = attention.split(
            _user(request), attention.items(_user(request), all_rows, today)
        )
    template = "employees/_results.html" if is_partial else "employees/list.html"
    return render(request, template, context)


@login_required
@require_POST
def attention_toggle(request: HttpRequest) -> HttpResponse:
    """ "Мэдлээ" / "Дахин харуулах" on one Анхаарах item; returns the box."""
    user, today = _user(request), timezone.localdate()
    found = attention.items(user, employee_rows(access.visible_employees(user), today), today)
    item = next((a for a in found if a.key == request.POST.get("key")), None)
    if item is None:
        raise Http404
    if request.POST.get("action") == "restore":
        attention.restore(user, item)
    else:
        attention.dismiss(user, item)
    shown, hidden = attention.split(user, found)
    return render(request, "employees/_attention.html", {"attention": shown, "attention_hidden": hidden})


def _employee_for(request: HttpRequest, pk: int) -> Employee:
    return get_object_or_404(access.visible_employees(_user(request)), pk=pk)


def _employee_form(request: HttpRequest, employee: Employee, data: Any = None, files: Any = None) -> EmployeeForm:
    form = EmployeeForm(data, files, instance=employee)
    if not access.can_view_personal(_user(request), employee):  # those inputs are not on the page
        for name in PERSONAL_FIELDS:
            form.fields.pop(name, None)
    return form


def _salary_form(employee: Employee) -> SalaryInsuranceForm:
    instance = SalaryInsurance.objects.filter(employee=employee).first() or SalaryInsurance(employee=employee)
    return SalaryInsuranceForm(instance=instance, prefix="si")


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


def detail_context(request: HttpRequest, employee: Employee) -> dict[str, object]:
    user, today = _user(request), timezone.localdate()
    can_salary = access.can_view_salary(user)
    can_manage = access.can_manage(user)
    activity = access.visible_activity(user, employee)
    show_setup = employee.setup_required and can_manage
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
        "setup": setup_items,
        "setup_done": sum(i.done for i in setup_items) if setup_items else 0,
        "setup_complete": setup.complete_for(employee, user) if show_setup else False,
        "row": row,
        "jobs": _mark_scheduled(
            employee.job_records.select_related("position", "department", "manager", "event").order_by("-period"),
            user,
            today,
        ),
        "salary": salary_on(employee, today) if can_salary else None,
        "salaries": (
            _mark_scheduled(employee.salary_records.select_related("event").order_by("-period"), user, today)
            if can_salary
            else []
        ),
        "event_menu": menu,
        "event_allowed": {value for value, _ in menu},
        "next_event": _next_event(employee, can_salary, today),
        "leave_until": events.leave_until(employee, today) if row.state == "long_leave" else None,
        "details": SalaryInsurance.objects.filter(employee=employee).first() if can_salary else None,
        "activity": activity.select_related("by")[:100],
        "activity_count": activity.count(),
        "latest_activity": activity.select_related("by").first(),
        "can_manage": can_manage,
        "can_view_salary": can_salary,
        "can_manage_salary": access.can_manage_salary(user),
        "can_view_personal": access.can_view_personal(user, employee),
        "today": today,
        "form": _employee_form(request, employee) if can_manage else None,
        "si_form": _salary_form(employee) if access.can_manage_salary(user) else None,
    }


@login_required
def employee_detail(request: HttpRequest, pk: int) -> HttpResponse:
    employee = _employee_for(request, pk)
    return render(request, "employees/detail.html", detail_context(request, employee))


@login_required
def employee_add(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage(user))
    person = HirePersonForm(request.POST or None, request.FILES or None)
    job = HireJobForm(request.POST or None)
    extras = HireExtrasForm(request.POST or None)
    allow_salary = access.can_manage_salary(user)
    si = SalaryInsuranceForm(request.POST or None, prefix="si") if allow_salary else None
    lists = [
        (key, title, formset_class(request.POST or None, instance=Employee(), prefix=key))
        for key, (formset_class, title) in LISTS.items()
    ]
    formsets = [formset for _, _, formset in lists]
    if (
        request.method == "POST"
        and person.is_valid()
        and job.is_valid()
        and extras.is_valid()
        and (si is None or si.is_valid())
        and all(formset.is_valid() for formset in formsets)
    ):
        salary = extras.cleaned_data["base_salary"] if allow_salary else None
        with transaction.atomic():
            employee = history.hire(
                person.save(commit=False),
                start=job.cleaned_data["start"],
                job={f: job.cleaned_data[f] for f in JobRecord.JOB_FIELDS},
                salary=salary,
                by=user,
            )
            if si is not None and si.has_changed():
                si.instance.employee = employee
                si.save()
            for formset in formsets:
                formset.instance = employee
                formset.save()
            if extras.cleaned_data["create_login"]:
                login = User.objects.create_user(
                    extras.cleaned_data["username"].strip(),
                    first_name=employee.given_name,
                    last_name=employee.family_name,
                )
                login.set_unusable_password()  # admin sets the password in the back office
                login.save()
                employee.user = login
                employee.save(update_fields=["user"])
        return redirect("employees:detail", pk=employee.pk)
    return render(
        request,
        "employees/add.html",
        {
            "person": person,
            "job": job,
            "extras": extras,
            "allow_salary": allow_salary,
            "si": si,
            "lists": lists,
        },
    )


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


TABS = ("work", "personal", "salary")
WORK_TAB_FIELDS = frozenset(
    {
        "first_hire_date",
        "work_conditions",
        "work_schedule",
        "probation_end",
        "car_ownership",
        "clothing_size",
        "shoe_size",
        "elected_position",
    }
)


def _error_tab(form: EmployeeForm | None, si_form: SalaryInsuranceForm | None, posted: str) -> str:
    """The tab to open after a failed save, so the first error is not hidden behind another tab."""
    if si_form is not None and si_form.errors:
        return "salary"
    errors = set(form.errors) if form is not None else set()
    if errors & PERSONAL_FIELDS:
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
    form = _employee_form(request, Employee.objects.get(pk=pk), request.POST, request.FILES) if can_manage else None
    si_form = None
    if can_salary:  # without the permission, salary POST data is ignored entirely
        instance = SalaryInsurance.objects.filter(employee=employee).first() or SalaryInsurance(employee=employee)
        si_form = SalaryInsuranceForm(request.POST, instance=instance, prefix="si")
    tab = request.POST.get("tab", "")
    if (form is None or form.is_valid()) and (si_form is None or si_form.is_valid()):
        with transaction.atomic():
            if form is not None:
                records.update_employee(employee, {f: form.cleaned_data[f] for f in form.changed_data}, user)
            if si_form is not None and si_form.changed_data:
                records.update_salary_insurance(
                    employee, {f: si_form.cleaned_data[f] for f in si_form.changed_data}, user
                )
        url = reverse("employees:detail", args=[pk])
        return HttpResponseRedirect(f"{url}#{tab}" if tab in TABS else url, status=303)
    context = detail_context(request, employee) | {
        "form": form,
        "si_form": si_form,
        "tab": _error_tab(form, si_form, tab),
    }
    return render(request, "employees/detail.html", context, status=400)


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
    _require(access.can_manage(_user(request)) and employee.setup_required)
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


LISTS: dict[str, tuple[Any, str]] = {
    "family": (FamilyFormSet, "Гэр бүл"),
    "education": (EducationFormSet, "Боловсрол"),
    "talents": (TalentFormSet, "Авьяас"),
    "gifts": (GiftFormSet, "Олгосон бэлэг"),
}


def _edit_list(request: HttpRequest, pk: int, kind: str) -> HttpResponse:
    employee = _employee_for(request, pk)
    _require(access.can_manage(_user(request)))
    formset_class, title = LISTS[kind]
    formset = formset_class(request.POST or None, instance=employee, prefix=kind)
    if request.method == "POST" and formset.is_valid():
        with transaction.atomic():
            formset.save()
            if formset.has_changed():
                ActivityEntry.objects.create(
                    employee=employee,
                    by=_user(request),
                    kind=ActivityKind.CHANGED,
                    personal=True,  # family, education, talents and gifts are Personal-tab data
                    message=f"{title} жагсаалт өөрчилсөн",
                )
        return _done(employee)
    return render(request, "employees/_list_modal.html", {"title": title, "formset": formset, "action": request.path})


@login_required
def edit_family(request: HttpRequest, pk: int) -> HttpResponse:
    return _edit_list(request, pk, "family")


@login_required
def edit_education(request: HttpRequest, pk: int) -> HttpResponse:
    return _edit_list(request, pk, "education")


@login_required
def edit_talents(request: HttpRequest, pk: int) -> HttpResponse:
    return _edit_list(request, pk, "talents")


@login_required
def edit_gifts(request: HttpRequest, pk: int) -> HttpResponse:
    return _edit_list(request, pk, "gifts")


# --- Events ---
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
    effective: date | None
    if request.method == "POST":
        form = EventForm(type, request.POST, with_salary=with_salary)
        if form.is_valid():
            data = form.cleaned_data
            salary = data.get("salary") if with_salary else None
            current = salary_on(employee, data["effective"])
            if salary is not None and type != EventType.SALARY_CHANGE and current and current.base_salary == salary:
                salary = None  # the form is pre-filled with the current pay; untouched means no pay change
            try:
                events.record(
                    employee,
                    type=type,
                    effective=data["effective"],
                    changes={f: data[f] for f in form.job_fields},
                    salary=salary,
                    reason=data["reason"],
                    note=data["note"],
                    by=user,
                    expected_return=data.get("expected_return"),
                )
                return _done(employee)
            except EventError as error:
                for name, message in error.errors.items():
                    form.add_error(name if name in form.fields else None, message)
        effective = form.cleaned_data.get("effective") if hasattr(form, "cleaned_data") else None
        summary = _event_summary(employee, form)
    elif request.GET.get("summary"):
        form = EventForm(type, request.GET, with_salary=with_salary)
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
            typed = EventForm(type, request.GET, with_salary=with_salary)
            before = _event_initial(employee, type, previous, with_salary)
            for name, field in typed.fields.items():
                if name not in ("effective", "reason", "note") and name in request.GET:
                    value = typed[name].data
                    if field.has_changed(before.get(name), value):
                        initial[name] = value
        form = EventForm(type, initial=initial, with_salary=with_salary)
        summary = ""
    form.fields["effective"].widget.attrs.update(
        {
            "hx-get": request.path,
            "hx-trigger": "change",
            "hx-target": "closest div.fixed",
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
        "action": request.path,
        "summary": summary,
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
    form = CancelEventForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            events.cancel(event, reason=form.cleaned_data["reason"], by=_user(request))
            return _done(employee)
        except EventError as error:
            for name, message in error.errors.items():
                form.add_error(name if name in form.fields else None, message)
    return _modal(request, f"Цуцлах: {event.get_type_display()} ({event.effective:%Y-%m-%d})", form, request.path)
