import io
import logging
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from accounts.audit import record_export
from accounts.models import User
from config import batching
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.vary import vary_on_headers
from reports.staff_list import REPORT as STAFF_LIST

from employees import access, attention, company_stats, sections
from employees import today as facts
from employees.forms import (
    FORMS,
    AddressRowForm,
    CreateLoginForm,
    EmployeeForm,
    HireAddressForm,
    JobCorrectionForm,
    OrderFieldsForm,
    PersonalRowForm,
    SalaryCorrectionForm,
    SetSalaryForm,
)
from employees.listing import Row, employee_rows
from employees.models import (
    Employee,
    HrOrder,
    JobRecord,
)
from employees.services import (
    event_page,
    hire_page,
    history,
    logins,
    order_detail_page,
    order_docs,
    order_files,
    order_popups,
    order_print_page,
    order_register,
    order_register_page,
    order_signing,
    orders,
    page_writes,
    palette_answer,
    personal_rows,
    print_jobs,
    records,
    setup,
)
from employees.services import personal_writes as pw
from employees.services.detail_page import (  # noqa: F401  (tests import these names from here)
    ACTIVITY_BATCH,
    _is_scheduled,
    _next_event,
    _section_context,
    activity_context,
    change_rows,
    detail_facts,
    order_rows,
)
from employees.services.detail_page import (
    needs_setup as _needs_setup,
)
from employees.services.history import HistoryError
from employees.services.page_writes import (  # noqa: F401  (tests and other modules import these names from here)
    DB_REFUSED,
    TABS,
    _surface_hidden_errors,
)

# views.away_cells stays importable from here: the Today tests call it
from employees.services.today_page import away_cells, today_facts  # noqa: F401
from employees.validators import normalize_register_no

logger = logging.getLogger(__name__)
NO_DEPARTMENT = order_print_page.NO_DEPARTMENT  # re-exported: the print page and the tests use this name


