import calendar as pycal
from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from employees import access as employee_access
from employees.models import Employee, JobStatus
from employees.services import history
from employees.services.macs_writes import ListEntryInUse
from macs.models import LeaveAssign, LeaveTypeRow

from leave import access
from leave.forms import (
    AdjustForm,
    CancelForm,
    CarryOverForm,
    GrantForm,
    LeaveForm,
    LeaveTypeForm,
    initial_dates,
    loaded_from_post,
)
from leave.models import LeaveSettings, LeaveTypeExt, type_ext
from leave.services import calendar, entitlement, ledger, records, rows, writes
from leave.services.rows import LeaveRow

MAX_INT = 2_147_483_647  # production ids are 32-bit integers


def today() -> date:
    return timezone.localdate()


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _require(allowed: bool) -> None:
    if not allowed:
        raise PermissionDenied


def _done() -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


def _int(value: str | None) -> int | None:
    """A non-negative 32-bit id from user input, or None (never raises)."""
    if not value or len(value) > 12 or not value.isdecimal():
        return None
    number = int(value)
    return number if number <= MAX_INT else None


def _iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _not_configured() -> str:
    return "" if ledger.annual_configured() else ledger.NOT_CONFIGURED


def _visible_assign(user: User, pk: int) -> LeaveAssign | None:
    """A production leave row whose employee the user may see, or None."""
    visible = employee_access.visible_employees(user).values("pk")
    return LeaveAssign.objects.filter(pk=pk, employee_id__in=visible).first()


def _own_leave(user: User, pk: int) -> tuple[LeaveAssign, LeaveRow]:
    a = _visible_assign(user, pk)
    if a is None:
        raise Http404
    try:
        return a, rows.leave(a.pk)
    except LeaveAssign.DoesNotExist as exc:  # unusable row (missing employee or type): not shown
        raise Http404 from exc


@login_required
def leave_list(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_view(user))
    f = request.GET
    people = employee_access.visible_employees(user)
    q = f.get("q", "").strip()
    if (employee_id := _int(f.get("employee"))) is not None:  # link from the employee page
        people = people.filter(pk=employee_id)
        person = people.first()
        q = person.full_name if person else q
    else:
        for word in q.split():  # every word must match a name part or the code
            people = people.filter(
                Q(family_name__icontains=word) | Q(given_name__icontains=word) | Q(code__icontains=word)
            )
    by_id = {e.pk: e for e in people}
    found = rows.leaves(employee_ids=list(by_id), start=_iso(f.get("from", "")), end=_iso(f.get("to", "")))
    if (type_id := _int(f.get("type"))) is not None:
        found = [lv for lv in found if lv.leave_type.pk == type_id]
    status = f.get("status", "recorded")
    if status != "all":
        found = [lv for lv in found if lv.state.name == status.upper()]
    t = today()
    context = {
        "items": [(lv, by_id[lv.employee_id]) for lv in found],
        "types": LeaveTypeRow.objects.all(),
        "filters": f,
        "q": q,
        "can_record": access.can_record(user),
        "today": t,
        "not_configured": _not_configured(),
        "missing_holidays": [
            y for y in (t.year, t.year + 1) if (y == t.year or t.month == 12) and not calendar.has_holidays(y)
        ],
    }
    template = "leave/_rows.html" if request.headers.get("HX-Request") else "leave/list.html"
    return render(request, template, context)


def _leave_form(
    request: HttpRequest,
    form: LeaveForm,
    *,
    title: str,
    leave_id: int | None = None,
    loaded: writes.AssignSnapshot | None = None,
    error: str = "",
) -> HttpResponse:
    context = {
        "form": form,
        "action": request.path,
        "title": title,
        "error": error,
        "leave_id": leave_id or "",
        "loaded": loaded,
        "not_configured": _not_configured(),
    }
    return render(request, "leave/_form.html", context)


