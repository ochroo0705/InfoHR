"""The position-slot screen «Орон тооны төлөвлөгөө»: the budget table `nazg` per year, with the people using each row.

Only holders of `employees.manage_position_slots` open it (403 for others). The rules (counting, one row per key,
the log) live in `employees.services.slots`; this module only draws the pages and the pop-up forms.
"""

from dataclasses import asdict
from datetime import date
from typing import Any

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
from employees.services import slot_page, slots
from employees.services.slot_page import MAX_YEAR, MIN_YEAR
from employees.services.slot_page import exists_message as _exists_message
from employees.services.slot_page import year_param as _year_param
from employees.slot_kind import MAIN, TEMPORARY

KIND_CHOICES = [(MAIN, slots.KIND_LABELS[MAIN]), (TEMPORARY, slots.KIND_LABELS[TEMPORARY])]

manage_slots = permission_required("employees.manage_position_slots", raise_exception=True)


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
    return slot_page.used_on(year, timezone.localdate())


@login_required
@manage_slots
@require_GET
def slot_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    year = _year_param(request.GET.get("year"), today.year)
    slot_lines = slot_page.slot_lines(year, today, on=_used_on(year))
    lines: list[dict[str, Any]] = [
        {"row": line.row, "posts": line.posts, "used": line.used, "free": line.free} for line in slot_lines
    ]
    totals = asdict(slot_page.totals(slot_lines))
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
