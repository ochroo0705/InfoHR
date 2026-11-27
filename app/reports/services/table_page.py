"""The report page's table layout, request-free: the batch of rows, the header cells, each cell as text, the footer, the
rules and note, and the flags the page reads. The Django report page and the React API both call table_page(), so a
rule has one home. Nothing here reads a request: the caller passes the QueryDict, the path, the viewer and the offset.

What the function answers per layout:
- table: the header cells, the batch (or every row when grouped), the footer, and the flags of the table.
- any other layout: the header cells, the count, the filter bar, the rules, the note and the address. `groups` is [] and
  `footer` is None: the Django page draws those layouts from `table` (the layout's own rows), so no cell is converted.
  The batch offset is ignored for them, as the rows are not batched."""

from dataclasses import dataclass, replace
from datetime import date, datetime

from accounts.models import User
from config import batching
from django.http import QueryDict
from django.utils import timezone
from employees import access

from reports import corrections
from reports.filters import Filters, parse_filters, to_query
from reports.page_rules import HeaderCell
from reports.page_rules import address as page_address
from reports.page_rules import next_sort as page_next_sort
from reports.page_rules import sort_mark as page_sort_mark
from reports.services.edit_targets import EditFlags, EditTarget, edit_target, marks_of
from reports.services.filter_bar import FilterBar, bar_adds, filter_bar
from reports.table import Cell, Table, build_table, column_classes, pin_style
from reports.types import Report

CHECK_PINNED_CSS = "w-10 sticky z-10 bg-surface"  # the checkbox cell when columns are pinned (unpinned: w-10 only)
CHECK_PINNED_STYLE = "left: 0rem"
MAX_OFFSET_DIGITS = 18  # a longer offset is not a batch number: it starts at 0, as config.batching reads it


def parse_offset(raw: str) -> int:
    """The batch offset a query names, read the way config.batching.window reads it: digits only, at most 18 of them.
    Anything else (a sign, a superscript digit, a longer number, nothing) starts at 0."""
    return int(raw) if raw.isdecimal() and len(raw) <= MAX_OFFSET_DIGITS else 0


@dataclass(frozen=True)
class CellOut:
    """One cell as the page shows it. `text` is what the template prints: dates as ISO, blank for no value. For a money
    cell `value` is the raw number as text (the template formats it, e.g. «2,500,000₮»; the API leaves that to the
    client) and `money` is True. `text` is the same raw text for money cells."""

    text: str
    value: str | None
    money: bool
    href: str  # the link target, "" when the cell is not a link
    css: str  # the td's classes: alignment, colour and pinning (Cell.css)
    style: str  # the inline offset of a pinned cell, "" when not pinned
    person: int  # the employee id of the row (Report.person); 0 when the report has none
    edit: EditTarget | None = None  # the inline editor this cell opens for this viewer; None when it opens none


@dataclass(frozen=True)
class RowGroup:
    label: str  # "" when the rows are not grouped
    count: int  # the rows in this group as the answer carries them
    rows: list[list[CellOut]]


@dataclass(frozen=True)
class TablePage:
    filters: Filters  # the cleaned filters the table used
    query: str  # the cleaned filters as an address query
    address: str  # the report's address for these filters, with the picker's `add` chips
    heads: list[HeaderCell]
    groups: list[RowGroup]  # one group with label "" when not grouped
    next_offset: int | None  # the offset of the next batch; None when no batch follows
    count: int  # every filtered row, not only the batch
    shows_count: bool
    rules_text: str
    clear_rules_url: str
    note: str
    footer: list[CellOut] | None
    selectable: bool
    check_css: str
    check_style: str
    table_span: int  # the columns a full-width row spans (the checkbox column counts when selectable)
    pin: int
    can_edit_cells: bool  # the inline editors of the table cells (5f); False keeps the cell plain
    can_correct_cells: bool
    can_edit_rows: bool
    layout: str
    adds: list[str]  # the picker's `add` chips this user may use, with or without the bar
    bar: FilterBar | None  # None when the caller asked for no bar (with_bar=False: the batch answers)
    batched: bool  # True when the rows are one batch of an ungrouped table (the page's pill may follow)
    table: Table  # the page's own table (cells with their edit fields); the Django template draws from it
    edit_marks: list[str]  # the editor kinds the cells open, in legend order (edit_targets.EDIT_MARKS)