def _group_by_department(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    buckets: dict[str, list[Row]] = {}
    for row in rows:
        name = (row.job.department.name or "") if row.job else NO_DEPARTMENT
        buckets.setdefault(name, []).append(row)
    return sorted(buckets.items(), key=lambda item: (item[0] == NO_DEPARTMENT, item[0]))


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


LIST_BATCH = batching.LIST_BATCH  # people per batch in the employee list


@login_required
def employee_list(request: HttpRequest) -> HttpResponse:
    """The employees screen is the staff-list report: this address sends the viewer there, keeping the old filters
    the report also has (department, state, grouping by department)."""
    # A hire from outside the user's scope opens this address instead of the detail page (that would 404): its
    # one-time login is shown here, once, the same way employee_detail shows it.
    pending = request.session.pop(ONE_TIME_LOGIN_KEY, None)
    if isinstance(pending, dict):
        response = render(request, "employees/one_time_login_page.html", {"one_time_login": pending})
        response["Cache-Control"] = "no-store"  # the password must not come back from the Back cache
        return response
    query: dict[str, str] = {}
    if request.GET.get("department", "").isdigit():
        query["department"] = request.GET["department"]
    if request.GET.get("state") in ("upcoming", "left"):
        query["state"] = request.GET["state"]
    if request.GET.get("group") == "1":
        query["group"] = "department"
    url = reverse("reports:report", args=[STAFF_LIST.key])
    return redirect(f"{url}?{urlencode(query)}" if query else url)


@login_required
def today_page(request: HttpRequest) -> HttpResponse:
    """Home page: tiles, the attention box, who is away (counts), upcoming dates (counts), company figures.

    Names of people away or with a birthday are not on the page; they load per click through the fragments."""
    context: dict[str, Any] = today_facts(_user(request), timezone.localdate())
    context["attention_open"] = True
    context.update(_box_context(context["box"]))
    context["attention_count"] = len(context["attention"])
    return render(request, "employees/today.html", context)


@login_required
def company_page(request: HttpRequest) -> HttpResponse:
    """The company figures (headcount, turnover, departments, tenure) on their own page; the Today page links here."""
    user, today = _user(request), timezone.localdate()
    if not user.has_perm("macs.view_employees"):
        raise PermissionDenied
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    company = company_stats.company(user, rows, today)
    if company is None:
        raise PermissionDenied
    return render(request, "employees/company.html", {"today": today, "company": company})


@login_required
@require_GET
def today_away(request: HttpRequest) -> HttpResponse:
    """The names of people away on one day of the Today strip (`?day=YYYY-MM-DD`, inside the 14-day window)."""
    user, today = _user(request), timezone.localdate()
    try:
        day = date.fromisoformat(request.GET.get("day", ""))
    except ValueError:
        raise Http404 from None
    if not today <= day < today + timedelta(days=facts.WINDOW_DAYS):
        raise Http404
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)
    response = render(request, "employees/_today_away.html", {"away": facts.away_on_day(user, rows, day), "day": day})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def today_views(request: HttpRequest) -> HttpResponse:
    """The report setups that say what is coming up, with their counts (empty without reports.view_reports)."""
    from reports.today_tiles import tiles  # loaded per call: it pulls in the report registry, which imports employees

    response = render(request, "employees/_today_views.html", {"tiles": tiles(_user(request))})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def today_upcoming(request: HttpRequest) -> HttpResponse:
    """The birthdays or the work anniversaries in the next 30 days (`?kind=birthday|anniversary`)."""
    user, today = _user(request), timezone.localdate()
    kind = request.GET.get("kind", "")
    if kind not in ("birthday", "anniversary"):
        raise Http404
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)  # the personal-data check reads each person's HR row (own record)
    found = [u for u in facts.upcoming(user, rows, today) if u.kind == kind]
    response = render(request, "employees/_today_upcoming.html", {"upcoming": found, "kind": kind})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def today_hires(request: HttpRequest) -> HttpResponse:
    """The names of people who joined in the last 30 days (the hires line of «Ойрын 30 хоног»)."""
    user, today = _user(request), timezone.localdate()
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)
    response = render(request, "employees/_today_hires.html", {"hires": facts.new_hires(rows, today)})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def attention_toggle(request: HttpRequest) -> HttpResponse:
    """ "Мэдлээ" / "Дахин харуулах" on one Анхаарах item; returns the box."""
    user, today = _user(request), timezone.localdate()
    rows = employee_rows(access.visible_employees(user), today)
    facts.prime_exts(rows)  # one query for every HR row: the attention rules read it per person
    found = attention.items(user, rows, today)
    keys = set(request.POST.getlist("key"))
    picked = [a for a in found if a.key in keys]
    if not picked:
        raise Http404
    for item in picked:
        if request.POST.get("action") == "restore":
            attention.restore(user, item)
        else:  # "dismiss" (one item) or "dismiss_all" (a whole group)
            attention.dismiss(user, item)
    context = _attention_context(user, found)
    box = render_to_string("employees/_attention.html", context, request=request)
    tile = render_to_string("employees/_attention_tile.html", {**context, "oob": True}, request=request)
    return HttpResponse(box + tile)  # the tile sits outside the box: it is swapped out of band


@login_required
@require_GET
def attention_more(request: HttpRequest) -> HttpResponse:
    """The items of one Анхаарах group past the first `GROUP_LIMIT` («Бүгдийг харах»), or all of them with `all=1`."""
    user, today = _user(request), timezone.localdate()
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)  # one query for every HR row: the attention rules read it per person
    shown, _ = attention.split(user, attention.items(user, rows, today))
    kind, urgency = request.GET.get("kind", ""), request.GET.get("urgency", "")
    found = next((g for g in attention.group(shown) if g.kind == kind and str(g.urgency) == urgency), None)
    if found is None:
        raise Http404
    try:
        offset = max(0, int(request.GET.get("offset", "0")))
    except ValueError:
        offset = 0
    context: dict[str, Any] = {"group": found, "rest": found.items[attention.GROUP_LIMIT :], "more": 0}
    if request.GET.get("all") == "1" and not found.dated:  # a missing-data row: its people a page at a time
        page_end = offset + attention.GAP_PAGE
        context.update(
            rest=found.items[offset:page_end],
            more=max(0, len(found.items) - page_end),
            next_offset=page_end,
        )
    response = render(request, "employees/_attention_more.html", context)
    response["Cache-Control"] = "no-store"
    return response


def _attention_context(user: User, found: list[attention.Attention]) -> dict[str, object]:
    return _box_context(attention.box(user, found))


