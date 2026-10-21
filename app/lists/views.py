"""The Lists screen: one generic editor for every production lookup table (docs/UI_RULES.md §11)."""

import re
from typing import Any

from config.converters import INT4_MAX, INT4_MIN
from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from employees.services import macs_writes
from employees.services.macs_writes import ListEntryInUse

from lists.forms import entry_form, list_fields
from lists.models import MeaningfulEntry
from lists.registry import LISTS, MEANINGS, QUICK, ListSpec


def _spec(slug: str) -> ListSpec:
    spec = LISTS.get(slug)
    if spec is None:
        raise Http404
    return spec


def _done() -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


def _cell(entry: Any, field: str) -> Any:
    display = getattr(entry, f"get_{field}_display", None)  # choice fields show their label
    return display() if display else getattr(entry, field)


_SIGNED_INT = re.compile(r"-?[0-9]{1,10}")


def _int(value: str | None) -> int | None:
    """A lookup-table id from a form. Negative ids are valid (MACS test data, QC 2b)."""
    if not value or not _SIGNED_INT.fullmatch(value) or not INT4_MIN <= int(value) <= INT4_MAX:
        return None
    return int(value)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def index(request: HttpRequest) -> HttpResponse:
    items = [{"spec": spec, "count": spec.model.objects.count()} for spec in LISTS.values()]
    return render(request, "lists/index.html", {"items": items, "meanings": MEANINGS})


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def list_view(request: HttpRequest, slug: str) -> HttpResponse:
    spec = _spec(slug)
    form_class = entry_form(spec)
    columns = [(name, form_class.base_fields[name].label) for name in list_fields(spec)]
    entries = spec.model.objects.all().order_by("name")
    rows = [(entry, [_cell(entry, name) for name, _label in columns]) for entry in entries]
    return render(request, "lists/list.html", {"spec": spec, "columns": columns, "rows": rows})


def _modal(request: HttpRequest, spec: ListSpec, form: Any, *, entry: Any | None, error: str = "") -> HttpResponse:
    if entry is None:
        title, action, delete_url = spec.label, reverse("lists:add", args=[spec.slug]), ""
    else:
        title = f"{spec.label}: засах"
        action = reverse("lists:edit", args=[spec.slug, entry.pk])
        delete_url = reverse("lists:delete", args=[spec.slug, entry.pk])
    context = {"title": title, "form": form, "action": action, "entry": entry, "delete_url": delete_url, "error": error}
    return render(request, "lists/_entry_form.html", context)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def add(request: HttpRequest, slug: str) -> HttpResponse:
    spec = _spec(slug)
    form_class = entry_form(spec)
    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            macs_writes.save_list_entry(spec.model, form.cleaned_data)
            return _done()
    else:
        form = form_class()
    return _modal(request, spec, form, entry=None)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def edit(request: HttpRequest, slug: str, pk: int) -> HttpResponse:
    spec = _spec(slug)
    entry = get_object_or_404(spec.model, pk=pk)
    form_class = entry_form(spec)
    if request.method == "POST":
        form = form_class(request.POST, instance=entry)
        if form.is_valid():
            macs_writes.save_list_entry(spec.model, form.cleaned_data, entry=entry)
            return _done()
    else:
        form = form_class(instance=entry)
    return _modal(request, spec, form, entry=entry)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def delete(request: HttpRequest, slug: str, pk: int) -> HttpResponse:
    spec = _spec(slug)
    entry = get_object_or_404(spec.model, pk=pk)
    if request.method != "POST":
        return redirect("lists:list", slug=slug)
    try:
        macs_writes.delete_list_entry(entry)
    except ListEntryInUse as exc:
        return _modal(request, spec, entry_form(spec)(instance=entry), entry=entry, error=str(exc))
    return _done()


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def meaning(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        for key, spec in MEANINGS.items():
            raw = request.POST.get(key, "")
            pk = _int(raw)
            if pk is not None and spec.model.objects.filter(pk=pk).exists():
                MeaningfulEntry.objects.update_or_create(key=key, defaults={"value": pk})
            elif not raw:
                MeaningfulEntry.objects.filter(key=key).delete()
        return redirect("lists:meaning")
    rows = [
        {"key": key, "spec": spec, "options": spec.model.objects.all(), "current": MeaningfulEntry.get(key)}
        for key, spec in MEANINGS.items()
    ]
    return render(request, "lists/meaning.html", {"rows": rows})


def _quick_spec(slug: str) -> ListSpec:
    spec = QUICK.get(slug)
    if spec is None:
        raise Http404
    return spec


def _existing(spec: ListSpec, name: str, parent: str = "") -> Any | None:
    """The entry with the same name (trimmed, case-insensitive), so the add never makes a duplicate.
    A list with a parent (district -> city) matches only inside the same parent."""
    if not name:
        return None
    qs = spec.model.objects.filter(name__iexact=name)
    if spec.parent:
        parent_id = _int(parent)
        if parent_id is None:
            return None
        qs = qs.filter(**{f"{spec.parent}_id": parent_id})
    return qs.order_by("pk").first()


def _reactivate(spec: ListSpec, entry: Any) -> None:
    """Department and Position keep an HR extension row with an active flag; a duplicate that was
    switched off is shown again instead of being left out of the dropdowns."""
    if spec.slug == "department":
        macs_writes.reactivate_department(entry)
    elif spec.slug == "position":
        macs_writes.reactivate_position(entry)


def _create(spec: ListSpec, values: dict[str, Any]) -> Any:
    if spec.slug == "department":
        return macs_writes.save_department(values["name"])
    if spec.slug == "position":
        return macs_writes.save_position(values["name"])
    return macs_writes.save_list_entry(spec.model, values)


def _quick_modal(request: HttpRequest, spec: ListSpec, form: Any, *, status: int = 200) -> HttpResponse:
    context = {
        "title": f"{spec.label}: шинэ бичлэг",
        "form": form,
        "action": reverse("lists:quick_add", args=[spec.slug]),
    }
    return render(request, "lists/_quick_modal.html", context, status=status)


def _first_error(form: Any) -> str:
    for errors in form.errors.values():
        return str(errors[0])
    return "Алдаа гарлаа."


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def quick_add(request: HttpRequest, slug: str) -> HttpResponse:
    """Add an entry from a form dropdown. GET: the pop-up for lists with more fields. POST: JSON {id, name, existed}."""
    spec = _quick_spec(slug)
    form_class = entry_form(spec)
    if request.method == "POST":
        existing = _existing(spec, request.POST.get("name", "").strip(), request.POST.get(spec.parent or "", ""))
        if existing is not None:
            _reactivate(spec, existing)
            return JsonResponse({"id": existing.pk, "name": existing.name, "existed": True})
        form = form_class(request.POST)
        if form.is_valid():
            entry = _create(spec, form.cleaned_data)
            return JsonResponse({"id": entry.pk, "name": entry.name, "existed": False})
        if spec.modal:
            return _quick_modal(request, spec, form, status=400)
        return JsonResponse({"error": _first_error(form)}, status=400)
    if not spec.modal:
        raise Http404
    initial = {name: request.GET[name] for name in list_fields(spec) if request.GET.get(name)}
    return _quick_modal(request, spec, form_class(initial=initial))
