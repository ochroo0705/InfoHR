"""The CSV file of a report's table: the shown column labels as the header row, then the rows as the screen shows."""

import csv
import io
from datetime import date
from decimal import Decimal

from employees.templatetags.hr import mnt

from reports.table import Cell, Table

FORMULA_START = (
    "=",
    "+",
    "-",
    "@",
    "\t",
    "\r",
)  # a text cell starting with these may run as a formula in a spreadsheet


def _text(cell: Cell) -> str:
    """The text a cell takes on screen: money with ₮, dates as Y-m-d, blanks empty, the rest as text."""
    value = cell.value
    if cell.money:
        return "" if value is None else mnt(value if isinstance(value, Decimal) else str(value))
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    text = str(value)
    return "'" + text if text.startswith(FORMULA_START) else text  # a neutral quote keeps it text in Excel


def csv_bytes(lines: list[str], table: Table) -> bytes:
    """The table as CSV: UTF-8 with a BOM so Excel reads Mongolian text, a header row of the shown column labels,
    then one row per person in table order. No footer. `lines` (the filter lines) are not written."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([c.label for c in table.columns])
    for _, rows in table.groups:
        for row in rows:
            writer.writerow([_text(cell) for cell in row])
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