def _box_context(box: attention.Box) -> dict[str, object]:
    """The template keys of the attention box, built from an already worked-out box."""
    return {
        "attention": box.shown,
        "attention_groups": box.groups,
        "attention_tiers": box.tiers,
        "urgent_count": box.tiers.urgent_count,
        "soon_count": box.tiers.soon_count,
        "gap_count": box.tiers.gap_count,
        "attention_hidden": box.hidden,
    }


def _employee_for(request: HttpRequest, pk: int) -> Employee:
    return get_object_or_404(access.visible_employees(_user(request)), pk=pk)


def _employee_form(request: HttpRequest, employee: Employee, data: Any = None, files: Any = None) -> EmployeeForm:
    return page_writes.employee_form(_user(request), employee, data, files)


ORDER_WARNING_KEY = "order_warning"  # session: MACS number clash, shown once on the employee page


def _remember_warning(request: HttpRequest, order: HrOrder | None) -> None:
    """Keep the MACS number-clash note for the next employee page (the pop-up closes with a refresh)."""
    if order is None or not order.number or order.date is None:
        return
    text = orders.legacy_clash_warning(order.number, order.date, order.command_id)
    if text:
        request.session[ORDER_WARNING_KEY] = text


def _refresh_context(request: HttpRequest, employee: Employee) -> dict[str, object]:
    """What _page_refresh.html needs after a personal-tab write, without rebuilding the whole page (UI_RULES §2f)."""
    activity = access.visible_activity(_user(request), employee)
    return {"employee": employee, "today": timezone.localdate(), **activity_context(activity)}


