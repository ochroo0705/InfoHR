"""The Lists screen: one generic editor for every production lookup table (docs/UI_RULES.md §11)."""

from typing import Any

from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from lists import service
from lists.forms import entry_form, list_fields
from lists.registry import LISTS, MEANINGS, QUICK, ListSpec
from lists.service import (
    cell_text,
    delete_entry,
    index_items,
    meaning_rows,
    save_entry,
    save_meanings,
    show_meanings,
)


def _spec(slug: str) -> ListSpec:
    spec = LISTS.get(slug)
    if spec is None:
        raise Http404
    return spec


def _done() -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def index(request: HttpRequest) -> HttpResponse:
    q = request.GET.get("q", "").strip()
    items = [{"spec": LISTS[item.slug], "count": item.count, "hits": item.hits} for item in index_items(q)]
    context = {"items": items, "meanings": MEANINGS, "q": q, "show_meanings": show_meanings(q)}
    return render(request, "lists/index.html", context)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def list_view(request: HttpRequest, slug: str) -> HttpResponse:
    spec = _spec(slug)
    form_class = entry_form(spec)
    columns = [(name, form_class.base_fields[name].label) for name in list_fields(spec)]
    entries = spec.model.objects.all().order_by("name")
    rows = [(entry, [cell_text(entry, name) for name, _label in columns]) for entry in entries]
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
    if request.method == "POST":
        result = save_entry(spec, request.POST)
        if result.ok:
            return _done()
        form = result.form
    else:
        form = entry_form(spec)()
    return _modal(request, spec, form, entry=None)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def edit(request: HttpRequest, slug: str, pk: int) -> HttpResponse:
    spec = _spec(slug)
    entry = get_object_or_404(spec.model, pk=pk)
    if request.method == "POST":
        result = save_entry(spec, request.POST, entry=entry)
        if result.ok:
            return _done()
        form = result.form
    else:
        form = entry_form(spec)(instance=entry)
    return _modal(request, spec, form, entry=entry)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def delete(request: HttpRequest, slug: str, pk: int) -> HttpResponse:
    spec = _spec(slug)
    entry = get_object_or_404(spec.model, pk=pk)
    if request.method != "POST":
        return redirect("lists:list", slug=slug)
    result = delete_entry(entry)
    if result.ok:
        return _done()
    return _modal(request, spec, entry_form(spec)(instance=entry), entry=entry, error=result.error)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def meaning(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        save_meanings(request.POST)
        return redirect("lists:meaning")
    rows = [
        {
            "key": row.key,
            "spec": MEANINGS[row.key],
            "options": [{"pk": pk, "name": name} for pk, name in row.options],
            "current": row.current,
        }
        for row in meaning_rows()
    ]
    return render(request, "lists/meaning.html", {"rows": rows})


def _quick_spec(slug: str) -> ListSpec:
    spec = QUICK.get(slug)
    if spec is None:
        raise Http404
    return spec


def _quick_modal(request: HttpRequest, spec: ListSpec, form: Any, *, status: int = 200) -> HttpResponse:
    context = {
        "title": f"{spec.label}: шинэ бичлэг",
        "form": form,
        "action": reverse("lists:quick_add", args=[spec.slug]),
    }
    return render(request, "lists/_quick_modal.html", context, status=status)


@login_required
@permission_required("lists.manage_lists", raise_exception=True)
def quick_add(request: HttpRequest, slug: str) -> HttpResponse:
    """Add an entry from a form dropdown. GET: the pop-up for lists with more fields. POST: JSON {id, name, existed}."""
    spec = _quick_spec(slug)
    if request.method == "POST":
        result = service.quick_add(spec, request.POST)
        if result.ok:
            return JsonResponse({"id": result.id, "name": result.name, "existed": result.existed})
        if spec.modal:
            return _quick_modal(request, spec, result.form, status=400)
        return JsonResponse({"error": service.first_error(result.form)}, status=400)
    if not spec.modal:
        raise Http404
    form_class = entry_form(spec)
    return _quick_modal(request, spec, form_class(initial=service.quick_initial(spec, request.GET)))
