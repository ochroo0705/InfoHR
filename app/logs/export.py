"""The Excel files of the two log pages (UI_RULES §4b): the same filtered rows as the screen, one per sheet.

The workbook is written in write-only mode and each row is streamed from the database, so 100,000 rows never sit in
memory as cells or model objects. Every value is stored as text, so a message starting with "=" is never a formula.
"""

import io
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from accounts.audit import ACTIONS, Category
from accounts.models import SystemLogEntry
from django.db.models import Model, QuerySet
from django.http import HttpResponse
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind
from openpyxl import Workbook
from openpyxl.cell import Cell, WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

from logs.employee_query import EmployeeLogFilter
from logs.system_query import SystemLogFilter

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ROW_LIMIT = 100_000  # rows one file holds; a longer list is cut and says so on its last line
CHUNK = 500  # rows fetched from the database at a time
SHEET = "Бүртгэл"
BOLD = Font(bold=True)
EMPTY = "(хоосон)"
EMPLOYEE_HEADERS = ["Огноо", "Хэн", "Ажилтан", "Код", "Төрөл", "Мессеж", "Өөрчлөлт"]
EMPLOYEE_WIDTHS = [18, 22, 28, 12, 16, 60, 60]
SYSTEM_HEADERS = ["Огноо", "Хэн", "Ангилал", "Үйлдэл", "Зорилт", "Дэлгэрэнгүй", "IP"]
SYSTEM_WIDTHS = [18, 22, 18, 30, 30, 60, 16]

T = TypeVar("T", bound=Model)


@dataclass
class Tally:
    """What one export wrote: the number of data rows (the row limit's last line is not counted)."""

    rows: int = 0


def capped_rows(entries: QuerySet[T], to_row: Callable[[T], list[str]], tally: Tally) -> Iterator[list[str]]:
    """The rows of `entries` as text, streamed in chunks; past ROW_LIMIT one last line says the list was cut."""
    for entry in entries.iterator(chunk_size=CHUNK):
        if tally.rows >= ROW_LIMIT:  # read at call time, so a test can lower the limit
            yield [f"Хязгаарласан: эхний {ROW_LIMIT} мөрийг татсан"]
            return
        tally.rows += 1
        yield to_row(entry)


def _text_cell(ws: WriteOnlyWorksheet, text: str, *, bold: bool = False) -> Cell:
    """One cell holding `text` as text: a value starting with "=" stays a string, never a formula."""
    cell = WriteOnlyCell(ws, value=ILLEGAL_CHARACTERS_RE.sub("", text))
    cell.data_type = "s"
    if bold:
        cell.font = BOLD
    return cell


def workbook_response(
    filename: str, headers: list[str], rows: Iterable[list[str]], widths: list[int] | None = None
) -> HttpResponse:
    """An .xlsx download: bold headers on row 1, then the rows. `widths` sets the column widths in characters."""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(SHEET)
    for col, width in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.append([_text_cell(ws, label, bold=True) for label in headers])
    for values in rows:
        ws.append([_text_cell(ws, value) for value in values])
    buffer = io.BytesIO()
    wb.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _value(value: object) -> str:
    """A change's old or new value as text; an empty one reads «(хоосон)», as on the screen."""
    if value is None or value == "":
        return EMPTY
    return str(value)


def changes_text(changes: object) -> str:
    """Every change as «Талбар: хуучин → шинэ», one per line."""
    if not isinstance(changes, list):
        return ""
    lines = []
    for change in changes:
        if isinstance(change, dict):
            lines.append(f"{change.get('field', '')}: {_value(change.get('old'))} → {_value(change.get('new'))}")
    return "\n".join(lines)


def _when(value: datetime) -> str:
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def employee_row(entry: ActivityEntry) -> list[str]:
    by = (entry.by.get_full_name() or entry.by.username) if entry.by is not None else "Систем"
    return [
        _when(entry.at),
        by,
        f"{entry.employee.family_name} {entry.employee.given_name}",
        entry.employee.code or "",
        entry.get_kind_display(),
        entry.message,
        changes_text(entry.changes),
    ]


def system_row(entry: SystemLogEntry) -> list[str]:
    target = " ".join(part for part in (entry.target_type, entry.target_label) if part)
    details = "\n".join(part for part in (entry.message, changes_text(entry.changes)) if part)
    return [
        _when(entry.at),
        entry.actor_name or "Систем",
        dict(Category.choices).get(entry.category, entry.category),  # the field has no choices: map the code
        ACTIONS.get(entry.action, entry.action),
        target,
        details,
        entry.ip or "",
    ]


def _chosen(label: str) -> str:
    """A filter line that names no one: a person's name is never written into the log (the search text stays out)."""
    return f"{label}: сонгосон"


def employee_filter_label(f: EmployeeLogFilter) -> str:
    """The readable filter label for the system log. It names no person, so it is safe to store."""
    parts: list[str] = []
    if f.q:
        parts.append(_chosen("Хайлт"))
    if f.employee is not None or f.emp:
        parts.append(_chosen("Ажилтан"))
    if f.by:
        parts.append(_chosen("Хэн хийсэн"))
    if f.kinds:
        labels = dict(ActivityKind.choices)
        parts.append("Төрөл: " + ", ".join(labels.get(kind, kind) for kind in f.kinds))
    if f.area:
        parts.append(_chosen("Хэсэг"))
    if f.field:
        parts.append(_chosen("Талбар"))
    if f.date_from is not None or f.date_to is not None:
        start = f.date_from.isoformat() if f.date_from is not None else "…"
        end = f.date_to.isoformat() if f.date_to is not None else "…"
        parts.append(f"Хугацаа: {start} – {end}")
    if f.system_only:
        parts.append("Зөвхөн системийн үйлдэл")
    return "; ".join(parts) or "Бүгд"


def system_filter_label(f: SystemLogFilter) -> str:
    """The readable filter label for the system log. It names no person, so it is safe to store."""
    parts: list[str] = []
    if f.q:
        parts.append(_chosen("Хайлт"))
    if f.categories:
        labels = dict(Category.choices)
        parts.append("Ангилал: " + ", ".join(labels.get(c, c) for c in f.categories))
    if f.action:
        parts.append("Үйлдэл: " + ACTIONS.get(f.action, f.action))
    if f.by:
        parts.append(_chosen("Хэн хийсэн"))
    if f.target:
        parts.append(_chosen("Зорилт"))
    if f.ip:
        parts.append(f"IP: {f.ip}")
    if f.date_from is not None or f.date_to is not None:
        start = f.date_from.isoformat() if f.date_from is not None else "…"
        end = f.date_to.isoformat() if f.date_to is not None else "…"
        parts.append(f"Хугацаа: {start} – {end}")
    return "; ".join(parts) or "Бүгд"