def detail_context(request: HttpRequest, employee: Employee) -> dict[str, object]:
    user = _user(request)
    form, si_form = page_writes.page_form_state(user, employee)
    return {
        **detail_facts(user, employee, timezone.localdate()),
        "order_warning": request.session.pop(ORDER_WARNING_KEY, "") if request.method == "GET" else "",
        "form": form,
        "si_form": si_form,
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
    if request.method != "POST":
        return _hire_form(request, hire_page.build(user, request.GET, None, None))
    page = hire_page.build(user, request.GET, request.POST, request.FILES)
    outcome = hire_page.submit(user, page)
    if outcome.employee is None:  # refused or invalid: the same page again, with the messages on its forms
        return _hire_form(request, page, status=400 if outcome.reason == "refused" else 200)
    if outcome.login is not None:  # the password is shown once, on the employee page
        request.session[ONE_TIME_LOGIN_KEY] = outcome.login
    _remember_warning(request, outcome.hire_order)
    # A limited user may hire outside their scope: that page would 404, so the list opens instead.
    if access.visible_employees(user).filter(pk=outcome.employee.pk).exists():
        url = reverse("employees:detail", args=[outcome.employee.pk])
    else:
        url = reverse("employees:list")
    if request.headers.get("HX-Request"):  # errors swap in place; success opens the new employee's page
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def _hire_form(request: HttpRequest, page: hire_page.HirePage, status: int = 200) -> HttpResponse:
    context = {
        "candidate_id": page.candidate_id,
        "submission_id": page.submission_id,
        "review": page.review,
        "duplicate": page.duplicate,
        "person": page.person,
        "job": page.job,
        "extras": page.extras,
        "allow_salary": page.allow_salary,
        "si": page.si,
        "address": page.address,
        "contact": page.contact,
        "order_form": page.order_form,
        # the photo hint asks for a picture again only when this failed POST carried one
        "photo_sent": bool(request.FILES.get("photo")),
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
    match = access.visible_employees(_user(request)).filter(register_no=value).first() if value else None
    return render(request, "employees/_register_check.html", {"match": match})


# --- Task 10: htmx modals ---
def _done(employee: Employee) -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"  # reload keeps the #tab in the URL, so the same tab stays open
    return response


def _modal(
    request: HttpRequest, title: str, form: object, action: str, hint: str = "", submit_label: str = "Хадгалах"
) -> HttpResponse:
    context = {"title": title, "form": form, "action": action, "hint": hint, "submit_label": submit_label}
    return render(request, "employees/_modal.html", context)


def _require(allowed: bool) -> None:
    if not allowed:
        raise PermissionDenied


ONE_TIME_LOGIN_KEY = "one_time_login"  # session key: {employee, username, password} shown once on the detail page


@login_required
@require_POST
def employee_save(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    employee = _employee_for(request, pk)
    result = page_writes.save_page(user, employee, request.POST, request.FILES)
    if result.ok:
        if request.headers.get("HX-Request"):  # reload in place: no extra history step, the tab (#hash) stays
            response = HttpResponse(status=204)
            response["HX-Refresh"] = "true"
            return response
        url = reverse("employees:detail", args=[pk])
        return HttpResponseRedirect(f"{url}#{result.tab}" if result.tab in TABS else url, status=303)
    context = detail_context(request, employee) | {
        "form": result.form,
        "si_form": result.si_form,
        "tab": result.tab,
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
        # The validation, stale check and write are page_writes.save_section (shared with the API); this view renders.
        result = page_writes.save_section(user, employee, section, request.POST)
        if result.ok:
            employee = Employee.objects.get(pk=pk)
            context = _section_context(
                employee, section, names, None, can_manage=can_manage, with_lists=False, user=user
            )
            context |= {**_refresh_context(request, employee), "oob": True}
            if section == "other":  # its menu entry counts filled fields
                filled, total = sections.other_progress(employee)
                context |= {"menu_sec": section, "menu_count": f"{filled}/{total}"}
            return render(request, template, context)
        form = result.form
        editing = True  # invalid, conflicting or refused: show the section for editing with its errors
    else:
        form = EmployeeForm(employee=Employee.objects.get(pk=pk), user=user)
    context = _section_context(
        employee, section, names, form, editing, can_manage, with_lists=not fields_only, user=user
    )
    return render(request, template, context, status=200)


@login_required
@require_GET
def activity_more(request: HttpRequest, pk: int) -> HttpResponse:
    """The next batch of the «Түүх» drawer, loaded when the pill at its end scrolls into view."""
    employee = _employee_for(request, pk)
    entries = access.visible_activity(_user(request), employee).select_related("by")
    raw = request.GET.get("offset", "")
    offset = int(raw) if raw.isdigit() else 0
    total = entries.count()
    shown = list(entries[offset : offset + ACTIVITY_BATCH])
    before = entries[offset - 1] if 0 < offset <= total else None  # entry above this batch: same day, no heading
    context = {
        "employee": employee,
        "today": timezone.localdate(),
        "activity": shown,
        "prev_day": timezone.localtime(before.at).strftime("%Y-%m-%d") if before else "",
        "activity_next_query": f"offset={offset + ACTIVITY_BATCH}" if total > offset + ACTIVITY_BATCH else "",
    }
    response = render(request, "employees/_activity_entries.html", context)
    response["Cache-Control"] = "no-store"
    return response


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
    form = JobCorrectionForm(request.POST or None, instance=JobRecord.objects.get(pk=record.pk), user=_user(request))
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
@login_required
def event_form(request: HttpRequest, pk: int, type: str) -> HttpResponse:
    employee, user = _employee_for(request, pk), _user(request)
    if request.method == "POST":
        outcome = event_page.submit(user, employee, type, request.POST)
        if outcome.ok:
            _remember_warning(request, outcome.order)
            return _done(employee)
        page = outcome.page
        if not request.POST and page.order_form is not None:
            # The old view bound the order block only to a non-empty POST: an empty POST shows it unbound.
            page.order_form = OrderFieldsForm(None, prefix="order")
    elif request.GET.get("summary"):
        summary = event_page.summary_line(user, employee, type, request.GET)
        return render(request, "employees/_event_summary.html", {"summary": summary})
    else:
        page = event_page.build_page(
            user, employee, type, request.GET, prev_effective=request.GET.get("prev_effective")
        )
    # The htmx attributes need this request's path, so the view adds them. A date error makes the service set the
    # text-box flag; it stays last, as the view always wrote it.
    effective_attrs = page.form.fields["effective"].widget.attrs
    datepicker = effective_attrs.pop("data-datepicker", None)
    effective_attrs.update(
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
    if datepicker is not None:
        effective_attrs["data-datepicker"] = datepicker
    context = {
        "title": page.title,
        "kinds": [
            (reverse("employees:event", args=[employee.pk, value]), label, selected)
            for value, label, selected in page.kinds
        ],
        "form": page.form,
        "prev_effective": page.prev_effective,
        "order_form": page.order_form,
        "action": request.path,
        "summary": page.summary,
        "reload": page.reload,
        "when": page.when,
    }
    return render(request, "employees/_event_form.html", context)


@login_required
def event_cancel(request: HttpRequest, pk: int, event_id: int) -> HttpResponse:
    employee, user = _employee_for(request, pk), _user(request)
    page = event_page.cancel_page(user, employee, event_id)
    form = page.form
    if request.method == "POST" and request.POST:  # an empty POST shows the unbound form, as before
        ok, form = event_page.submit_cancel(user, employee, event_id, request.POST)
        if ok:
            return _done(employee)
    return _modal(request, page.title, form, request.path, page.hint, submit_label="Цуцлах")


# --- Orders (тушаал) ---
def _order_for(request: HttpRequest, pk: int, order_id: int) -> tuple[Employee, HrOrder]:
    employee = _employee_for(request, pk)
    return employee, get_object_or_404(employee.hr_orders, pk=order_id)


@login_required
def order_edit(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    employee, order = _order_for(request, pk, order_id)  # a foreign order is a 404 before the manage right is checked
    user = _user(request)
    if request.method == "POST":
        ok, popup, done = order_popups.submit_edit(user, employee, order, request.POST)
        if ok:
            _remember_warning(request, done)
            return _done(employee)
    else:
        popup = order_popups.edit_popup(user, employee, order)
    return _modal(request, popup.title, popup.form, request.path, popup.hint)


@login_required
def order_upload(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    employee, order = _order_for(request, pk, order_id)
    user = _user(request)
    if request.method == "POST" and (request.POST or request.FILES):  # an empty POST shows the unbound form, as before
        ok, popup = order_popups.submit_upload(user, order, request.FILES.get("file"))
        if ok:
            return _done(employee)
    else:
        popup = order_popups.upload_popup(user, order)
    return _modal(request, popup.title, popup.form, request.path)


# --- On-screen signing (order-signing board): the pop-up, the signing POST, the saved signature pictures ---
SAVED_MISSING = order_signing.SAVED_MISSING  # re-exported: the messages live in the signing service
TEMPLATE_BROKEN = order_signing.TEMPLATE_BROKEN


def _sign_popup(
    request: HttpRequest, employee: Employee, order: HrOrder, errors: list[str], has_saved: bool
) -> HttpResponse:
    context = {
        "employee": employee,
        "order": order,
        "action": request.path,
        "errors": errors,
        "has_saved": has_saved,
    }
    return render(request, "employees/_order_sign.html", context)


@login_required
def order_sign(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """The signing pop-up of a registered order (GET), and the signing itself (POST, mode saved or drawn). The checks
    and the signing are in the signing service (order_signing.signing_state / submit_sign)."""
    employee, order = _order_for(request, pk, order_id)
    user = _user(request)
    if request.method != "POST":
        state = order_signing.signing_state(user, order)
        return _sign_popup(request, employee, order, [], state.has_saved)
    errors = order_signing.submit_sign(
        user, order, request.POST.get("mode", ""), request.POST.get("signature", ""), bool(request.POST.get("remember"))
    )
    if not errors:
        return _done(employee)
    return _sign_popup(request, employee, order, errors, order_signing.saved_signature_png(user) is not None)


@login_required
def order_signing_image(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """The signature picture stamped on a signed order. Anyone who may see the employee may see it (_order_for)."""
    _employee, order = _order_for(request, pk, order_id)
    return order_files.file_response(order_files.signing_image_payload(order))


@login_required
def my_signature_image(request: HttpRequest) -> HttpResponse:
    """The user's own saved signature picture (only ever the requester's own, 404 when none)."""
    return order_files.file_response(order_files.saved_signature_payload(_user(request)))


@login_required
@require_POST
def my_signature_delete(request: HttpRequest) -> HttpResponse:
    """Delete the user's own saved signature. The pop-up posts `next` (its own address) so the answer is the pop-up
    again, now showing the board; without it the page refreshes."""
    order_signing.delete_saved_signature(_user(request))
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


FILE_TYPES = order_files.FILE_TYPES  # the scan's magic bytes now live in the service; kept importable here


def _order_download(request: HttpRequest, pk: int, order_id: int, pdf: bool) -> HttpResponse:
    """The order filled from its Word template, as .docx or .pdf (a draft to print and sign)."""
    employee, order = _order_for(request, pk, order_id)
    payload = order_files.document_payload(_user(request), order, pdf=pdf)
    record_export(request, "download_order", order_files.order_label(order, employee))
    return order_files.file_response(payload)


@login_required
def order_document(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    return _order_download(request, pk, order_id, pdf=False)


@login_required
def order_document_pdf(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    return _order_download(request, pk, order_id, pdf=True)


MAX_ID_DIGITS = print_jobs.MAX_ID_DIGITS  # longer ids cannot be a row id (the database integer overflows)
ORDER_PRINT_LIMIT = print_jobs.ORDER_PRINT_LIMIT  # orders in one printout; a bigger pile is printed in two goes


@login_required
@require_POST
def orders_print_selected(request: HttpRequest) -> FileResponse | HttpResponseBadRequest:
    """The ticked orders of the register as one PDF, one order per page, to print and sign together. Only orders of
    people the user may see; cancelled orders and orders with no usable template are left out. Each order is
    logged like a single download."""
    user = _user(request)
    _require(access.can_manage(user))
    ids = set(print_jobs.parse_ids(request.POST.getlist("ids")))
    try:
        data, printed = print_jobs.render_now(user, ids)
    except print_jobs.NothingToPrint:
        return HttpResponseBadRequest(print_jobs.NOTHING)
    for order in printed:
        record_export(request, "download_order", print_jobs.export_label(order))
    return FileResponse(io.BytesIO(data), filename="tushaal-songoson.pdf", content_type=order_docs.PDF_TYPE)


@login_required
@require_POST
def orders_print_start(request: HttpRequest) -> JsonResponse:
    """Start building the ticked orders' PDF in the background (the register, 11 orders or more); the page keeps
    polling `orders_print_status` and offers `orders_print_file` when it is ready."""
    user = _user(request)
    _require(access.can_manage(user))
    ids = print_jobs.parse_ids(request.POST.getlist("ids"))
    if not ids:
        return JsonResponse({"error": print_jobs.NOTHING}, status=400)
    token = print_jobs.start(user, ids)
    return JsonResponse(
        {
            "token": token,
            "status": reverse("employees:orders_print_status", args=[token]),
            "file": reverse("employees:orders_print_file", args=[token]),
        }
    )


@login_required
@require_GET
def orders_print_status(request: HttpRequest, token: str) -> JsonResponse:
    user = _user(request)
    _require(access.can_manage(user))
    info = print_jobs.status(user, token)
    if info is None:
        raise Http404
    return JsonResponse(info)


@login_required
@require_GET
def orders_print_file(request: HttpRequest, token: str) -> FileResponse:
    user = _user(request)
    _require(access.can_manage(user))
    path = print_jobs.pdf_path(user, token)
    if path is None:
        raise Http404
    return FileResponse(path.open("rb"), filename="tushaal-songoson.pdf", content_type=order_docs.PDF_TYPE)


@login_required
def order_detail(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """Everything about one order in a pop-up (opened from the register): facts, links, history, actions."""
    employee, order = _order_for(request, pk, order_id)
    return render(request, "employees/_order_detail.html", order_detail_page.build(_user(request), employee, order))


@login_required
def order_cancel(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """Cancel one registered (not yet signed) order that has no change behind it (the hire order) with a reason.
    A change's order is cancelled together with the change (`event_cancel`)."""
    employee, order = _order_for(request, pk, order_id)
    user = _user(request)
    if request.method == "POST" and request.POST:  # an empty POST shows the unbound form, as before
        ok, popup = order_popups.submit_cancel(user, employee, order, request.POST)
        if ok:
            return _done(employee)
    else:
        popup = order_popups.cancel_popup(user, employee, order)
    return _modal(request, popup.title, popup.form, request.path, popup.hint, submit_label=order_popups.CANCEL_LABEL)


@login_required
def order_history(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """Who created, registered, edited, signed or cancelled this order, and when (read-only pop-up)."""
    employee, order = _order_for(request, pk, order_id)
    entries = order.activity.select_related("by").order_by("-at", "-id")
    return render(request, "employees/_order_history.html", {"employee": employee, "order": order, "entries": entries})


@login_required
def order_file(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    employee, order = _order_for(request, pk, order_id)  # visible employees only: anyone else gets 404
    payload = order_files.scan_payload(_user(request), order)  # hire and rehire scans need macs.view_salary (OQ-080)
    record_export(request, "download_order", "Гарын үсэгтэй файл: " + order_files.order_label(order, employee))
    return order_files.file_response(payload)


def _register_context(request: HttpRequest, *, batched: bool = False) -> dict[str, Any]:
    """The register page's filters and rows: one batch (`batched`, the page itself) or every row (print)."""
    query = order_register_page.parse_query(request.GET)
    today = timezone.localdate()
    options = order_register_page.filter_options(today)
    user = _user(request)
    filters: dict[str, Any] = {
        "year": query.year,
        "order_type": query.order_type,
        "department_id": query.department,
        "state": query.state or None,
        "today": today,
        "q": query.q,
        "sort": query.sort,
    }
    paging: dict[str, Any] = {}
    if batched:
        batch = batching.paged(
            request, lambda offset, size: order_register.register_page(user, **filters, offset=offset, size=size)
        )
        rows = batch.shown
        paging = {"offset": batch.offset, "next_query": batch.next_query}
    else:
        rows = order_register.register_rows(user, **filters)
    return {
        **paging,
        "can_manage": access.can_manage(user),
        "rows": rows,
        "q": query.q,
        "sort": query.sort,
        "sort_heads": order_register.sort_heads(query.sort),
        "year": query.year,
        "order_type": query.order_type,
        "department": query.department,
        "state": query.state,
        "types": options.types,
        "states": options.states,
        "departments": options.departments,
        "years": options.years,
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
    context = _register_context(request, batched=True)
    is_partial = bool(request.headers.get("HX-Request")) and not request.headers.get("HX-History-Restore-Request")
    if not is_partial:
        template = "employees/orders.html"
        context["background_from"] = print_jobs.BACKGROUND_FROM
    else:
        more_of_it = bool(context["offset"])  # a later batch adds rows to the table; the first replaces it
        template = "employees/_order_register_items.html" if more_of_it else "employees/_order_register_rows.html"
    return render(request, template, context)


@login_required
def orders_print(request: HttpRequest) -> HttpResponse:
    context = _register_context(request)
    query = order_register_page.parse_query(request.GET)
    options = order_register_page.filter_options(timezone.localdate())
    context["groups"] = [(group.department, group.rows) for group in order_print_page.build_groups(context["rows"])]
    context["company"] = order_print_page.company_name()
    record_export(
        request, "print_page", "Тушаалын бүртгэл", filters=_register_label(query, options), rows=len(context["rows"])
    )
    return render(request, "employees/orders_print.html", context)


def _register_label(query: order_register_page.RegisterQuery, options: order_register_page.FilterOptions) -> str:
    return order_print_page.register_label(query, options)


# --- Ctrl+K command palette ---
@login_required
@require_GET
def palette_search(request: HttpRequest) -> HttpResponse:
    """The palette's answers for the typed query: an HTML fragment the palette script swaps in. Never cached,
    because the answer depends on who asks (what they may open or see)."""
    user = _user(request)
    q = request.GET.get("q", "")
    result = palette_answer.answer(
        user,
        q=q,
        more=request.GET.get("more") == "1",  # «show all»: up to PEOPLE_MORE_LIMIT people instead of PEOPLE_LIMIT
        recent_raw=request.GET.get("recent", ""),  # the browser's remembered items; the service re-checks each one
        from_path=request.GET.get("from", ""),  # the page the palette opened on
        today=timezone.localdate(),
    )
    # The assistant's «Асуух» row. Local import: the assistant app imports employees.palette.
    from assistant.providers import is_enabled
    from assistant.services import QUESTION_LIMIT, looks_like_question

    ask_on = is_enabled() and bool(q.strip())
    response = render(
        request,
        "employees/_palette_results.html",
        {
            "ask_on": ask_on,
            "ask_first": ask_on and looks_like_question(q),  # a question: the row goes first and Enter asks it
            "ask_q": q[:QUESTION_LIMIT],
            "recent": result.recent,
            "current": result.current,
            "current_actions": result.current_actions,
            "screens": result.screens,
            "fixed_urls": result.fixed_urls,  # only these pages get a data-palette-ref (what can be recalled)
            "actions": result.actions,
            "people": result.people,
            "people_total": result.people_total,  # every match; the header shows «shown / total» when some are left out
            "people_more": result.people_more,  # offer «show all»
            "words": result.words,  # highlighted in the rows; empty for the empty box
            "orders": result.orders,
            "person": result.single,
            "person_actions": result.person_actions,
        },
    )
    response["Cache-Control"] = "no-store"
    return response
