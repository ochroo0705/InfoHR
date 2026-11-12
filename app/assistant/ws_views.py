"""The workspace page (`assistant:workspace`): the tab strip, the table and chat panes, and the new / rename / close
actions on a tab.

Access is one gate, `can_use_workspace`: the governed SQL switch on, the governed database ready, and a non-empty
catalogue for the viewer. A user who fails it gets 404 on every workspace view, and no nav entry (accounts/nav.py).
Every view fetches a tab with `get_object_or_404(WorkspaceTab, pk=pk, owner=user)`: ws_service does not check owners.
The new, rename and close actions are plain POST forms that redirect back, so they work without script.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

from accounts.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from hr_sql.host import HrHost

from assistant import sqlanswer, ws_run
from assistant.models import HelpQuestion, SavedTable, VerifiedQuery, WorkspaceTab, WorkspaceVersion
from assistant.providers import get_provider
from assistant.ws_excel import ascii_stem, file_stem, plain_title, ws_excel_bytes, ws_tsv_text
from assistant.ws_labels import COUNT_LABEL, display_names, view_labels
from assistant.ws_limits import EXPORT_MAX_ROWS, EXPORT_TIMEOUT_S, MAX_PAGE, MAX_TABS, PAGE_SIZE
from assistant.ws_service import (
    PROVIDER_LINE,
    WorkspaceLimit,
    close,
    new_tab,
    note_undo,
    open_from_question,
    refine_tab,
    rename,
    tabs_of,
    undo,
)
from assistant.ws_sql import COUNT_NAME, OPS, Filter, Spec, spec_from_json, spec_to_json, usable_columns

logger = logging.getLogger(__name__)

EMPTY_TITLE_TEXT = "Хүснэгтийн гарчгийг бичнэ үү."  # the message when a rename is sent with no title
GATE_CACHE_SECONDS = 60  # the gate answer per user is kept this long, shared by the views and the top bar
CHAT_MAX_CHARS = 500  # a chat line longer than this (after stripping) is refused with 400
CHAT_EMPTY_TEXT = "Асуултаа бичнэ үү."
CHAT_TOO_LONG_TEXT = f"Асуулт {CHAT_MAX_CHARS} тэмдэгтээс урт байна."
CHAT_ERROR_HEADER = "X-Chat-Error"  # set on a refused line: the form swaps its fragment in, with the error line

# The table pane (ws_table). ws_run's reasons are English and may echo viewer text, so the page shows these instead.
TABLE_REASONS = {
    "off": "Энэ хүснэгт одоо харагдахгүй байна.",
    "unavailable": "Өгөгдлийн сан бэлэн биш байна. Дараа дахин оролдоно уу.",
    "no_views": "Танд асуух өгөгдлийн хүснэгт алга.",
    "refused": "Энэ хүснэгтийг одоо харуулах боломжгүй байна. Шүүлтүүрээ арилгаад үзнэ үү.",
}
EMPTY_TAB_TEXT = "Хүснэгт хараахан хоосон байна. Чатаар асуулт асууж хүснэгтээ бөглөнө үү."
OP_LABELS = {
    "contains": "агуулсан",
    "eq": "тэнцүү",
    "gt": "их",
    "lt": "бага",
    "empty": "хоосон",
    "notempty": "хоосон биш",
}
MAX_SORTS = 5  # the table offers up to five sort keys (UI_RULES 4b)
MAX_FILTERS = 10  # the most filters one request may carry
_PAGE_DIGITS = re.compile(r"[0-9]{1,6}")  # ASCII digits only: int() of other digit forms can raise
TABLE_PARAMS = ("page", "sort", "f", "cols", "group")  # the address parameters that make a request explicit


def _catalogue_views(user: User) -> tuple:
    """The views the viewer may read. A module-level seam: the tests replace it, so no Firebird is needed."""
    return HrHost().catalogue_for(user).views


def _gate(user: User) -> bool:
    """The gate itself: switch on, governed database ready, at least one view. May raise (not caught here)."""
    if not sqlanswer._setting_enabled():
        return False
    if not sqlanswer._database_ready():
        return False
    return bool(_catalogue_views(user))


def can_use_workspace(user: User | AnonymousUser) -> bool:
    """The workspace gate: switch on, governed database ready, and at least one view for this viewer.

    The answer per signed-in user is cached for GATE_CACHE_SECONDS (only the boolean; never an exception). An
    anonymous user answers False without touching the cache or the database.
    Fails closed: an error while the gate is worked out answers False (the views then 404, the nav shows no entry).
    Only the exception's type name is logged, never its message, which can carry a database detail.
    Switching governed SQL off, or revoking a view, may take up to 60 s to show on the page; every run and refine
    re-checks it live.
    """
    if not isinstance(user, User) or not user.is_authenticated:
        return False
    key = f"ws_gate:{user.pk}"
    try:
        cached = cache.get(key)
        if cached is not None:
            return bool(cached)
        allowed = _gate(user)
        cache.set(key, allowed, GATE_CACHE_SECONDS)
        return allowed
    except Exception as exc:
        logger.warning("workspace gate failed: %s", type(exc).__name__)
        return False


def _gated_user(request: HttpRequest) -> User:
    """The signed-in viewer, or 404 when the workspace gate is closed for them. The result is kept on the request, so
    the nav (accounts/nav.py) reads it instead of building the catalogue again."""
    user = request.user
    assert isinstance(user, User)
    allowed: bool | None = getattr(request, "_sees_workspace", None)
    if allowed is None:
        allowed = can_use_workspace(user)
        request._sees_workspace = allowed  # type: ignore[attr-defined]
    if not allowed:
        raise Http404
    return user


@login_required
def workspace(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    """The workspace page. `workspace/` opens the newest tab; `workspace/<pk>/` opens the given tab of the viewer.
    A viewer with no tab at all gets one empty tab made and opened, so the chat box is ready at once."""
    user = _gated_user(request)
    tabs = tabs_of(user)
    if pk is None and not tabs:
        try:
            return redirect("assistant:workspace_tab", pk=new_tab(user).pk)
        except WorkspaceLimit:
            pass  # cannot happen with no tabs; fall through to the empty page
    if pk is None:
        current = tabs[-1] if tabs else None
    else:
        current = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    return render(request, "assistant/workspace.html", {"tabs": tabs, "current": current, "max_tabs": MAX_TABS})


@login_required
@require_POST
def ws_new(request: HttpRequest) -> HttpResponse:
    """Make an empty tab and open it. Past the tab limit the viewer is sent back with a message."""
    user = _gated_user(request)
    try:
        tab = new_tab(user)
    except WorkspaceLimit as exc:
        messages.error(request, str(exc))
        return redirect("assistant:workspace")
    return redirect("assistant:workspace_tab", pk=tab.pk)


@login_required
@require_POST
def ws_open(request: HttpRequest, question_id: int) -> HttpResponse:
    """Open the workspace tab made from one of the viewer's governed SQL answers (made on the first press, reused
    after). Someone else's question, a non-SQL one or one whose SQL no longer passes the checker answers 404. Past the
    tab limit the viewer is sent back to the workspace with the message."""
    user = _gated_user(request)
    question = get_object_or_404(HelpQuestion, pk=question_id, user=user)
    try:
        tab = open_from_question(user, question)
    except PermissionError:
        raise Http404 from None
    except WorkspaceLimit as exc:
        messages.error(request, str(exc))
        return redirect("assistant:workspace")
    return redirect("assistant:workspace_tab", pk=tab.pk)


@login_required
@require_POST
def ws_rename(request: HttpRequest, pk: int) -> HttpResponse:
    """Change the title of one of the viewer's tabs."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    title = request.POST.get("title", "").strip()
    if not title:
        messages.error(request, EMPTY_TITLE_TEXT)
    else:
        rename(tab, title)
    return redirect("assistant:workspace_tab", pk=tab.pk)


