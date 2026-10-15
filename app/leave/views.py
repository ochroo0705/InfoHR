import calendar as pycal
from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from employees import access as employee_access
from employees.models import JobStatus
from employees.services import history

from leave import access
from leave.forms import AdjustForm, CancelForm, CarryOverForm, LeaveForm, initial_dates
from leave.models import Holiday, Leave, LeaveStatus, LeaveType
from leave.services import calendar, ledger, records


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
    """A non-negative id from user input, or None (never raises)."""
    if not value or len(value) > 12 or not value.isdecimal():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _visible_leaves(user: User) -> QuerySet[Leave]:
    return Leave.objects.filter(employee__in=employee_access.visible_employees(user)).select_related(
        "employee", "leave_type"
    )


@login_required
def leave_list(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_view(user))
    qs = _visible_leaves(user)
    f = request.GET
    if (type_id := _int(f.get("type"))) is not None:
        qs = qs.filter(leave_type__pk=type_id)
    q = f.get("q", "").strip()
    if (employee_id := _int(f.get("employee"))) is not None:  # link from the employee page
        qs = qs.filter(employee__pk=employee_id)
        person = employee_access.visible_employees(user).filter(pk=employee_id).first()
        q = person.full_name if person else q
    else:
        for word in q.split():  # every word must match a name part or the code
            qs = qs.filter(
                Q(employee__family_name__icontains=word)
                | Q(employee__given_name__icontains=word)
                | Q(employee__code__icontains=word)
            )
    if f.get("status", "recorded") != "all":
        qs = qs.filter(status=f.get("status", LeaveStatus.RECORDED))
    if (d_from := _iso(f.get("from", ""))) is not None:
        qs = qs.filter(end_date__gte=d_from)
    if (d_to := _iso(f.get("to", ""))) is not None:
        qs = qs.filter(start_date__lte=d_to)
    t = today()
    context = {
        "leaves": qs,
        "types": LeaveType.objects.all(),
        "filters": f,
        "q": q,
        "can_record": access.can_record(user),
        "today": t,
        "missing_holidays": [
            y for y in (t.year, t.year + 1) if (y == t.year or t.month == 12) and not calendar.has_holidays(y)
        ],
    }
    template = "leave/_rows.html" if request.headers.get("HX-Request") else "leave/list.html"
    return render(request, template, context)


def _form_response(
    request: HttpRequest, form: LeaveForm, action: str, title: str, leave_id: int | None, error: str = ""
) -> HttpResponse:
    context = {"form": form, "action": action, "title": title, "error": error, "leave_id": leave_id or ""}
    return render(request, "leave/_form.html", context)


def _save(request: HttpRequest, leave: Leave | None) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    employees = employee_access.visible_employees(user)
    action = request.path
    title = "Чөлөө засах" if leave else "Чөлөө бүртгэх"
    leave_id = leave.pk if leave else None
    if request.method != "POST":
        if leave:
            fields = ("employee", "leave_type", "start_date", "end_date", "start_half", "end_half", "note")
            initial = {k: getattr(leave, k) for k in (*fields, "override_reason")}
        else:
            initial = {**initial_dates(today()), "employee": request.GET.get("employee")}
        return _form_response(
            request,
            LeaveForm(initial=initial, employees=employees, current_type=leave.leave_type if leave else None),
            action,
            title,
            leave_id,
        )
    form = LeaveForm(request.POST, employees=employees, current_type=leave.leave_type if leave else None)
    if not form.is_valid():
        return _form_response(request, form, action, title, leave_id)
    try:
        if leave:
            records.update(leave, form.draft(leave.pk), user, today())
        else:
            records.record(form.draft(), user, today())
    except records.LeaveError as e:
        return _form_response(request, form, action, title, leave_id, str(e))
    return _done()


@login_required
def leave_add(request: HttpRequest) -> HttpResponse:
    return _save(request, None)


@login_required
def leave_edit(request: HttpRequest, pk: int) -> HttpResponse:
    _require(access.can_record(_user(request)))
    leave = get_object_or_404(_visible_leaves(_user(request)), pk=pk)
    return _save(request, leave)