@login_required
def leave_add(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    employees = employee_access.visible_employees(user)
    if request.method != "POST":
        initial = {**initial_dates(today()), "employee": request.GET.get("employee")}
        return _leave_form(request, LeaveForm(initial=initial, employees=employees), title="Чөлөө бүртгэх")
    form = LeaveForm(request.POST, employees=employees)
    if not form.is_valid():
        return _leave_form(request, form, title="Чөлөө бүртгэх")
    try:
        records.record(form.draft(), user, today())
    except records.LeaveError as e:
        return _leave_form(request, form, title="Чөлөө бүртгэх", error=str(e))
    return _done()


@login_required
def leave_edit(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    a, row = _own_leave(user, pk)
    employees = employee_access.visible_employees(user)
    title = "Чөлөө засах"
    if request.method != "POST":
        initial = {
            "employee": a.employee_id,
            "leave_type": a.leave_type_id,
            "start_date": a.date1,
            "end_date": a.date2,
            "note": a.comment or "",
            "override_reason": row.override_reason,
        }
        form = LeaveForm(initial=initial, employees=employees, current_type=a.leave_type)
        return _leave_form(request, form, title=title, leave_id=a.pk, loaded=writes.snapshot(a))
    loaded = loaded_from_post(request.POST)
    form = LeaveForm(request.POST, employees=employees, current_type=a.leave_type)
    if loaded is None:  # the hidden row values are missing: show the current row so the next save can work
        return _leave_form(request, form, title=title, leave_id=a.pk, loaded=writes.snapshot(a), error=writes.STALE)
    if not form.is_valid():
        return _leave_form(request, form, title=title, leave_id=a.pk, loaded=loaded)
    try:
        records.update(a, form.draft(leave_id=a.pk, loaded=loaded), user, today())
    except records.LeaveError as e:
        return _leave_form(request, form, title=title, leave_id=a.pk, loaded=loaded, error=str(e))
    return _done()


@login_required
@require_POST
def leave_check(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    form = LeaveForm(request.POST, employees=employee_access.visible_employees(user))
    if not form.is_valid():
        return HttpResponse("")
    leave_id = _int(request.POST.get("leave_id"))
    leave = _visible_assign(user, leave_id) if leave_id is not None else None
    draft = form.draft(leave_id=leave.pk if leave else None)
    if leave is not None:  # same as records.update: the leave's own employee, not the posted one
        draft.employee = leave.employee
    return render(request, "leave/_check.html", {"check": records.check(draft, today())})


@login_required
def leave_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    a, row = _own_leave(user, pk)
    loaded = writes.snapshot(a)
    form = CancelForm(request.POST or None)
    error = ""
    if request.method == "POST":
        posted = loaded_from_post(request.POST)
        if posted is None:
            error = writes.STALE
        else:
            loaded = posted
            if form.is_valid():
                try:
                    records.cancel(a, posted, form.cleaned_data["reason"], user, today())
                    return _done()
                except records.LeaveError as e:
                    error = str(e)
    context = {
        "form": form,
        "row": row,
        "loaded": loaded,
        "error": error,
        "mistake": loaded.date1 <= today(),  # same rule as records.cancel
    }
    return render(request, "leave/_cancel.html", context)


def _suggestion(employee: Employee, start: date | None) -> str:
    """The law's annual days for a grant starting on `start`, as a hint for the manual grant form."""
    if start is None or entitlement.employment_start(employee) is None:
        return ""
    try:
        ent = entitlement.entitled(employee, start)
    except LookupError:  # no law rule row exists
        return ""
    return f"Хуулийн дагуу: {ent.days} хоног ({ent.breakdown})"


@login_required
def grant_add(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    employee = get_object_or_404(employee_access.visible_employees(user), pk=pk)
    form = GrantForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            ledger.manual_grant(employee, d["start"], d["end"], d["days"], d["reason"], user)
            return _done()
        except ledger.LedgerError as e:
            error = str(e)
    start = form.cleaned_data.get("start") if form.is_bound else None
    context = {
        "form": form,
        "title": "Эрх нэмэх",
        "action": request.path,
        "error": error,
        "hint": _suggestion(employee, start),
    }
    return render(request, "leave/_grant_form.html", context)


def _grant_view(request: HttpRequest, pk: int, start: str, end: str, carry: bool) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    employee = get_object_or_404(employee_access.visible_employees(user), pk=pk)
    period_start, period_end = _iso(start), _iso(end)
    if period_start is None or period_end is None:
        raise Http404
    form = (CarryOverForm if carry else AdjustForm)(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            if carry:
                ledger.carry_over(employee, period_start, period_end, d["days"], d["reason"], user)
            else:
                ledger.adjust(employee, period_start, period_end, d["days"], d["reason"], user)
            return _done()
        except ledger.LedgerError as e:
            error = str(e)
    title = "Дараа жил рүү шилжүүлэх" if carry else "Амралтын эрх засах"
    context = {
        "form": form,
        "title": f"{title} ({period_start} – {period_end})",
        "action": request.path,
        "error": error,
    }
    return render(request, "leave/_grant_form.html", context)


@login_required
def grant_adjust(request: HttpRequest, pk: int, start: str, end: str) -> HttpResponse:
    return _grant_view(request, pk, start, end, carry=False)


@login_required
def grant_carry(request: HttpRequest, pk: int, start: str, end: str) -> HttpResponse:
    return _grant_view(request, pk, start, end, carry=True)


@dataclass
class Cell:
    day: date
    off: bool
    leave: LeaveRow | None
    color: str = ""


MIN_YEAR, MAX_YEAR = 1900, 2100


def _month(value: str | None, fallback: date) -> date:
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        if not MIN_YEAR <= y <= MAX_YEAR:
            raise ValueError
        return date(y, m, 1)
    except ValueError:
        return fallback.replace(day=1)


def _color(lv: LeaveRow) -> str:
    """Annual leave is violet; every other counted leave is amber (one colour per kind the screen can tell apart)."""
    return "bg-violet-200" if lv.type_ext.uses_annual_balance else "bg-amber-200"


@login_required
def team_calendar(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_view(user))
    first = _month(request.GET.get("month"), today())
    last = first.replace(day=pycal.monthrange(first.year, first.month)[1])
    days = [first.replace(day=n) for n in range(1, last.day + 1)]
    holidays = calendar.holidays_between(first, last)
    people = list(employee_access.visible_employees(user))
    counted = [lv for lv in rows.leaves(employee_ids=[e.pk for e in people], start=first, end=last) if lv.counts]
    lines = []
    for e in people:
        jobs = [history.job_on(e, first), history.job_on(e, last)]
        if all(j is None or j.status == JobStatus.LEFT for j in jobs):
            continue
        mine = [lv for lv in counted if lv.employee_id == e.pk]
        cells = []
        for d in days:
            hit = next((lv for lv in mine if lv.start <= d <= lv.end), None)
            off = not calendar.is_working_day(d, holidays)
            color = _color(hit) if hit and not off else ""
            cells.append(Cell(d, off, hit if not off else None, color))
        lines.append((e, cells))
    prev_m = (first - timedelta(days=1)).strftime("%Y-%m") if first.year > MIN_YEAR else ""
    next_m = (last + timedelta(days=1)).strftime("%Y-%m") if last.year < MAX_YEAR else ""
    return render(
        request,
        "leave/calendar.html",
        {
            "first": first,
            "days": days,
            "lines": lines,
            "holidays": holidays,
            "prev": prev_m,
            "next": next_m,
            "this_month": today().strftime("%Y-%m") if first != today().replace(day=1) else "",
            "not_configured": _not_configured(),
        },
    )


def _add_holiday(year: int, raw_date: str, raw_name: str) -> str:
    """Set one date's holiday name. Returns the error text, or "" when saved."""
    name = raw_name.strip()
    try:
        day = date.fromisoformat(raw_date)
    except ValueError:
        return "Огноо буруу эсвэл нэр хоосон байна."
    if not name:
        return "Огноо буруу эсвэл нэр хоосон байна."
    if day.year != year:
        return "Огноо сонгосон жилийнх байх ёстой."
    if len(name) > 100:
        return "Нэр 100 тэмдэгтээс урт байж болохгүй."
    names = calendar.holiday_names(year)
    names[day] = name
    writes.set_holiday_dates(year, names)
    return ""


def _delete_holiday(year: int, raw_date: str) -> None:
    try:
        day = date.fromisoformat(raw_date)
    except ValueError:
        return
    names = calendar.holiday_names(year)
    if names.pop(day, None) is not None:
        writes.set_holiday_dates(year, names)


@login_required
def holidays(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    year = _int(request.GET.get("year"))
    if year is None or not MIN_YEAR <= year <= MAX_YEAR:
        year = today().year
    error = ""
    if request.method == "POST":
        before = calendar.holiday_names(year)
        action = request.POST.get("action")
        if action == "prefill":
            calendar.prefill_year(year)
        elif action == "add":
            error = _add_holiday(year, request.POST.get("date", ""), request.POST.get("name", ""))
        elif action == "delete":
            _delete_holiday(year, request.POST.get("date", ""))
        after = calendar.holiday_names(year)
        changed = {d for d in before.keys() | after.keys() if before.get(d) != after.get(d)}
        writes.recount_assigns(changed, user)  # Info HR rows only; old-program rows keep their days
        if not error:
            return redirect(f"{request.path}?year={year}")
    return render(
        request,
        "leave/holidays.html",
        {
            "year": year,
            "holidays": sorted(calendar.holiday_names(year).items()),
            "error": error,
            "fixed_count": len(calendar.FIXED_HOLIDAYS),
        },
    )


def _type_rows() -> list[tuple[LeaveTypeRow, LeaveTypeExt]]:
    found = [(row, type_ext(row)) for row in LeaveTypeRow.objects.all()]
    return sorted(found, key=lambda pair: (pair[1].order, pair[0].name))


@login_required
def leave_settings(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    setting = LeaveSettings.get()
    if request.method == "POST":
        setting.auto_annual_grant = request.POST.get("auto_annual_grant", "") in {"on", "1", "true", "True"}
        setting.save(update_fields=["auto_annual_grant"])
        return redirect("leave:settings")
    context = {"types": _type_rows(), "auto": setting.auto_annual_grant}
    return render(request, "leave/settings.html", context)


def _type_initial(row: LeaveTypeRow) -> dict[str, object]:
    ext = type_ext(row)
    return {
        "name": row.name,
        "is_paid": ext.is_paid,
        "uses_annual_balance": ext.uses_annual_balance,
        "is_active": ext.is_active,
        "order": ext.order,
    }


def _type_modal(
    request: HttpRequest, form: LeaveTypeForm, *, row: LeaveTypeRow | None, error: str = ""
) -> HttpResponse:
    if row is None:
        action, title = reverse("leave:type_add"), "Чөлөөний төрөл нэмэх"
    else:
        action, title = reverse("leave:type_edit", args=[row.pk]), "Чөлөөний төрөл засах"
    context = {"form": form, "row": row, "action": action, "title": title, "error": error}
    return render(request, "leave/_type_form.html", context)


def _ext_values(d: dict[str, object]) -> dict[str, object]:
    return {
        "is_paid": d["is_paid"],
        "uses_annual_balance": d["uses_annual_balance"],
        "is_active": d["is_active"],
        "order": d["order"],
    }


@login_required
def leave_type_add(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    if request.method != "POST":
        return _type_modal(request, LeaveTypeForm(initial={"is_active": True, "order": 0}), row=None)
    form = LeaveTypeForm(request.POST)
    if not form.is_valid():
        return _type_modal(request, form, row=None)
    writes.save_leave_type(form.cleaned_data["name"], _ext_values(form.cleaned_data))
    return _done()


@login_required
def leave_type_edit(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    row = get_object_or_404(LeaveTypeRow, pk=pk)
    if request.method != "POST":
        return _type_modal(request, LeaveTypeForm(initial=_type_initial(row)), row=row)
    form = LeaveTypeForm(request.POST)
    if not form.is_valid():
        return _type_modal(request, form, row=row)
    writes.save_leave_type(form.cleaned_data["name"], _ext_values(form.cleaned_data), row=row)
    return _done()


@login_required
@require_POST
def leave_type_delete(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    row = get_object_or_404(LeaveTypeRow, pk=pk)
    try:
        writes.delete_leave_type(row)
    except ListEntryInUse as exc:
        return _type_modal(request, LeaveTypeForm(initial=_type_initial(row)), row=row, error=str(exc))
    return _done()
