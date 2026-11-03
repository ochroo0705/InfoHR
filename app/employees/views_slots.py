"""The position-slot screen «Орон тооны төлөвлөгөө»: the budget table `nazg` per year, with the people using each row.

Only holders of `employees.manage_position_slots` open it (403 for others). The rules (counting, one row per key,
the log) live in `employees.services.slots`; this module only draws the pages and the pop-up forms.
"""

from datetime import date
from typing import Any, cast

from accounts.models import User
from config import batching
from django import forms
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from macs.models import Branch, NazgRow, Position

from employees.forms import StyledForm
from employees.models import CompanySettings
from employees.services import slots
from employees.slot_kind import MAIN, TEMPORARY

MIN_YEAR, MAX_YEAR = 2000, 2100
KIND_CHOICES = [(MAIN, slots.KIND_LABELS[MAIN]), (TEMPORARY, slots.KIND_LABELS[TEMPORARY])]

manage_slots = permission_required("employees.manage_position_slots", raise_exception=True)


def _year_param(raw: str | None, default: int) -> int:
    """A year from the query string; anything that is not a four-digit year in range is the default."""
    if raw and len(raw) == 4 and raw.isdecimal() and MIN_YEAR <= int(raw) <= MAX_YEAR:
        return int(raw)
    return default


def _done() -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


class SlotForm(StyledForm):
    position = forms.ModelChoiceField(Position.objects.order_by("name"), label="Албан тушаал")
    branch = forms.ModelChoiceField(Branch.objects.order_by("name"), label="Салбар")
    kind = forms.ChoiceField(choices=KIND_CHOICES, label="Төрөл")
    year = forms.IntegerField(label="Он", min_value=MIN_YEAR, max_value=MAX_YEAR)
    qty = forms.IntegerField(label="Орон тоо", min_value=0, max_value=100000)

    def __init__(self, *args: Any, row: NazgRow | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.row = row

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if self.errors:
            return data
        key = {k: data[k] for k in ("position", "branch", "kind", "year")}
        holder = NazgRow.objects.filter(**key).first()
        if holder is not None and (self.row is None or holder.pk != self.row.pk):
            self.add_error(None, _exists_message(holder))
        return data


def _exists_message(holder: NazgRow) -> str:
    return (
        f"Ийм мөр аль хэдийн байна ({cast(Position, holder.position).name}, {cast(Branch, holder.branch).name}, "
        f"{slots.KIND_LABELS.get(holder.kind, holder.kind)}, {holder.year} он: орон тоо {holder.qty}). "
        "Шинэ мөр нэмэхгүй, жагсаалтаас тэр мөрийг нээж засна уу."
    )


def _modal(request: HttpRequest, form: SlotForm, row: NazgRow | None) -> HttpResponse:
    context = {
        "form": form,
        "title": "Орон тоо засах" if row else "Орон тоо нэмэх",
        "action": request.path,
        "row": row,
        "delete_url": reverse("employees:slot_delete", args=[row.pk]) if row else "",
        "hint": "Нэг албан тушаал, салбар, төрөл, оны хувьд нэг мөр байна.",
    }
    return render(request, "employees/_slot_form.html", context)


def _initial(row: NazgRow) -> dict[str, Any]:
    return {"position": row.position_id, "branch": row.branch_id, "kind": row.kind, "year": row.year, "qty": row.qty}


def _used_on(year: int) -> date:
    """The day the screen counts people on: today for the current year, else the year's first day (so the people who
    work at any time in that year are counted, as the hire check counts people who start later in the year)."""
    today = timezone.localdate()
    return today if year == today.year else date(year, 1, 1)


@login_required
@manage_slots
@require_GET
def slot_list(request: HttpRequest) -> HttpResponse:
    this_year = timezone.localdate().year
    year = _year_param(request.GET.get("year"), this_year)
    rows = list(
        NazgRow.objects.filter(year=year)
        .select_related("position", "branch")
        .order_by("position__name", "branch__name", "kind", "pk")
    )
    used = slots.used_by_key(year, _used_on(year))
    lines: list[dict[str, Any]] = []
    for row in rows:
        count = used.get((row.position_id, row.branch_id, row.kind), 0)
        lines.append({"row": row, "posts": row.qty, "used": count, "free": row.qty - count})
    totals = {
        "posts": sum(line["posts"] for line in lines),
        "used": sum(line["used"] for line in lines),
        "free": sum(line["free"] for line in lines),
    }
    batch = batching.window(request, lines)
    context = {
        "year": year,
        "rows": batch.shown,
        "offset": batch.offset,
        "next_query": batch.next_query,
        "totals": totals,
        "enforce": CompanySettings.get().enforce_position_slots,
        "settings_url": reverse("admin:employees_companysettings_changelist"),
    }
    template = "employees/_slot_rows.html" if request.headers.get("HX-Request") else "employees/slots_list.html"
    return render(request, template, context)


@login_required
@manage_slots
def slot_add(request: HttpRequest) -> HttpResponse:
    initial = {"year": _year_param(request.GET.get("year"), timezone.localdate().year), "kind": MAIN}
    if request.method != "POST":
        return _modal(request, SlotForm(initial=initial), None)
    form = SlotForm(request.POST)
    if not form.is_valid():
        return _modal(request, form, None)
    return _save(request, form, None)


@login_required
@manage_slots
def slot_edit(request: HttpRequest, pk: int) -> HttpResponse:
    row = get_object_or_404(NazgRow.objects.select_related("position", "branch"), pk=pk)
    if request.method != "POST":
        return _modal(request, SlotForm(initial=_initial(row), row=row), row)
    form = SlotForm(request.POST, row=row)
    if not form.is_valid():
        return _modal(request, form, row)
    return _save(request, form, row)


def _save(request: HttpRequest, form: SlotForm, row: NazgRow | None) -> HttpResponse:
    data = form.cleaned_data
    assert isinstance(request.user, User)  # noqa: S101
    try:
        slots.save_row(
            position=data["position"],
            branch=data["branch"],
            kind=data["kind"],
            year=data["year"],
            qty=data["qty"],
            by=request.user,
            row=row,
        )
    except slots.SlotRowExists as exists:  # another save took the key between the form check and the write
        form.add_error(None, _exists_message(exists.row))
        return _modal(request, form, row)
    except slots.SlotWriteDenied as denied:  # the database login lacks the grant on nazg: say so, no 500
        form.add_error(None, denied.message)
        return _modal(request, form, row)
    return _done()


@login_required
@manage_slots
def slot_delete(request: HttpRequest, pk: int) -> HttpResponse:
    row = get_object_or_404(NazgRow.objects.select_related("position", "branch"), pk=pk)
    if request.method != "POST":
        return redirect("employees:slots")
    assert isinstance(request.user, User)  # noqa: S101
    try:
        slots.delete_row(row, by=request.user)
    except slots.SlotWriteDenied as denied:
        form = SlotForm(_initial(row), row=row)  # bound, so the error can be added; shows the row's own values
        form.is_valid()  # run the form checks once so an error can be added
        form.add_error(None, denied.message)
        return _modal(request, form, row)
    return _done()
