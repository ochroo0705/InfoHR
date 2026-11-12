"""Saved workspace tables (SavedTable): the list, the page with the table tools and no chat, the exports, and delete.

The table is the workspace's own: the helpers of ws_views build the pane, the Excel file, the print page and the copy
text from a `_Source` of kind "saved". Nothing a viewer changes here is saved back (persist is False); the SQL runs
fresh, as the viewer, through the same governed path. Access: the workspace gate (404 when closed), then the table must
be visible to the viewer (`saved_tables.visible_to`, 404 otherwise). Delete also needs `saved_tables.can_delete` (403).
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from assistant.models import SavedTable
from assistant.saved_tables import can_delete, visible_to
from assistant.ws_excel import plain_title, ws_excel_bytes, ws_tsv_text
from assistant.ws_views import (
    EXPORT_REFUSED,
    TEXT_TYPE,
    XLSX_TYPE,
    _attachment,
    _cell,
    _export,
    _gated_user,
    _print_lines,
    _Source,
    _table_context,
)


def _visible_table(user, pk: int) -> SavedTable:
    """The saved table when the viewer may see it, else 404."""
    return get_object_or_404(visible_to(user), pk=pk)


def _saved_source(table: SavedTable) -> _Source:
    """The source of a saved table: its SQL and settings as stored; nothing is written back (persist is False)."""
    return _Source(kind="saved", pk=table.pk, title=table.name, version=table, persist=False, tab=None)


def _page(request: HttpRequest, user, table: SavedTable) -> HttpResponse:
    """The whole saved page: the heading, then the table pane with its tools. No chat."""
    source = _saved_source(table)
    return render(
        request,
        "assistant/saved_page.html",
        {"saved": table, "can_delete": can_delete(user, table), **_table_context(request, user, source)},
    )


@login_required
@require_GET
def saved_list(request: HttpRequest) -> HttpResponse:
    """The saved tables the viewer may see: shared ones and their own private ones, by name."""
    user = _gated_user(request)
    rows = [
        {"table": table, "can_delete": can_delete(user, table)}
        for table in visible_to(user).select_related("author")
    ]
    return render(request, "assistant/saved_list.html", {"rows": rows})


@login_required
@require_GET
def saved_page(request: HttpRequest, pk: int) -> HttpResponse:
    """One saved table, drawn in full with its tools."""
    user = _gated_user(request)
    return _page(request, user, _visible_table(user, pk))


@login_required
@require_GET
def saved_table(request: HttpRequest, pk: int) -> HttpResponse:
    """The table pane of a saved table. An htmx request gets the pane alone; a plain request (or a back step) gets the
    whole saved page, so the addresses the pane pushes still open the table."""
    user = _gated_user(request)
    table = _visible_table(user, pk)
    fragment = (
        request.headers.get("HX-Request") == "true" and request.headers.get("HX-History-Restore-Request") != "true"
    )
    if fragment:
        return render(request, "assistant/_ws_table.html", _table_context(request, user, _saved_source(table)))
    return _page(request, user, table)


@login_required
@require_GET
def saved_excel(request: HttpRequest, pk: int) -> HttpResponse:
    """The saved table's rows as an .xlsx file, under the address's settings (as the workspace's Excel)."""
    user = _gated_user(request)
    source = _saved_source(_visible_table(user, pk))
    export = _export(request, user, source)
    if export.line:
        return HttpResponse(export.line, status=EXPORT_REFUSED, content_type=TEXT_TYPE)
    body = ws_excel_bytes(export.headers(), export.result.rows, source.title, cut=export.cut)
    response = HttpResponse(body, content_type=XLSX_TYPE)
    response["Content-Disposition"] = _attachment(source, "xlsx")
    return response


@login_required
@require_GET
def saved_print(request: HttpRequest, pk: int) -> HttpResponse:
    """The print page of the saved table: its filters, then its rows. Printed on load by the page."""
    user = _gated_user(request)
    source = _saved_source(_visible_table(user, pk))
    export = _export(request, user, source)
    if export.line:
        return HttpResponse(export.line, status=EXPORT_REFUSED, content_type=TEXT_TYPE)
    shown = [[_cell(value) for value in row] for row in export.result.rows]
    return render(
        request,
        "assistant/ws_print.html",
        {
            "title": plain_title(source.title),
            "today": timezone.localdate(),
            "lines": _print_lines(export.spec, export.names),
            "headers": export.headers(),
            "rows": shown,
            "cut": export.cut,
            "count": len(shown),
        },
    )


@login_required
@require_GET
def saved_copy(request: HttpRequest, pk: int) -> HttpResponse:
    """All the rows of the saved table as tab-separated text with the header line, for the clipboard."""
    user = _gated_user(request)
    source = _saved_source(_visible_table(user, pk))
    export = _export(request, user, source)
    if export.line:
        return HttpResponse(export.line, status=EXPORT_REFUSED, content_type=TEXT_TYPE)
    response = HttpResponse(ws_tsv_text(export.headers(), export.result.rows), content_type=TEXT_TYPE)
    if export.cut:
        response["X-Cut"] = "1"
    return response


@login_required
@require_POST
def saved_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete a saved table. 404 unless the viewer may see it; 403 unless the viewer is its author or may manage saved
    tables. The list is shown again with a message."""
    user = _gated_user(request)
    table = _visible_table(user, pk)
    if not can_delete(user, table):
        raise PermissionDenied
    table.delete()
    messages.success(request, "Устгалаа.")
    return redirect("assistant:saved_list")
