"""The export files of a report, request-free: the whole report's Excel, the picked people's Excel and CSV, and the copy
text of their names. The Django views and the React export API both call these, so a rule has one home. Nothing here
reads a request or checks a right: the caller checks the user may open the report and may export it (or print, for the
copy), as the views did. Each file carries the audit action, label and row count the caller records with record_export.
"""

import re
from dataclasses import dataclass
from typing import Literal

from accounts.models import User
from django.core import signing
from django.utils import timezone

from reports import excel
from reports.csvout import csv_bytes
from reports.filters import Filters, describe
from reports.selection import Picked, SelectionError, subset
from reports.summary import summary_of
from reports.table import Table, allowed_columns, build_table
from reports.types import Column, Report

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv; charset=utf-8"
NO_NAME_COLUMN = "Нэр харуулах багана алга"  # the copy needs the report's name column, and the user may see it
# the print ticket is forged, expired or not this user's or report's
TICKET_INVALID = "Хэвлэх холбоос хүчингүй болсон. Дахин сонгоно уу."
TICKET_SALT = "reports.selected_print"  # keeps a print ticket from being read as any other signed value
TICKET_MAX_AGE = 600  # seconds a print ticket stays valid after it is made

# every character str.splitlines() breaks a line on, plus the tab: each becomes one space, so a person is one line
LINE_BREAKS = re.compile(r"[\t\n\r\x0b\x0c\x1c\x1d\x1e\x85  ]")


def _one_line(value: object) -> str:
    """A cell's text on one line: blank for None, and every tab or line break becomes a space."""
    return LINE_BREAKS.sub(" ", "" if value is None else str(value))


@dataclass(frozen=True)
class ExportFile:
    body: bytes
    content_type: str
    filename: str
    log_action: str  # the audit action: export_report or export_selected
    log_label: str  # the filter lines as one audit label
    rows: int  # the rows in the file


@dataclass(frozen=True)
class CopyResult:
    text: str  # one line per person: the name, and the work email after a tab when it may be seen
    count: int  # the lines in text
    dropped: int  # posted ids the user may not act on
    log_label: str  # the filter lines as one audit label


def _filter_lines(user: User, report: Report, table: Table) -> list[str]:
    """The filter lines the file shows."""
    labels = {c.key: c.label for c in allowed_columns(report, user)}
    return describe(table.filters, report.filters, labels=labels)


def _log_label(user: User, report: Report, table: Table) -> str:
    """The same filter lines as one audit label."""
    labels = {c.key: c.label for c in allowed_columns(report, user)}
    return "; ".join(describe(table.filters, report.filters, for_log=True, labels=labels))


def _with_note(lines: list[str], report: Report, table: Table) -> list[str]:
    """The filter lines with the report's grey note after them, when the report has one for these filters."""
    note = report.note(table.filters) if report.note is not None else ""
    return [*lines, note] if note else lines


def excel_file(user: User, report: Report, filters: Filters) -> ExportFile:
    """The Excel file of the report for these filters: the same visible columns, sort and groups as the screen, the
    grey note under the filter lines, and the summary as a second sheet for a chart or pivot address."""
    table = build_table(report, user, filters)
    lines = _with_note(_filter_lines(user, report, table), report, table)  # the note goes in the sheet too
    log_label = _log_label(user, report, table)
    today = timezone.localdate().isoformat()
    summary = summary_of(table)  # a chart or pivot address adds its numbers as a second sheet
    body = excel.workbook_bytes(report.title, lines, table, sheet=report.key, summary=summary)
    return ExportFile(
        body=body,
        content_type=XLSX,
        filename=f"{report.key}-{today}.xlsx",
        log_action="export_report",
        log_label=log_label,
        rows=table.count,
    )


def selected_file(user: User, report: Report, picked: Picked, kind: Literal["xlsx", "csv"]) -> ExportFile:
    """The picked people's rows as an Excel or CSV file: the screen's visible columns, no footer. The CSV is UTF-8 with
    a BOM and has no filter lines; the Excel file ends with the grey note when the report has one."""
    table = subset(picked.table, report, picked.ids)
    log_label = _log_label(user, report, table)
    today = timezone.localdate().isoformat()
    if kind == "csv":
        # csv_bytes writes the header and the rows only, never the filter lines, so none are built for it
        return ExportFile(
            body=csv_bytes([], table),
            content_type=CSV,
            filename=f"{report.key}-selected-{today}.csv",
            log_action="export_selected",
            log_label=log_label,
            rows=table.count,
        )
    lines = _with_note(_filter_lines(user, report, table), report, table)
    body = excel.workbook_bytes(report.title, lines, table, sheet=report.key)
    return ExportFile(
        body=body,
        content_type=XLSX,
        filename=f"{report.key}-selected-{today}.xlsx",
        log_action="export_selected",
        log_label=log_label,
        rows=table.count,
    )


def copy_columns(user: User, report: Report) -> tuple[Column, Column | None]:
    """The name column (required) and the email column (None when the user may not see it). Raises SelectionError
    with NO_NAME_COLUMN when the user may not see the name column; the caller checks this before picking anyone."""
    by_key = {c.key: c for c in allowed_columns(report, user)}
    name = by_key.get("name")
    if name is None:
        raise SelectionError(NO_NAME_COLUMN)
    return name, by_key.get("email")


def ticket_make(user: User, report_key: str, query: str, ids: list[str], all_: bool) -> str:
    """A signed, compressed ticket that carries a print selection (the report address, the ticked ids and `all`) for
    this user and report. ticket_read opens it again; it stays short even for 500 people."""
    return signing.dumps(
        {"u": user.pk, "k": report_key, "q": query, "i": ids, "a": all_},
        salt=TICKET_SALT,
        compress=True,
    )


def ticket_read(user: User, report_key: str, ticket: str, max_age: int = TICKET_MAX_AGE) -> tuple[str, list[str], bool]:
    """The (query, ids, all) a ticket made by ticket_make carries. Raises SelectionError with TICKET_INVALID when the
    signature is wrong, the ticket is older than max_age seconds, or it belongs to another user or report."""
    try:
        payload = signing.loads(ticket, salt=TICKET_SALT, max_age=max_age)
    except signing.BadSignature:  # SignatureExpired is a BadSignature too
        raise SelectionError(TICKET_INVALID) from None
    if not isinstance(payload, dict) or "u" not in payload or "k" not in payload:
        raise SelectionError(TICKET_INVALID)
    if payload["u"] != user.pk or payload["k"] != report_key:
        raise SelectionError(TICKET_INVALID)
    query, ids, all_ = payload.get("q"), payload.get("i"), payload.get("a")
    if not isinstance(query, str) or not isinstance(all_, bool):
        raise SelectionError(TICKET_INVALID)
    if not isinstance(ids, list) or not all(isinstance(pk, str) for pk in ids):
        raise SelectionError(TICKET_INVALID)
    return query, ids, all_


def selected_copy(user: User, report: Report, picked: Picked) -> CopyResult:
    """The picked people's names, one line each in report order, with the work email after a tab when the user may
    see the report's email column."""
    name, email = copy_columns(user, report)
    table = subset(picked.table, report, picked.ids)
    lines: list[str] = []
    for row in table.rows:
        line = _one_line(name.value(row))
        if email is not None:
            line += "\t" + _one_line(email.value(row))
        lines.append(line)
    return CopyResult(
        text="\n".join(lines),
        count=len(lines),
        dropped=picked.dropped,
        log_label=_log_label(user, report, table),
    )
