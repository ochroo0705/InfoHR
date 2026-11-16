"""The in-page order template editor: its page, and the save and reset calls behind it.

`OrderTemplateAdmin` wires these views under its own URLs and passes itself in, so the admin's `has_view_permission`
and `has_change_permission` decide who gets in. The Word file is built by `order_template_editor`. A save ends in
`OrderTemplate.save()`, so the audit receiver logs it exactly as an admin save is logged.
"""

import json
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from accounts.models import User
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from lxml.etree import XMLSyntaxError

from employees import access
from employees.listing import still_working
from employees.models import CompanySettings, Employee, OrderTemplate, OrderType
from employees.services import order_docs
from employees.services.order_template_editor import doc_to_docx, docx_to_doc, validate_doc

TEMPLATE = "employees/order_template_editor.html"
EMPLOYEE_CHOICE_LIMIT = 500  # the preview picker lists at most this many people; the default (first) covers the rest
STALE_MESSAGE = "Өөр хүн өөрчилсөн байна. Хуудсаа дахин нээнэ үү."
NO_CHANGE_MESSAGE = "Энэ загварыг засах эрх байхгүй байна."
BAD_REQUEST_MESSAGE = "Хүсэлтийн өгөгдөл буруу байна."
BAD_UPDATED_AT_MESSAGE = "«updated_at» талбар дутуу эсвэл буруу байна."
BAD_LETTERHEAD_MESSAGE = "«Бланк дээр гаргах» сонголт үнэн эсвэл худал байх ёстой."
BAD_EMPLOYEE_MESSAGE = "«employee_id» талбар буруу байна."
PREVIEW_FAILED_MESSAGE = "Загварыг бөглөж чадсангүй. Талбаруудаа шалгана уу."
NOT_EDITABLE_MESSAGE = "Энэ загварыг энд засах боломжгүй. Word файл оруулах эсвэл стандарт загварт буцаана уу."


def edit_page(model_admin: Any, request: HttpRequest, pk: int) -> HttpResponse:
    """The editor page. A user with view permission only sees it read-only (`can_change` is false)."""
    if not model_admin.has_view_permission(request):
        return HttpResponse(status=404)
    row = get_object_or_404(OrderTemplate, pk=pk)
    doc = _editor_doc(row)
    fields = _fields_for(row.order_type)
    urls = {
        "save_url": reverse("admin:employees_ordertemplate_save", args=[row.pk]),
        "reset_url": reverse("admin:employees_ordertemplate_reset", args=[row.pk]),
    }
    payload = {
        "doc": doc,
        "fields": fields,
        "updated_at": row.updated_at.isoformat(),
        "can_change": model_admin.has_change_permission(request, row),
        "show_letterhead": row.show_letterhead,
        **urls,
    }
    panel_groups, other_fields = _panel(fields)
    context = {
        **model_admin.admin_site.each_context(request),
        "opts": OrderTemplate._meta,
        "title": f"Загвар засах: {row}",
        "row": row,
        "order_type_label": str(row),
        "back_url": reverse("admin:employees_ordertemplate_changelist"),
        "uses_starter": not row.file,
        "payload": payload,
        **payload,
        "preview_url": reverse("admin:employees_ordertemplate_preview", args=[row.pk]),
        "download_url": reverse("admin:employees_ordertemplate_download", args=[row.pk]) + "?which=current",
        "letterhead_url": reverse("admin:employees_companysettings_changelist"),
        "letterhead": _letterhead(CompanySettings.get()),
        "panel_groups": panel_groups,
        "other_fields": other_fields,
        "employee_choices": _employee_choices(request.user),  # type: ignore[arg-type]
    }
    return render(request, TEMPLATE, context)


def _letterhead(company: CompanySettings) -> dict[str, Any]:
    """The letterhead presets and lines the locked mock on the editor page is drawn from (company-level only)."""
    return {
        "logo_place": company.letterhead_logo_place,
        "text_align": company.letterhead_text_align,
        "logo_size": company.letterhead_logo_size,
        "rule": company.letterhead_rule,
        "lines": company.letterhead_text(),
    }


