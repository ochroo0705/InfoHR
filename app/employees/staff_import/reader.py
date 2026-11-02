"""Reads the staff spreadsheet: the headings and the data rows of one sheet, each row with its Excel row number."""

import io
import zipfile
from typing import Any

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
EXAMPLE_MARK = "Жишээ"  # a row whose first cell is this is the example row of the template; it is never imported
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # old .xls files and password-protected .xlsx files start with this

NOT_XLSX = "Файл .xlsx хэлбэрээр байх ёстой. Энэ файлыг уншиж чадсангүй."
LOCKED_MESSAGE = (
    "Файл нууц үгтэй эсвэл хуучин .xls хэлбэртэй байна. Нууц үгийг арилгаад .xlsx хэлбэрээр дахин хадгална уу."
)
NO_DATA = "Файлд ажилтны мөр олдсонгүй."
MAX_UNPACKED = 100 * 1024 * 1024  # a small .xlsx can hide a huge sheet: the unpacked total is capped too


class ImportFileError(ValueError):
    """A file the importer cannot use. The message is Mongolian and shown to the user as it is."""


def _unpacked_size(data: bytes) -> int:
    """The total size of the parts of the file once unpacked (read from the zip directory, nothing is unpacked)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        return 0  # not a zip: load_workbook reports it as not an .xlsx file


def _open(data: bytes) -> Workbook:
    if len(data) > MAX_BYTES:
        raise ImportFileError(f"Файл хэт том байна. Дээд хэмжээ {MAX_BYTES // (1024 * 1024)} МБ.")
    if data.startswith(OLE_MAGIC):
        raise ImportFileError(LOCKED_MESSAGE)
    if _unpacked_size(data) > MAX_UNPACKED:
        raise ImportFileError(
            f"Файл хэт том байна. Задалсан хэмжээ {MAX_UNPACKED // (1024 * 1024)} МБ-аас ихгүй байна."
        )
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for corrupt input (zip, XML, styles); all mean the same
        raise ImportFileError(NOT_XLSX) from exc


def _value(cell: Any) -> object:
    """The cell's value, with an error cell (such as #N/A) turned into None."""
    if getattr(cell, "data_type", None) == "e":
        return None
    return cell.value


def _is_blank(values: list[object]) -> bool:
    return all(v is None or (isinstance(v, str) and not v.strip()) for v in values)


def _is_example(values: list[object]) -> bool:
    return isinstance(values[0], str) and values[0].strip() == EXAMPLE_MARK


def sheet_names(data: bytes) -> list[str]:
    """The names of the sheets in the file, in workbook order."""
    wb = _open(data)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def _read_sheet(wb: Workbook, sheet: str, header_rows: int) -> tuple[list[str], list[tuple[int, list[object]]]]:
    if sheet not in wb.sheetnames:
        raise ImportFileError(f"«{sheet}» хуудас файлд олдсонгүй.")
    ws = wb[sheet]
    # read-only mode trusts the file's <dimension> tag; a wrong (too small) tag would drop rows, so ignore it
    ws.reset_dimensions()

    headings: list[str] = []
    rows: list[tuple[int, list[object]]] = []
    for number, cells in enumerate(ws.iter_rows(), start=1):
        values = [_value(cell) for cell in cells]
        if number <= header_rows:
            headings = ["" if v is None else str(v) for v in values]
            continue
        if not values or _is_blank(values) or _is_example(values):
            continue
        rows.append((number, values))
        if len(rows) > MAX_ROWS:
            raise ImportFileError(f"Файлд {MAX_ROWS}-аас олон мөр байна. Хэсгүүдэд хувааж оруулна уу.")

    if not rows:
        raise ImportFileError(NO_DATA)
    return headings, rows


def read_rows(data: bytes, sheet: str, header_rows: int = 1) -> tuple[list[str], list[tuple[int, list[object]]]]:
    """The headings and the data rows of `sheet`.

    The headings are the last of the first `header_rows` rows, each cell as text. The data rows follow, as
    `(excel_row_number, cells)`: blank rows are left out, the example row is left out, and the numbers stay the
    real Excel row numbers. Cell values keep their Python types; an error cell becomes None.
    """
    wb = _open(data)
    try:
        return _read_sheet(wb, sheet, header_rows)
    except ImportFileError:
        raise
    except Exception as exc:  # a damaged sheet part fails while it is being parsed, not when it is opened
        raise ImportFileError(NOT_XLSX) from exc
    finally:
        wb.close()