@login_required
@require_POST
def ws_close(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete one of the viewer's tabs with its versions and messages; the newest remaining tab opens."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    title = tab.title
    close(tab)
    messages.success(request, f"«{title}» хүснэгт хаагдлаа.")
    return redirect("assistant:workspace")


def _page_param(raw: str | None) -> int:
    """The 0-based page from the address. Anything that is not a small whole number, or above MAX_PAGE, is page 0."""
    if raw is None or not _PAGE_DIGITS.fullmatch(raw.strip()):
        return 0
    page = int(raw.strip())
    return page if page <= MAX_PAGE else 0


def _known(name: object, usable: tuple[str, ...]) -> str:
    """The usable column with this name (case-insensitive), or "" when it is not one."""
    if not isinstance(name, str):
        return ""
    wanted = name.strip().upper()
    return wanted if wanted in usable else ""


def _no_nul(text: str) -> bool:
    """A NUL in a value is never kept: it cannot be sent to the database as text, so the value is dropped."""
    return "\x00" not in text


def _spec_from_request(get, usable: tuple[str, ...]) -> Spec:
    """The Spec the address asks for. Unknown columns, ops and directions, NUL values and the group name N are dropped
    here; the caller also round-trips the result through spec_from_json (bad numbers, long text)."""
    columns: list[str] = []
    for raw in get.getlist("cols"):
        columns.extend(name for name in (_known(part, usable) for part in raw.split(",")) if name)

    sort: list[tuple[str, str]] = []
    for raw in get.getlist("sort"):
        name, _sep, direction = raw.partition(":")
        column = _known(name, usable)
        direction = direction.strip().lower()
        if column and direction in ("asc", "desc") and column not in dict(sort) and len(sort) < MAX_SORTS:
            sort.append((column, direction))

    filters: list[Filter] = []
    for raw in get.getlist("f"):
        parts = raw.split("|", 2)  # a value may itself contain "|": only the first two are separators
        column = _known(parts[0], usable) if len(parts) == 3 else ""
        if column and parts[1] in OPS and _no_nul(parts[2]):
            filters.append(Filter(column, parts[1], parts[2]))
    # The filter form's own fields add one filter: column, operator and value.
    added = _known(get.get("fcol"), usable)
    added_value = get.get("fval", "")
    if added and get.get("fop", "") in OPS and _no_nul(added_value):
        filters.append(Filter(added, get.get("fop", ""), added_value))

    group = _known(get.get("group", ""), usable)
    if group == COUNT_NAME:  # the count uses that name, so it cannot be grouped
        group = ""
    return Spec(
        columns=tuple(dict.fromkeys(columns)),
        filters=tuple(filters[:MAX_FILTERS]),
        sort=tuple(sort),
        group_by=group,
    )


def _effective_spec(get, saved: str, columns: tuple[str, ...], usable: tuple[str, ...]) -> Spec:
    """The Spec a table address or an export address means: the parameters in the address when it names any, else the
    saved settings. Dropped what the saved SQL does not have, as the table pane does."""
    if any(name in get for name in TABLE_PARAMS):
        spec = _spec_from_request(get, usable)
    else:
        spec = spec_from_json(saved, columns)
    return spec_from_json(spec_to_json(spec), columns)  # drops what the saved SQL does not have, bad numbers, long text


def _pairs(spec: Spec, skip: str = "") -> list[tuple[str, str]]:
    """The spec as address parameters, leaving out the group named by `skip` ("sort", "f", "cols" or "group")."""
    pairs: list[tuple[str, str]] = []
    if skip != "sort":
        pairs += [("sort", f"{name}:{direction}") for name, direction in spec.sort]
    if skip != "f":
        pairs += [("f", f"{item.column}|{item.op}|{item.value}") for item in spec.filters]
    if skip != "cols" and spec.columns:
        pairs.append(("cols", ",".join(spec.columns)))
    if skip != "group" and spec.group_by:
        pairs.append(("group", spec.group_by))
    return pairs


@dataclass(frozen=True)
class _Source:
    """What a table pane is built from: a workspace tab ("ws") or, later, a saved table ("saved"). `kind` is the URL
    name prefix of the table, excel, print and copy addresses."""

    kind: str
    pk: int
    title: str
    version: Any  # has .sql, .labels, .settings (WorkspaceVersion or SavedTable); None for an empty tab
    persist: bool  # True: the effective spec is written back to the version (workspace only)
    tab: Any = None  # the WorkspaceTab for kind "ws", else None (templates read it)


def _tab_source(tab: WorkspaceTab) -> _Source:
    """The source of a workspace tab: its current version, and the spec is saved back to it."""
    return _Source(kind="ws", pk=tab.pk, title=tab.title, version=tab.current(), persist=True, tab=tab)


def _url(source: _Source, what: str) -> str:
    """The address of one of the source's views: what is "table", "excel", "print" or "copy"."""
    return reverse(f"assistant:{source.kind}_{what}", args=[source.pk])


def _table_url(source: _Source, spec: Spec, page: int = 0) -> str:
    """The table address for this spec and page. The page is always written, so every such address has a query
    string and the view never restores the saved settings for it."""
    query = urlencode(_pairs(spec) + [("page", str(page))])
    return f"{_url(source, 'table')}?{query}"


def _export_query(spec: Spec) -> str:
    """The query string of the export addresses (Excel, print, copy): the spec's parameters and page 0, so the file
    never restores saved settings on its own. Export ignores the page; it is written only to match the table."""
    return urlencode(_pairs(spec) + [("page", "0")])


def _model_labels(text: str) -> dict[str, str]:
    """The headings the model gave for a version's columns (WorkspaceVersion.labels, JSON text), upper-case name ->
    heading. Anything that is not a JSON object of text values gives {}; never raises."""
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {key.upper(): value for key, value in data.items() if isinstance(key, str) and isinstance(value, str)}


def _names(user: User, sql: str, columns: tuple[str, ...], model_labels: str = "") -> dict[str, str]:
    """Upper-case column name -> the text the page shows for it: the Mongolian label of a governed view column, else
    the heading the model gave for the version (model_labels), else the column name (ws_labels). A reviewed view label
    wins over the model's. Display only; addresses and form values keep the column name. A failure here never
    breaks the table: the names are shown instead."""
    try:
        labels = {**_model_labels(model_labels), **view_labels(_catalogue_views(user), sql)}
        return display_names(columns, labels)
    except Exception as exc:
        logger.warning("workspace labels failed: %s", type(exc).__name__)
        return {name.upper(): name for name in columns}


def _shown(names: dict[str, str], column: str) -> str:
    """The text shown for a column: its label when it has one, else the name as given."""
    return names.get(column.upper(), column)


def _header_texts(columns: tuple[str, ...], names: dict[str, str], grouped: bool) -> list[str]:
    """The header line of a result (print, Excel, copy): labels, and «Тоо» for the count column of a grouped table."""
    return [COUNT_LABEL if grouped and name.upper() == COUNT_NAME else _shown(names, name) for name in columns]


def _filter_label(item: Filter, names: dict[str, str]) -> str:
    """One filter in words, as the chip shows it: «столбец нөхцөл «утга»»."""
    return f"{_shown(names, item.column)} {OP_LABELS.get(item.op, item.op)}" + (
        "" if item.op in ("empty", "notempty") else f" «{item.value}»"
    )


def _print_lines(spec: Spec, names: dict[str, str]) -> list[str]:
    """The filters, sort and grouping of a spec as lines for the print page."""
    lines = [f"Шүүлтүүр: {_filter_label(item, names)}" for item in spec.filters]
    if spec.sort:
        words = [
            f"{_shown(names, name)} ({'өсөх' if direction == 'asc' else 'буурах'})" for name, direction in spec.sort
        ]
        lines.append("Эрэмбэ: " + ", ".join(words))
    if spec.group_by:
        lines.append(f"Бүлэглэх: {_shown(names, spec.group_by)}")
    return lines


def _cell(value: object) -> dict[str, object]:
    """One table cell: None is an empty cell; numbers are right-aligned by the template."""
    numeric = isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    return {"text": "" if value is None else str(value), "numeric": numeric}


def _cells(row: Sequence[object], labels: Sequence[str] = ()) -> list[dict[str, object]]:
    """One table row: the cells, each told whether the cell before it is a number (that column gets left padding, so a
    right-aligned number does not touch the next column; UI_RULES 4)."""
    cells = [_cell(value) for value in row]
    for index, cell in enumerate(cells):  # the label is what a row shows in front of the value on a phone (card form)
        if index < len(labels):
            cell["label"] = labels[index]
    for before, cell in zip(cells, cells[1:], strict=False):
        cell["after_number"] = bool(before["numeric"])
    return cells


def _reason_line(status: str, reason: str) -> str:
    """The Mongolian line for a run that is not ok. ws_run's reasons are English and may echo viewer text, so they are
    never shown; "unavailable" is split into «no views» and «not ready» by the reason's own constant."""
    if status == "unavailable" and reason == sqlanswer.NO_VIEWS_REASON:
        return TABLE_REASONS["no_views"]
    return TABLE_REASONS.get(status, TABLE_REASONS["refused"])


def _line_context(source: _Source, line: str) -> dict[str, object]:
    """A pane with one line and no table, no controls."""
    return {
        "tab": source.tab,
        "source": source,
        "table_url": _url(source, "table"),
        "status_line": line,
        "controls": False,
        "headers": [],
        "rows": [],
        "cut": False,
        "paging": False,
        "unusable": 0,
    }


def _controls_context(
    source: _Source, spec: Spec, usable: tuple[str, ...], unusable: int, names: dict[str, str]
) -> dict[str, object]:
    """The toolbar, chips and form addresses for this spec. Built even when the run is refused, so the viewer can
    always clear the filters from the pane. The export addresses carry the same spec (all rows, not the page).
    Every choice carries the column name (the form value) and its label (the text shown)."""
    export = _export_query(spec)
    return {
        "tab": source.tab,
        "source": source,
        "table_url": _url(source, "table"),
        "controls": True,
        "unusable": unusable,
        "column_options": [{"name": name, "label": _shown(names, name)} for name in usable],
        "has_state": bool(spec.filters or spec.sort or spec.columns or spec.group_by),
        "clear_url": _table_url(source, Spec()),
        "excel_url": f"{_url(source, 'excel')}?{export}",
        "print_url": f"{_url(source, 'print')}?{export}",
        "copy_url": f"{_url(source, 'copy')}?{export}",
        "filters": [
            {
                "label": _filter_label(item, names),
                "remove_url": _table_url(source, replace(spec, filters=spec.filters[:i] + spec.filters[i + 1 :])),
            }
            for i, item in enumerate(spec.filters)
        ],
        "op_choices": list(OP_LABELS.items()),
        "column_choices": [
            {"name": name, "label": _shown(names, name), "checked": not spec.columns or name in spec.columns}
            for name in usable
        ],
        "group_choices": [
            {"name": name, "label": _shown(names, name), "selected": name == spec.group_by} for name in usable
        ],
        "keep_filter": _pairs(spec) + [("page", "0")],
        "keep_cols": _pairs(spec, "cols") + [("page", "0")],
        "keep_group": _pairs(spec, "group") + [("page", "0")],
        # Only a workspace tab can be saved as a saved table; the saved page has no save pop-up.
        "save_url": reverse("assistant:ws_save_table", args=[source.pk]) if source.kind == "ws" else "",
        "keep_all": _pairs(spec),
    }


def _plain_context(source: _Source, user: User, sql: str, unusable: int, labels: str = "") -> dict[str, object]:
    """The rows of a result with no column a tool can use: shown with no controls and no paging, at most PAGE_SIZE."""
    result = ws_run.run_base(user, sql)
    if result.status != "ok":
        return _line_context(source, _reason_line(result.status, result.reason))
    names = _names(user, sql, result.columns, labels)
    return {
        **_line_context(source, ""),
        "headers": [
            {"name": name, "label": _shown(names, name), "sort_url": "", "mark": "", "mark_title": ""}
            for name in result.columns
        ],
        "rows": [_cells(row, [_shown(names, name) for name in result.columns]) for row in result.rows],
        "cut": result.cut,
        "unusable": unusable,
    }


def _nothing_to_clear(spec: Spec) -> bool:
    """True when no tool is applied: nothing for the viewer to clear."""
    return not (spec.filters or spec.sort or spec.columns or spec.group_by)


def _falls_back(status: str, spec: Spec) -> bool:
    """The one fallback rule of the table and of the exports: a REFUSED wrapped run with no tool applied shows the saved
    query's own rows. off, unavailable and no-views never fall back: they give their line, never rows."""
    return status == "refused" and _nothing_to_clear(spec)


def _table_context(request: HttpRequest, user: User, source: _Source) -> dict[str, object]:
    """Everything the table pane shows. Runs the source's current SQL through ws_run (base columns, one page, the
    total). The effective spec is saved on the current version only after the page run is ok, and only when the
    source persists (a workspace tab)."""
    version = source.version
    if version is None:
        return {**_line_context(source, ""), "empty_note": EMPTY_TAB_TEXT}

    base = ws_run.base_columns(user, version.sql)
    if base.status != "ok":
        return _line_context(source, _reason_line(base.status, base.reason))

    columns = base.columns
    usable = usable_columns(columns)
    unusable = len(columns) - len(usable)
    if not usable:
        return _plain_context(source, user, version.sql, unusable, version.labels)

    # Only the known parameters count as "params given"; a stray one (a cache-buster) must not stop the restore.
    spec = _effective_spec(request.GET, version.settings, columns, usable)
    text = spec_to_json(spec)
    names = _names(user, version.sql, columns, version.labels)

    page = _page_param(request.GET.get("page"))
    result = ws_run.run_page(user, version.sql, columns, spec, page)
    if result.status != "ok":
        if _falls_back(result.status, spec):
            # Nothing to clear: the wrapped run failed on a result the saved query itself can show. Show its rows.
            plain = _plain_context(source, user, version.sql, unusable, version.labels)
            if not plain["status_line"]:
                return plain
        return {
            **_controls_context(source, spec, usable, unusable, names),
            "status_line": _reason_line(result.status, result.reason),
            "headers": [],
            "rows": [],
            "cut": False,
            "paging": False,
        }
    if source.persist and isinstance(version, WorkspaceVersion) and text != version.settings:
        # A guarded update: a version a concurrent undo has just deleted matches no row and raises nothing.
        WorkspaceVersion.objects.filter(pk=version.pk).update(settings=text)
    total = ws_run.run_count(user, version.sql, columns, spec)

    grouped = bool(spec.group_by)
    sort_now = dict(spec.sort)
    headers = []
    for name in result.columns:
        upper = name.upper()
        sortable = upper in usable and not grouped
        current = sort_now.get(upper, "") if sortable else ""
        next_direction = "desc" if current == "asc" else "asc"
        headers.append(
            {
                "name": name,
                "label": COUNT_LABEL if grouped and upper == COUNT_NAME else _shown(names, name),
                "sort_url": _table_url(source, replace(spec, sort=((upper, next_direction),))) if sortable else "",
                "mark": {"asc": "↑", "desc": "↓"}.get(current, ""),
                "aria_sort": {"asc": "ascending", "desc": "descending"}.get(current, ""),
                "mark_title": {"asc": "өсөхөөр", "desc": "буурахаар"}.get(current, ""),
            }
        )

    shown = [_cells(row, [str(header["label"]) for header in headers]) for row in result.rows]
    # A header sits like its cells: right-aligned over numbers, padded after a number column (UI_RULES 4).
    for index, header in enumerate(headers):
        header["numeric"] = any(index < len(row) and row[index]["numeric"] for row in shown)
        header["after_number"] = index > 0 and bool(headers[index - 1]["numeric"])
    first = page * PAGE_SIZE + 1 if shown else 0
    last = page * PAGE_SIZE + len(shown)
    if total is not None:
        has_next = last < total
    else:
        has_next = len(shown) == PAGE_SIZE

    return {
        **_controls_context(source, spec, usable, unusable, names),
        "status_line": "",
        "headers": headers,
        "rows": shown,
        "cut": False,
        "total": total,
        "unit": "бүлэг" if grouped else "мөр",
        "first": first,
        "last": last,
        "paging": True,
        "prev_url": _table_url(source, spec, page - 1) if page > 0 else "",
        "next_url": _table_url(source, spec, page + 1) if has_next else "",
    }


@login_required
@require_GET
def ws_table(request: HttpRequest, pk: int) -> HttpResponse:
    """The table pane of one of the viewer's tabs. An htmx request gets the pane alone; a plain request (no script)
    gets the whole workspace page with the pane in it, so the links still work."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    source = _tab_source(tab)
    context = _table_context(request, user, source)
    # A back or forward step restores the pushed address with HX-History-Restore-Request: that is a whole page to
    # draw, not a fragment for the pane.
    fragment = (
        request.headers.get("HX-Request") == "true" and request.headers.get("HX-History-Restore-Request") != "true"
    )
    if fragment:
        return render(request, "assistant/_ws_table.html", context)
    return render(
        request,
        "assistant/workspace.html",
        {"tabs": tabs_of(user), "current": tab, "max_tabs": MAX_TABS, "table": True, **context},
    )


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TEXT_TYPE = "text/plain; charset=utf-8"
EXPORT_REFUSED = 409  # an export that cannot run answers with its Mongolian line (plain text) and no file


@dataclass(frozen=True)
class _Export:
    result: ws_run.RunResult
    cut: bool  # True when the rows stop at EXPORT_MAX_ROWS (or PAGE_SIZE for a result with no usable column)
    spec: Spec
    line: str  # the Mongolian refusal line when the run is not ok; "" when there are rows to write
    names: dict[str, str] = field(default_factory=dict)  # upper-case column name -> the text shown (see _names)

    def headers(self) -> list[str]:
        """The header line of the file or page: the same texts as the table's headers."""
        return _header_texts(self.result.columns, self.names, bool(self.spec.group_by))


def _plain_export(user: User, sql: str, labels: str = "") -> _Export:
    """The saved query's own rows up to EXPORT_MAX_ROWS, with no tool applied, through run_base. Used when no column is
    usable, and as the fallback of an empty spec whose wrapped run was refused."""
    plain = ws_run.run_base(user, sql, limit=EXPORT_MAX_ROWS, timeout_s=EXPORT_TIMEOUT_S)
    if plain.status != "ok":
        return _Export(plain, False, Spec(), _reason_line(plain.status, plain.reason))
    return _Export(plain, plain.cut, Spec(), "", _names(user, sql, plain.columns, labels))


def _export(request: HttpRequest, user: User, source: _Source) -> _Export:
    """Every row of the source's current version under the address's spec, up to EXPORT_MAX_ROWS. The same parsing and
    the same checks as the table pane; the page parameter is ignored and nothing is saved."""
    version = source.version
    if version is None:
        return _Export(ws_run.RunResult(status="refused"), False, Spec(), EMPTY_TAB_TEXT)
    base = ws_run.base_columns(user, version.sql)
    if base.status != "ok":
        return _Export(base, False, Spec(), _reason_line(base.status, base.reason))
    usable = usable_columns(base.columns)
    if not usable:  # no tool can name a column: the saved query's own rows
        return _plain_export(user, version.sql, version.labels)
    spec = _effective_spec(request.GET, version.settings, base.columns, usable)
    result, cut = ws_run.run_export(user, version.sql, base.columns, spec)
    if _falls_back(result.status, spec):  # the same fallback as the table pane
        return _plain_export(user, version.sql, version.labels)
    if result.status != "ok":
        return _Export(result, False, spec, _reason_line(result.status, result.reason))
    return _Export(result, cut, spec, "", _names(user, version.sql, base.columns, version.labels))


def _attachment(source: _Source, ext: str) -> str:
    """The Content-Disposition of a download named after the source. The title is cleaned first; the UTF-8 name is sent
    as filename*, with an ASCII name for old clients."""
    stem = file_stem(source.title)
    plain = ascii_stem(stem, f"{'workspace' if source.kind == 'ws' else 'saved'}-{source.pk}")
    return f"attachment; filename=\"{plain}.{ext}\"; filename*=UTF-8''{quote(stem + '.' + ext)}"


@login_required
@require_GET
def ws_excel(request: HttpRequest, pk: int) -> HttpResponse:
    """The tab's rows as an .xlsx file: every row under the address's sort, filters and columns, up to EXPORT_MAX_ROWS.
    A file cut at the ceiling says so in its first row. A refused run gives no file, only the Mongolian line (409)."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    source = _tab_source(tab)
    export = _export(request, user, source)
    if export.line:
        return HttpResponse(export.line, status=EXPORT_REFUSED, content_type=TEXT_TYPE)
    body = ws_excel_bytes(export.headers(), export.result.rows, source.title, cut=export.cut)
    response = HttpResponse(body, content_type=XLSX_TYPE)
    response["Content-Disposition"] = _attachment(source, "xlsx")
    return response


@login_required
@require_GET
def ws_print(request: HttpRequest, pk: int) -> HttpResponse:
    """The print page of the tab: its filters, then every row up to EXPORT_MAX_ROWS. The page asks the browser to print
    on load. A refused run answers with the Mongolian line (409) and no page."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    source = _tab_source(tab)
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
def ws_copy(request: HttpRequest, pk: int) -> HttpResponse:
    """All the rows of the tab as tab-separated text with the header line, for the clipboard (the «Бүх N мөр» copy).
    The header X-Cut is 1 when the rows stop at the ceiling. A refused run answers with the Mongolian line (409)."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    source = _tab_source(tab)
    export = _export(request, user, source)
    if export.line:
        return HttpResponse(export.line, status=EXPORT_REFUSED, content_type=TEXT_TYPE)
    response = HttpResponse(ws_tsv_text(export.headers(), export.result.rows), content_type=TEXT_TYPE)
    if export.cut:
        response["X-Cut"] = "1"
    return response


def _chat_context(tab: WorkspaceTab) -> dict[str, object]:
    """Everything the chat pane shows: the stored lines oldest first, the current version's SQL (folded away), whether
    undo is offered (only with more than one version) and the addresses the form and the undo button post to."""
    version = tab.current()
    version_count = tab.versions.count()
    # «Зөв гэж тэмдэглэх» belongs to the answer this tab was opened from, so it is offered only while the table is still
    # that answer (one version): after a refinement the stored question no longer matches what the viewer sees.
    verify_id = tab.source_id if tab.source_id and version_count == 1 else None
    return {
        "verify_id": verify_id,
        "verified": bool(verify_id) and VerifiedQuery.objects.filter(source_id=verify_id).exists(),
        "tab": tab,
        "chat_messages": list(tab.messages.order_by("id")),
        "chat_sql": version.sql if version is not None else "",
        "can_undo": version_count > 1,
        "version_count": version_count,
        "ask_url": reverse("assistant:ws_ask", args=[tab.pk]),
        "undo_url": reverse("assistant:ws_undo", args=[tab.pk]),
    }


def _chat_response(
    request: HttpRequest, tab: WorkspaceTab, table_changed: bool, zero_rows: bool = False
) -> HttpResponse:
    """The chat fragment after a line or an undo. When the table may have changed, the table pane is told to reload.
    `zero_rows` adds the caution line for a refinement that left no rows."""
    response = render(request, "assistant/_ws_chat.html", {**_chat_context(tab), "zero_rows": zero_rows})
    if table_changed:
        response["HX-Trigger"] = "ws-table-changed"
    return response


def _chat_error(request: HttpRequest, tab: WorkspaceTab, message: str, status: int, draft: str = "") -> HttpResponse:
    """The chat fragment with one visible Mongolian error line, at an error status. htmx does not swap error statuses,
    so the header tells the ask form's before-swap hook (_ws_chat.html) to swap this fragment in anyway. `draft` is
    the line the viewer sent: it goes back into the box, so a refused line is not lost."""
    context = {**_chat_context(tab), "chat_error": message, "chat_draft": draft}
    response = render(request, "assistant/_ws_chat.html", context)
    response.status_code = status
    response[CHAT_ERROR_HEADER] = "1"
    return response


def _tab_title(tab: WorkspaceTab) -> str | None:
    """The tab's title as the database has it now (a first question renames the tab in another row write); None when
    the tab is gone."""
    return WorkspaceTab.objects.filter(pk=tab.pk).values_list("title", flat=True).first()


@login_required
@require_GET
def ws_chat(request: HttpRequest, pk: int) -> HttpResponse:
    """The chat pane of one of the viewer's tabs: the stored lines, the current SQL and the form."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    return render(request, "assistant/_ws_chat.html", _chat_context(tab))


@login_required
@require_POST
def ws_ask(request: HttpRequest, pk: int) -> HttpResponse:
    """One line from the viewer: the open tab's SQL is refined (or built, for an empty tab). The fragment is returned
    with the outcome line; a saved new version also reloads the table pane, and a new title reloads the page (the
    heading and the tab strip show the title)."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    text = request.POST.get("q", "").strip()
    if not text:
        return _chat_error(request, tab, CHAT_EMPTY_TEXT, 400)
    if len(text) > CHAT_MAX_CHARS:
        return _chat_error(request, tab, CHAT_TOO_LONG_TEXT, 400, draft=text)
    provider = get_provider()
    if provider is None:
        return _chat_error(request, tab, PROVIDER_LINE, 404, draft=text)
    title_before = _tab_title(tab)
    # refine_tab locks the tab's row and asks the model: it is called here, outside any transaction.atomic block.
    result = refine_tab(user, tab, text, timezone.localdate(), provider)
    saved = result.version is not None
    response = _chat_response(request, tab, table_changed=saved, zero_rows=saved and result.total == 0)
    title_after = _tab_title(tab)
    if title_after is not None and title_after != title_before:
        response["HX-Refresh"] = "true"
    return response


@login_required
@require_POST
def ws_undo(request: HttpRequest, pk: int) -> HttpResponse:
    """Go back one version of the tab (SQL and tool settings together). The table pane is reloaded only when a version
    was actually removed: a tab with one version has nothing to go back to. A real undo also stores one assistant
    line that says so, with the row count of the version that is current again."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    current = tab.current()
    before_pk = current.pk if current is not None else None
    after = undo(tab)
    removed = after is not None and after.pk != before_pk
    if after is not None and removed:
        note_undo(user, tab, after)
    return _chat_response(request, tab, table_changed=removed)


SAVE_NAME_TEXT = "Нэр оруулна уу."  # a saved table needs a name of 1 to 80 characters
SAVE_EMPTY_TEXT = "Хүснэгт хоосон байна."  # the tab has no SQL yet, so there is nothing to save
SAVED_TEXT = "Тайланд хадгаллаа."
SAVE_NAME_MAX = 80
SAVE_VISIBILITIES = ("shared", "private")


@login_required
@require_POST
def ws_save_table(request: HttpRequest, pk: int) -> HttpResponse:
    """Save the open tab as a saved table (SavedTable): its checked SQL, its labels and the table settings from the
    posted form (the tools in the pane). The viewer's own tab only. A blank name, an empty tab or a base run that is
    not ok saves nothing and says why on the tab; an unknown visibility is shared. Redirects to the saved page."""
    user = _gated_user(request)
    tab = get_object_or_404(WorkspaceTab, pk=pk, owner=user)
    tab_url = reverse("assistant:workspace_tab", args=[tab.pk])
    version = tab.current()
    if version is None:
        messages.error(request, SAVE_EMPTY_TEXT)
        return redirect(tab_url)
    name = request.POST.get("name", "").strip()
    if not 1 <= len(name) <= SAVE_NAME_MAX:
        messages.error(request, SAVE_NAME_TEXT)
        return redirect(tab_url)
    visibility = request.POST.get("visibility", "shared")
    if visibility not in SAVE_VISIBILITIES:
        visibility = "shared"
    base = ws_run.base_columns(user, version.sql)
    if base.status != "ok":
        messages.error(request, _reason_line(base.status, base.reason))
        return redirect(tab_url)
    spec = _effective_spec(request.POST, version.settings, base.columns, usable_columns(base.columns))
    table = SavedTable.objects.create(
        name=name,
        sql=version.sql,
        labels=version.labels,
        settings=spec_to_json(spec),
        author=user,
        visibility=visibility,
    )
    messages.success(request, SAVED_TEXT)
    return redirect("assistant:saved_page", pk=table.pk)