@login_required
@require_POST
def leave_check(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    form = LeaveForm(request.POST, employees=employee_access.visible_employees(user))
    if not form.is_valid():
        return HttpResponse("")
    leave_id = _int(request.POST.get("leave_id"))
    leave = _visible_leaves(user).filter(pk=leave_id).first() if leave_id is not None else None
    draft = form.draft(leave.pk if leave else None)
    if leave is not None:  # same as records.update: the leave's own employee, not the posted one
        draft.employee = leave.employee
    return render(request, "leave/_check.html", {"check": records.check(draft, today())})


@login_required
def leave_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    leave = get_object_or_404(_visible_leaves(user), pk=pk)
    form = CancelForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        try:
            records.cancel(leave, form.cleaned_data["reason"], user, today())
            return _done()
        except records.LeaveError as e:
            error = str(e)
    context = {"form": form, "leave": leave, "error": error, "mistake": leave.started(today())}
    return render(request, "leave/_cancel.html", context)


def _grant_view(request: HttpRequest, pk: int, year: str, carry: bool) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    employee = get_object_or_404(employee_access.visible_employees(user), pk=pk)
    year_start = _iso(year)
    if year_start is None:
        raise Http404
    form = (CarryOverForm if carry else AdjustForm)(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        try:
            if carry:
                ledger.carry_over(employee, year_start, form.cleaned_data["days"], form.cleaned_data["reason"], user)
            else:
                ledger.adjust(employee, year_start, form.cleaned_data["days"], form.cleaned_data["reason"], user)
            return _done()
        except ledger.LedgerError as e:
            error = str(e)
    title = "Дараа жил рүү шилжүүлэх" if carry else "Амралтын эрх засах"
    context = {"form": form, "title": f"{title} ({year})", "action": request.path, "error": error}
    return render(request, "leave/_grant_form.html", context)


@login_required
def grant_adjust(request: HttpRequest, pk: int, year: str) -> HttpResponse:
    return _grant_view(request, pk, year, carry=False)


@login_required
def grant_carry(request: HttpRequest, pk: int, year: str) -> HttpResponse:
    return _grant_view(request, pk, year, carry=True)


COLORS = {"annual": "bg-violet-200", "sick": "bg-rose-200", "unpaid": "bg-slate-300", "personal": "bg-emerald-200"}


@dataclass
class Cell:
    day: date
    off: bool
    leave: Leave | None
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


@login_required
def team_calendar(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_view(user))
    first = _month(request.GET.get("month"), today())
    last = first.replace(day=pycal.monthrange(first.year, first.month)[1])
    days = [first.replace(day=n) for n in range(1, last.day + 1)]
    holidays = calendar.holidays_between(first, last)
    leaves = list(_visible_leaves(user).filter(status=LeaveStatus.RECORDED, start_date__lte=last, end_date__gte=first))
    rows = []
    for e in employee_access.visible_employees(user):
        jobs = [history.job_on(e, first), history.job_on(e, last)]
        if all(j is None or j.status == JobStatus.LEFT for j in jobs):
            continue
        mine = [lv for lv in leaves if lv.employee_id == e.pk]
        cells = []
        for d in days:
            hit = next((lv for lv in mine if lv.start_date <= d <= lv.end_date), None)
            off = not calendar.is_working_day(d, holidays)
            color = COLORS.get(hit.leave_type.code, "bg-amber-200") if hit and not off else ""
            cells.append(Cell(d, off, hit if not off else None, color))
        rows.append((e, cells))
    prev_m = (first - timedelta(days=1)).strftime("%Y-%m") if first.year > MIN_YEAR else ""
    next_m = (last + timedelta(days=1)).strftime("%Y-%m") if last.year < MAX_YEAR else ""
    return render(
        request,
        "leave/calendar.html",
        {
            "first": first,
            "days": days,
            "rows": rows,
            "holidays": holidays,
            "prev": prev_m,
            "next": next_m,
            "this_month": today().strftime("%Y-%m") if first != today().replace(day=1) else "",
            "types": LeaveType.objects.filter(is_active=True),
        },
    )


@login_required
def holidays(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    year = _int(request.GET.get("year"))
    if year is None or not MIN_YEAR <= year <= MAX_YEAR:
        year = today().year
    error = ""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "prefill":
            calendar.prefill_year(year)
            records.recount({date(year, m, d) for m, d, _ in calendar.FIXED_HOLIDAYS}, user)
        elif action == "add":
            try:
                day = date.fromisoformat(request.POST.get("date", ""))
                name = request.POST.get("name", "").strip()
                if not name:
                    raise ValueError
                Holiday.objects.update_or_create(date=day, defaults={"name": name})
                records.recount({day}, user)
            except ValueError:
                error = "Огноо буруу эсвэл нэр хоосон байна."
        elif action == "delete":
            if (pk := _int(request.POST.get("id"))) is not None:
                gone = set(Holiday.objects.filter(pk=pk).values_list("date", flat=True))
                Holiday.objects.filter(pk=pk).delete()
                records.recount(gone, user)
        if not error:
            return redirect(f"{request.path}?year={year}")
    return render(
        request,
        "leave/holidays.html",
        {
            "year": year,
            "holidays": Holiday.objects.filter(date__year=year),
            "error": error,
            "fixed_count": len(calendar.FIXED_HOLIDAYS),
        },
    )