def _text(value: object) -> str:
    """What the template prints for a value: an ISO date, a blank for no value, else the value's text."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
    if isinstance(value, date):
        return f"{value:%Y-%m-%d}"
    return str(value)


def cell_out(cell: Cell, flags: EditFlags | None = None) -> CellOut:
    """One cell as the page shows it. With `flags` (the table page's rights) it also names its inline editor; without
    them (the print page) the cell opens none."""
    value = None if cell.value is None else _text(cell.value)
    return CellOut(
        text="" if value is None else value,
        value=value,
        money=cell.money,
        href=cell.href,
        css=cell.css,
        style=cell.sticky_left,
        person=cell.person,
        edit=None if flags is None else edit_target(cell, flags),
    )


def table_page(
    request_get: QueryDict, path: str, user: User, report: Report, offset: int, *, with_bar: bool = True
) -> TablePage:
    """The table layout of the report page for these filters, as this user may see it. `offset` is the batch the
    caller asks for (0 for the first); a negative or huge one starts at 0. A grouped table ignores it.
    `with_bar=False` skips the filter bar (its option lists are queries): `bar` is then None. `adds` is always set, so a
    batch answer still builds its addresses the same way."""
    table = build_table(report, user, parse_filters(request_get))
    f = table.filters
    start = offset if 0 <= offset < 10**MAX_OFFSET_DIGITS else 0
    batched = table.spec.layout == "table" and not f.group
    next_offset: int | None = None
    if batched:
        # the batch of the rows, and the offset of the one after it (config.batching.window_at, the same slice)
        shown, more = batching.window_at(table.groups[0][1], start)
        next_offset = start + batching.LIST_BATCH if more else None
        table.groups = [("", shown)]
    plain = bool(report.saved_views)  # an empty address then says view=plain, not the bare default-view address
    bar = filter_bar(request_get, path, user, report, table, plain) if with_bar else None
    table_layout = table.spec.layout == "table"
    # the rights of the inline editors, read once per page (the same expressions as the Django page's context)
    can_edit_cells = table_layout and (access.can_manage(user) or access.can_manage_salary(user))
    can_correct_cells = table_layout and corrections.enabled() and access.can_manage(user)
    can_edit_rows = table_layout and access.can_manage(user)
    flags = EditFlags(
        cells=can_edit_cells,
        plain=access.can_manage(user),
        salary=access.can_manage_salary(user),
        correct=can_correct_cells,
        correct_salary=can_correct_cells and access.can_manage_salary(user),
        rows=can_edit_rows,
    )
    adds = bar.adds if bar is not None else bar_adds(request_get, user, report)
    heads = []
    for i, (c, cls) in enumerate(zip(table.columns, column_classes(table.columns), strict=True)):
        heads.append(
            HeaderCell(
                label=c.label,
                href=page_address(path, replace(f, sort=page_next_sort(f.sort, c.key)), adds, plain=plain),
                append_href=page_address(
                    path, replace(f, sort=page_next_sort(f.sort, c.key, append=True)), adds, plain=plain
                ),
                arrow=page_sort_mark(f.sort, c.key),
                cls=cls,
                sticky_left=pin_style(i, table.pin, table.pin_base),
            )
        )
    selectable = report.person is not None and table_layout
    pinned = selectable and table.pin > 0
    # cells are converted for the table layout only: the other layouts' pages never read these rows here
    groups = (
        [
            RowGroup(label=label, count=len(rows), rows=[[cell_out(cell, flags) for cell in row] for row in rows])
            for label, rows in table.groups
        ]
        if table_layout
        else []
    )
    return TablePage(
        filters=f,
        query=to_query(f),
        address=page_address(path, f, adds, plain=plain),
        heads=heads,
        groups=groups,
        next_offset=next_offset,
        count=table.count,
        shows_count=table.shows_count,
        rules_text=table.rules_text,
        clear_rules_url=page_address(path, replace(f, rules=""), adds, plain=plain),
        note=report.note(f) if report.note is not None else "",
        footer=None if table.footer is None or not table_layout else [cell_out(cell, flags) for cell in table.footer],
        selectable=selectable,
        check_css=CHECK_PINNED_CSS if pinned else "w-10",
        check_style=CHECK_PINNED_STYLE if pinned else "",
        table_span=len(heads) + (1 if selectable else 0),
        pin=table.pin,
        can_edit_cells=can_edit_cells,
        can_correct_cells=can_correct_cells,
        can_edit_rows=can_edit_rows,
        layout=table.spec.layout,
        adds=adds,
        bar=bar,
        batched=batched,
        table=table,
        edit_marks=marks_of(out.edit for group in groups for row in group.rows for out in row),
    )
