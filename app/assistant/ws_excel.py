"""Files made from a workspace table: the Excel workbook, the copied text (tab-separated) and the safe file names.

Python, openpyxl and django.utils.timezone only, no HR import. The rows come from ws_run.run_export (or run_base); this
module only writes them. Text is always stored as text: a value that starts with = + - @ (or a tab or CR) is written
as a string cell, never a formula. openpyxl makes a formula of any "=..." string it is given, so the cell type is set
back to text after the value is assigned.
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone as dj_timezone
from openpyxl import Workbook
from openpyxl.cell import Cell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

MAX_WIDTH = 50  # characters; a wider column is capped so one long text does not make the sheet unreadable
MIN_WIDTH = 8
DATE_FORMAT = "yyyy-mm-dd"
BOLD = Font(bold=True)
SHEET_MAX = 31  # Excel's sheet-name limit
SHEET_ILLEGAL = re.compile(r"[\\/?*\[\]:]")  # characters Excel refuses in a sheet name
CONTROL = re.compile(r"[\x00-\x1f\x7f]")  # control characters: never in a sheet name or a copied cell
FORMULA_START = ("=", "+", "-", "@")  # a copied cell that starts with one of these becomes text (after cleaning)
# The edge characters a copied cell loses: one explicit set, identical to workspace.js (str.strip() defaults differ).
COPY_EDGE = " \t\r\n\u00a0\ufeff\u2028\u2029\x1c\x1d\x1e\x1f\x85"
FILE_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')  # characters a file name must not hold
CELL_MAX = 32767  # Excel's longest text in one cell
DEFAULT_SHEET = "Хүснэгт"
CUT_NOTE = "Эхний {n} мөрийг харуулав"  # the first row of a file cut at the export ceiling


def plain_title(title: str) -> str:
    """A tab title as page text: control characters removed (the print page shows it in its heading and <title>)."""
    return CONTROL.sub("", title)


def sheet_title(title: str) -> str:
    """The sheet name for a tab title: the characters Excel and openpyxl refuse removed (control characters too), at
    most 31 characters, never empty."""
    cleaned = ILLEGAL_CHARACTERS_RE.sub("", CONTROL.sub("", SHEET_ILLEGAL.sub("", title)))
    cleaned = cleaned.strip().strip("'")[:SHEET_MAX].strip()
    return cleaned or DEFAULT_SHEET


def file_stem(title: str, fallback: str = "workspace") -> str:
    """A file name without its extension, safe on Windows and in a Content-Disposition header."""
    cleaned = FILE_ILLEGAL.sub("", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")[:60].strip(" .")
    return cleaned or fallback


def ascii_stem(stem: str, fallback: str) -> str:
    """The plain-ASCII form of a file name, for the old filename= parameter (the browser reads filename* first)."""
    ascii_only = re.sub(r"[^A-Za-z0-9._-]+", "-", stem.encode("ascii", "ignore").decode("ascii")).strip("-.")
    return ascii_only or fallback


def cell_text(value: object) -> str:
    """Text for one cell: the value as text, control characters removed, at most the longest Excel text."""
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    return text[:CELL_MAX]


def _is_finite_number(value: object) -> bool:
    """A number Excel can hold: an int, a finite float or a finite Decimal. nan and inf are written as text instead."""
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Decimal):
        return value.is_finite()
    return isinstance(value, int)  # bool is an int too


def _put(ws, row: int, column: int, value: object, bold: bool = False) -> int:
    """Writes one value keeping its type (numbers stay numbers, dates stay dates, None stays empty). Returns the width
    the value takes as text, for sizing the column."""
    cell: Cell = ws.cell(row=row, column=column)
    if bold:
        cell.font = BOLD
    if value is None:
        return 0
    if isinstance(value, datetime) and value.tzinfo is not None:
        # An Excel date has no zone: the time is converted to the zone the screen uses, then the zone is dropped.
        value = dj_timezone.localtime(value).replace(tzinfo=None)
    if isinstance(value, (date, datetime)):
        cell.value = value
        cell.number_format = DATE_FORMAT
        return len(value.isoformat())
    if _is_finite_number(value):
        cell.value = value
        return len(str(value))
    text = cell_text(value)
    cell.value = text
    cell.data_type = "s"  # a text cell: a value starting with = + - @ is never a formula
    return len(text)


def ws_excel_bytes(columns: Sequence[str], rows: Sequence[Sequence[object]], title: str, cut: bool = False) -> bytes:
    """The table as an .xlsx file: a bold header row, then the rows. When `cut` is True the first row is a note with
    how many rows the file holds (the export ceiling was reached)."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title(title)
    row = 1
    if cut:
        _put(ws, row, 1, CUT_NOTE.format(n=len(rows)))
        row += 1
    widths: dict[int, int] = {}
    for col, name in enumerate(columns, start=1):
        widths[col] = max(widths.get(col, 0), _put(ws, row, col, name, bold=True))
    row += 1
    for values in rows:
        for col, value in enumerate(values, start=1):
            widths[col] = max(widths.get(col, 0), _put(ws, row, col, value))
        row += 1
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = min(max(width, MIN_WIDTH) + 2, MAX_WIDTH)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def copy_clean(raw: str) -> str:
    """A copied cell cleaned: line breaks and tabs become spaces, then the edge characters of COPY_EDGE are removed.
    The same steps and the same character set are in app/static/js/workspace.js (cleanCell)."""
    return re.sub(r"[\t\r\n]+", " ", raw).strip(COPY_EDGE)


def formula_safe(text: str) -> str:
    """The cleaned copied text, with one single quote in front when it starts with = + - or @: Excel would read the
    paste as a formula. Applied to the cleaned text, so no whitespace or line break can hide the start."""
    return "'" + text if text[:1] in FORMULA_START else text


def _tsv_cell(value: object) -> str:
    """A copied cell: empty for None, one line only (a tab or a line break would split the paste), never a formula."""
    if value is None:
        return ""
    return formula_safe(copy_clean(str(value)))


def ws_tsv_text(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """The header and the rows as tab-separated text, one line each, for the clipboard."""
    lines = ["\t".join(_tsv_cell(name) for name in columns)]
    lines += ["\t".join(_tsv_cell(value) for value in values) for values in rows]
    return "\n".join(lines)