def _employee_choices(user: User) -> list[dict[str, Any]]:
    """The people the preview can be drawn for, from the user's own data scope: working today, by name."""
    visible = access.visible_employees(user)
    rows = still_working(visible, timezone.localdate()).order_by("family_name", "given_name", "pk")
    return [
        {"pk": e.pk, "label": " ".join(part for part in (e.code, e.family_name, e.given_name) if part)}
        for e in rows[:EMPLOYEE_CHOICE_LIMIT]
    ]


def _panel(fields: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The side panel: the fields that fill for this order type, grouped as on the order pages; and every other
    field, flat, under «Бусад төрлийн талбар»."""
    groups: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for group in fields:
        wanted = [item for item in group["items"] if item["for_this_type"]]
        others.extend(item for item in group["items"] if not item["for_this_type"])
        if wanted:
            groups.append({"group": group["group"], "items": wanted})
    return groups, others


def save_view(model_admin: Any, request: HttpRequest, pk: int) -> HttpResponse:
    """Saves the editor's document as the template's .docx. Body: {updated_at, doc, show_letterhead}.

    The stale check, the editability check and the write run in one transaction, on a row locked where the backend
    supports it, so two saves cannot both pass the check.
    """
    row = get_object_or_404(OrderTemplate, pk=pk)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not model_admin.has_change_permission(request, row):
        return JsonResponse({"ok": False, "errors": [NO_CHANGE_MESSAGE]}, status=403)
    try:
        body = json.loads(request.body or b"null")
    except (ValueError, UnicodeDecodeError, RecursionError):
        body = None
    if not isinstance(body, dict):
        return _errors(400, BAD_REQUEST_MESSAGE)
    updated_at = body.get("updated_at")
    if not isinstance(updated_at, str):
        return _errors(400, BAD_UPDATED_AT_MESSAGE)
    show_letterhead = body.get("show_letterhead")
    if not isinstance(show_letterhead, bool):
        return _errors(400, BAD_LETTERHEAD_MESSAGE)

    with transaction.atomic():
        locked = _locked_row(pk)
        if updated_at != locked.updated_at.isoformat():
            return _errors(409, STALE_MESSAGE)
        if _editor_doc(locked) is None:  # a file the editor cannot represent is never overwritten from here
            return _errors(409, NOT_EDITABLE_MESSAGE)
        problems = validate_doc(body.get("doc"), locked.order_type)
        if problems:
            return JsonResponse({"ok": False, "errors": problems}, status=400)

        data = doc_to_docx(body["doc"], locked.order_type)
        locked.file.save(order_docs.TEMPLATE_FILES[OrderType(locked.order_type)], ContentFile(data), save=False)
        locked.show_letterhead = show_letterhead
        locked.updated_by = request.user  # type: ignore[assignment]
        locked.save()  # the audit receiver runs inside this save: a failed log write rolls it back
        locked.refresh_from_db(fields=["updated_at"])
        return JsonResponse({"ok": True, "updated_at": locked.updated_at.isoformat()})


def preview_view(model_admin: Any, request: HttpRequest, pk: int) -> HttpResponse:
    """The PDF preview of the editor's unsaved document, drawn for one employee by the same renderer as a print.
    Body: {doc, employee_id, show_letterhead}. `employee_id` null means the first employee the user may see who works
    here today. Needs only view permission; saves nothing (no order, number, event or audit row)."""
    if not model_admin.has_view_permission(request):
        return HttpResponse(status=404)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    row = get_object_or_404(OrderTemplate, pk=pk)
    try:
        body = json.loads(request.body or b"null")
    except (ValueError, UnicodeDecodeError, RecursionError):
        body = None
    if not isinstance(body, dict):
        return _errors(400, BAD_REQUEST_MESSAGE)
    show_letterhead = body.get("show_letterhead")
    if not isinstance(show_letterhead, bool):
        return _errors(400, BAD_LETTERHEAD_MESSAGE)
    employee_id = body.get("employee_id")
    if employee_id is not None and (not isinstance(employee_id, int) or isinstance(employee_id, bool)):
        return _errors(400, BAD_EMPLOYEE_MESSAGE)
    doc = body.get("doc")
    if doc is not None:  # a read-only page sends no document: the stored template is previewed instead
        problems = validate_doc(doc, row.order_type)
        if problems:
            return JsonResponse({"ok": False, "errors": problems}, status=400)

    user: User = request.user  # type: ignore[assignment]  # admin_view only lets signed-in staff through
    employee = _preview_employee(user, employee_id)
    if employee is None:  # outside the user's data scope, or no such employee: the same answer as the order pages
        return HttpResponse(status=404)
    try:
        content = doc_to_docx(doc, row.order_type) if doc is not None else _stored_docx(row.order_type)
        pdf = order_docs.preview_pdf(row.order_type, employee, content, user, show_letterhead=show_letterhead)
    except (order_docs.OrderDocError, BadZipFile, XMLSyntaxError, OSError):  # a corrupt stored file is a 400, not a 500
        return _errors(400, PREVIEW_FAILED_MESSAGE)
    return HttpResponse(pdf, content_type="application/pdf")


def _preview_employee(user: User, employee_id: int | None) -> Employee | None:
    """The employee a preview is drawn for: the one asked for (only if the user may see them), else the first
    employee the user may see who works here today. None when there is none."""
    visible = access.visible_employees(user)
    if employee_id is None:
        return still_working(visible, timezone.localdate()).order_by("pk").first()
    return visible.filter(pk=employee_id).first()


def reset_view(model_admin: Any, request: HttpRequest, pk: int) -> HttpResponse:
    """Puts the bundled starter back: the file is cleared and the letterhead is switched on, as for a new template.
    Works on every row, including one the editor cannot show: it is the way out of such a file."""
    row = get_object_or_404(OrderTemplate, pk=pk)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not model_admin.has_change_permission(request, row):
        return JsonResponse({"ok": False, "errors": [NO_CHANGE_MESSAGE]}, status=403)
    row.file = ""
    row.show_letterhead = True
    row.updated_by = request.user  # type: ignore[assignment]
    with transaction.atomic():
        row.save()
    row.refresh_from_db(fields=["updated_at"])
    return JsonResponse({"ok": True, "updated_at": row.updated_at.isoformat()})


def _locked_row(pk: int) -> OrderTemplate:
    """The row, locked until the surrounding transaction ends where the database supports row locks."""
    queryset = OrderTemplate.objects.all()
    if connection.features.has_select_for_update:
        queryset = queryset.select_for_update()
    return queryset.get(pk=pk)


def _editor_doc(row: OrderTemplate) -> dict[str, Any] | None:
    """The document as the editor shows it: the stored file, or the bundled starter when there is none.
    None means the page is read-only (the file cannot be shown in the editor, or cannot be read)."""
    if row.file:
        try:
            with row.file.open("rb") as handle:
                data = handle.read()
        except OSError:
            return None
    else:
        data = order_docs.starter_path(row.order_type).read_bytes()
    return docx_to_doc(data, row.order_type)


def _stored_docx(order_type: int) -> bytes:
    """The .docx the template of this type holds now: the uploaded file, else the bundled starter (the same source
    the orders are printed from)."""
    source = order_docs.template_source(order_type)
    return source.read_bytes() if isinstance(source, Path) else source.getvalue()


def _fields_for(order_type: int) -> list[dict[str, Any]]:
    """Every field of the help list, grouped as on the order pages. `for_this_type` marks the ones that fill for
    this order type; the others are still offered, flagged, so an existing template can use them."""
    wanted = set(order_docs.placeholders_for(order_type))
    groups: dict[str, list[dict[str, Any]]] = {}
    for group, name, meaning in order_docs.PLACEHOLDER_HELP:
        item = {
            "name": name,
            "label": order_docs.PLACEHOLDER_LABELS.get(name, name),  # the short chip text
            "meaning": meaning,
            "for_this_type": name in wanted,
        }
        groups.setdefault(group, []).append(item)
    return [{"group": group, "items": items} for group, items in groups.items()]


def _errors(status: int, message: str) -> JsonResponse:
    return JsonResponse({"ok": False, "errors": [message]}, status=status)
