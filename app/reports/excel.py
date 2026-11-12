"""The Excel file of a report: the table the screen and the print show, with title, filter lines and total."""

import io
from datetime import date
from decimal import Decimal
from typing import cast

from openpyxl import Workbook
from openpyxl.cell import Cell as XlCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from reports import privacy
from reports.summary import Summary
from reports.table import Table

MAX_WIDTH = 50  # characters; a wider column is capped so one long text does not make the sheet unreadable
DATE_FORMAT = "yyyy-mm-dd"
BOLD = Font(bold=True)
SUMMARY_SHEET = "Нэгтгэл"  # the chart or pivot summary sheet, after the rows sheet


def _text(value: object) -> str:
    """The text a value takes in the sheet, used to size the columns."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _write(ws: Worksheet, row: int, column: int, value: object, bold: bool = False) -> None:
    """Writes one value keeping its type: numbers stay numbers, dates stay dates, blanks stay empty.
    Text is always stored as text, so a value starting with "=" never becomes a formula."""
    cell = cast(XlCell, ws.cell(row=row, column=column))  # a sheet written here has no merged cells
    if bold:
        cell.font = BOLD
    if value is None:
        return
    if isinstance(value, date):
        cell.value = value
        cell.number_format = DATE_FORMAT
    elif isinstance(value, (int, float, Decimal)):
        cell.value = value
    else:
        cell.value = ILLEGAL_CHARACTERS_RE.sub("", _text(value))  # control characters old MACS text may hold
        cell.data_type = "s"


def _size(ws: Worksheet, widths: list[int]) -> None:
    """Sets each column's width from its longest text, plus a margin, capped at MAX_WIDTH."""
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = min(width + 2, MAX_WIDTH)


def _summary_sheet(wb: Workbook, summary: Summary) -> None:
    """The second sheet of a chart or pivot address: the summary grid from row 3, and for a chart a drawing of it
    beside the grid, built from the cells just written so it stays in step with the sheet."""
    ws = cast(Worksheet, wb.create_sheet(SUMMARY_SHEET))
    _write(ws, 1, 1, summary.title, bold=True)
    widths = [len(_text(h)) for h in summary.head]
    for col, label in enumerate(summary.head, start=1):
        _write(ws, 3, col, label, bold=True)
    row = 4
    for line in summary.lines:
        for col, value in enumerate(line, start=1):
            _write(ws, row, col, value)
            widths[col - 1] = max(widths[col - 1], len(_text(value)))
        row += 1
    if summary.foot is not None:
        for col, value in enumerate(summary.foot, start=1):
            _write(ws, row, col, value, bold=True)
            widths[col - 1] = max(widths[col - 1], len(_text(value)))
        row += 1
    if summary.masked:  # the note sits in the row after the summary's last row, so the reader knows figures are missing
        _write(ws, row, 1, privacy.masked_note(privacy.min_group()))
    _size(ws, widths)
    if summary.kind == "pivot":
        return  # a pivot is a grid only
    last = 3 + len(summary.lines)  # the header row 3, then one row per category
    categories = Reference(ws, min_col=1, min_row=4, max_row=last)
    stacked = summary.kind == "stacked"
    # a stack is one series per column between the label and «Нийт»; a plain chart has the one value column
    value_cols = (2, len(summary.head) - 1) if stacked else (2, 2)
    drawing: BarChart | LineChart | DoughnutChart
    if summary.kind == "donut":
        drawing = DoughnutChart()
    elif summary.kind == "line":
        drawing = LineChart()
    else:
        bars = BarChart()
        if stacked:
            bars.grouping = "stacked"
            bars.overlap = 100
        drawing = bars
    values = Reference(ws, min_col=value_cols[0], max_col=value_cols[1], min_row=3, max_row=last)
    drawing.add_data(values, titles_from_data=True)
    drawing.set_categories(categories)
    drawing.title = summary.title
    ws.add_chart(drawing, f"{get_column_letter(len(summary.head) + 2)}3")


def workbook_bytes(
    title: str, lines: list[str], table: Table, *, sheet: str = "Тайлан", summary: Summary | None = None
) -> bytes:
    """The report as an .xlsx file. Row 1 the title, row 2 the filter lines, row 4 the headers, then the rows.
    When the table is grouped, a bold «label · N» row starts each group. The last row is the total.
    `sheet` names the sheet; the views pass the report key. A summary (a chart or pivot address) adds a second sheet."""
    wb = Workbook()
    ws = cast(Worksheet, wb.active)  # a new workbook always has its first sheet
    ws.title = sheet[:31]  # Excel's sheet-name limit
    _write(ws, 1, 1, title, bold=True)
    _write(ws, 2, 1, "; ".join(lines) or None)

    headers = [c.label for c in table.columns]
    widths = [len(h) for h in headers]
    for col, label in enumerate(headers, start=1):
        _write(ws, 4, col, label, bold=True)

    row = 5
    for label, rows in table.groups:
        if table.filters.group:
            _write(ws, row, 1, f"{label} · {len(rows)}", bold=True)
            row += 1
        for values in rows:
            for col, cell in enumerate(values, start=1):
                _write(ws, row, col, cell.value)
                widths[col - 1] = max(widths[col - 1], len(_text(cell.value)))
            row += 1
    if table.footer is not None:  # the totals row sits under the data, above the count line
        for col, cell in enumerate(table.footer, start=1):
            _write(ws, row, col, cell.value, bold=True)
            widths[col - 1] = max(widths[col - 1], len(_text(cell.value)))
        row += 1
    if table.shows_count:
        _write(ws, row, 1, f"Нийт: {table.count}")
    _size(ws, widths)
    if summary is not None:
        _summary_sheet(wb, summary)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
