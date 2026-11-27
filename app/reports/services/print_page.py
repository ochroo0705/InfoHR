"""The print page of a report, request-free: the filter lines, the note, the table's header and rows, the footer, the
summary a chart or pivot adds, and the flags the page reads. The Django print view and the React print API both call
build_print(), so a rule has one home. Nothing here reads a request: the caller passes the user, the report and the
parsed filters. The caller checks the user may open the report (registry.can_open) before calling.

`only` prints a subset of the people (the selection's print): the rows are cut with selection.subset, the footer is
dropped (its totals would count everyone), and no summary is added."""

from collections.abc import Collection
from dataclasses import dataclass

from accounts.models import User
from django.utils import timezone
from employees.models import CompanySettings

from reports import privacy
from reports.filters import Filters, describe
from reports.selection import subset
from reports.services.table_page import CellOut, cell_out
from reports.summary import Summary, summary_of
from reports.table import Table, allowed_columns, build_table, column_classes
from reports.types import Report

MAX_PORTRAIT_COLUMNS = 7  # more columns than this print on A4 landscape


@dataclass(frozen=True)
class PrintGroup:
    label: str  # "" when the rows are not grouped
    rows: list[list[CellOut]]


@dataclass(frozen=True)
class PrintPage:
    title: str  # the report's title
    company: str  # the company's name, from the company settings
    today: str  # the print date, ISO (YYYY-MM-DD)
    printed_by: str  # the viewer's full name, else the user name
    lines: list[str]  # the filter lines, in the report's order
    note: str  # the report's grey note for these filters; "" when none
    landscape: bool  # more columns than MAX_PORTRAIT_COLUMNS
    heads: list[tuple[str, str]]  # (label, class) of each shown column
    groups: list[PrintGroup]  # one group with label "" when not grouped
    footer: list[CellOut] | None  # the footer totals; None when there are none or the print is a subset
    count: int  # every filtered row, not only the rows printed on the page
    shows_count: bool  # the table's «Нийт: N» line is drawn (the printed table's flag; a subset keeps it)
    grouped: bool  # True when the table is grouped (each group has a heading row)
    summary: Summary | None  # the chart or pivot numbers; None for a table address and for a subset
    min_group: int  # the smallest group whose money is shown; the note under the summary says so
    log_label: str  # the filter lines as one audit label
    table: Table  # the table the print was built from; the Django template draws its cells (reports/print.html)


def build_print(
    user: User,
    report: Report,
    filters: Filters,
    *,
    only: Collection[int] | None = None,
    table: Table | None = None,
) -> PrintPage:
    """The print page of the report for these filters, as this user may see it. `only` keeps the people with these
    employee ids (in report order); None prints everyone. `table` is the report already built for these filters (the
    selection's picked table); given, it is used instead of building the table again."""
    if table is None:
        table = build_table(report, user, filters)
    if only is not None:
        table = subset(table, report, only)
    labels = {c.key: c.label for c in allowed_columns(report, user)}
    return PrintPage(
        title=report.title,
        company=CompanySettings.get().name,
        today=timezone.localdate().isoformat(),
        printed_by=user.get_full_name() or user.get_username(),
        lines=describe(table.filters, report.filters, labels=labels),
        note=report.note(table.filters) if report.note is not None else "",
        landscape=len(table.columns) > MAX_PORTRAIT_COLUMNS,
        heads=[(c.label, cls) for c, cls in zip(table.columns, column_classes(table.columns), strict=True)],
        groups=[
            PrintGroup(label=label, rows=[[cell_out(cell) for cell in row] for row in rows])
            for label, rows in table.groups
        ],
        footer=None if table.footer is None else [cell_out(cell) for cell in table.footer],
        count=table.count,
        shows_count=table.shows_count,
        grouped=bool(table.filters.group),
        summary=None if only is not None else summary_of(table),  # a chart or pivot address adds its numbers
        min_group=privacy.min_group(),
        log_label="; ".join(describe(table.filters, report.filters, for_log=True, labels=labels)),
        table=table,
    )
