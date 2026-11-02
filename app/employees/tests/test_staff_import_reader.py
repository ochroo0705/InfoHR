import io
import re
import zipfile
from collections.abc import Sequence
from datetime import date, datetime

import pytest
from openpyxl import Workbook, load_workbook

from employees.staff_import.fields import FIELDS
from employees.staff_import.reader import MAX_BYTES, MAX_ROWS, ImportFileError, read_rows, sheet_names
from employees.staff_import.template import template_bytes

SHEET = "Ажилтан"
HEADING = ["Овог", "Нэр", "Утас"]


def _book(rows: Sequence[Sequence[object]], sheet: str = SHEET) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet
    for row in rows:
        ws.append(list(row))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_reads_headings_and_rows_with_real_row_numbers() -> None:
    data = _book([HEADING, ["Бат", "Дорж", "99112233"], ["Сара", "Энх", "88001122"], ["Ган", "Болд", "77665544"]])

    headings, rows = read_rows(data, SHEET)

    assert headings == HEADING
    assert [number for number, _ in rows] == [2, 3, 4]
    assert rows[0] == (2, ["Бат", "Дорж", "99112233"])


def test_blank_row_in_the_middle_is_dropped_but_numbering_keeps_real_rows() -> None:
    data = _book([HEADING, ["Бат", "Дорж", "1"], [None, None, None], ["Сара", "Энх", "2"]])

    _, rows = read_rows(data, SHEET)

    assert [number for number, _ in rows] == [2, 4]
    assert rows[1][1][0] == "Сара"


def test_trailing_blank_rows_are_dropped() -> None:
    data = _book([HEADING, ["Бат", "Дорж", "1"], [None, None, None], [None, None, None]])

    _, rows = read_rows(data, SHEET)

    assert [number for number, _ in rows] == [2]


def test_phone_typed_as_number_stays_numeric() -> None:
    data = _book([HEADING, ["Бат", "Дорж", 99112233]])

    _, rows = read_rows(data, SHEET)

    value = rows[0][1][2]
    assert isinstance(value, (int, float))
    assert value == 99112233


def test_dates_come_back_as_datetime() -> None:
    data = _book([HEADING, ["Бат", "Дорж", date(1990, 5, 1)]])

    _, rows = read_rows(data, SHEET)

    assert isinstance(rows[0][1][2], datetime)
    assert rows[0][1][2].date() == date(1990, 5, 1)


def test_error_cell_becomes_none() -> None:
    data = _book([HEADING, ["Бат", "Дорж", "#N/A"]])

    _, rows = read_rows(data, SHEET)

    assert rows[0][1][2] is None


def test_header_rows_takes_the_last_skipped_row_as_headings() -> None:
    data = _book([["Хэсэг", None, None], HEADING, ["Бат", "Дорж", "1"]])

    headings, rows = read_rows(data, SHEET, header_rows=2)

    assert headings == HEADING
    assert [number for number, _ in rows] == [3]


def test_example_row_marked_with_zhishee_is_skipped() -> None:
    data = _book([HEADING, ["Жишээ", "Бат", "1"], ["Сара", "Энх", "2"]])

    _, rows = read_rows(data, SHEET)

    assert [number for number, _ in rows] == [3]


def test_sheet_names_lists_the_sheets() -> None:
    assert sheet_names(_book([HEADING], sheet=SHEET)) == [SHEET]


def test_missing_sheet_raises_import_file_error() -> None:
    data = _book([HEADING, ["Бат", "Дорж", "1"]])

    with pytest.raises(ImportFileError):
        read_rows(data, "Бусад")


def test_not_an_xlsx_raises_import_file_error() -> None:
    with pytest.raises(ImportFileError):
        read_rows(b"not an xlsx", SHEET)


def test_empty_data_raises_import_file_error() -> None:
    with pytest.raises(ImportFileError):
        read_rows(_book([HEADING]), SHEET)


def test_over_max_rows_raises_and_max_rows_is_accepted() -> None:
    at_limit = _book([HEADING] + [["Бат", "Дорж", str(i)] for i in range(MAX_ROWS)])
    _, rows = read_rows(at_limit, SHEET)
    assert len(rows) == MAX_ROWS

    over = _book([HEADING] + [["Бат", "Дорж", str(i)] for i in range(MAX_ROWS + 1)])
    with pytest.raises(ImportFileError):
        read_rows(over, SHEET)


def test_over_max_bytes_is_rejected_before_opening() -> None:
    with pytest.raises(ImportFileError, match="5"):
        read_rows(b"x" * (MAX_BYTES + 1), SHEET)


def test_template_without_salary_has_no_salary_column() -> None:
    headings = _template_headings(template_bytes(False))

    assert "Цалин" not in headings
    assert "Банк" not in headings
    assert headings == [field.label for field in FIELDS if not field.needs_salary]


def test_template_with_salary_has_salary_column() -> None:
    headings = _template_headings(template_bytes(True))

    assert "Цалин" in headings
    assert headings == [field.label for field in FIELDS]


def test_template_read_back_has_no_data_rows() -> None:
    with pytest.raises(ImportFileError):
        read_rows(template_bytes(True), SHEET)


def _template_headings(data: bytes) -> list[object]:
    wb = load_workbook(io.BytesIO(data))
    try:
        ws = wb[SHEET]
        return [cell.value for cell in ws[1] if cell.value is not None]
    finally:
        wb.close()


def _with_dimension(data: bytes, ref: str) -> bytes:
    """The same workbook with the sheet's <dimension ref> tag replaced, as a file written by another tool may hold."""
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                content = re.sub(rb'<dimension ref="[^"]*"', f'<dimension ref="{ref}"'.encode(), content)
            target.writestr(name, content)
    source.close()
    return buffer.getvalue()


def test_small_dimension_tag_does_not_drop_data_rows() -> None:
    data = _book([HEADING, ["Бат", "Дорж", "1"], ["Сара", "Энх", "2"]])

    _, rows = read_rows(_with_dimension(data, "A1"), SHEET)

    assert [number for number, _ in rows] == [2, 3]
    assert rows[1][1][0] == "Сара"


def test_too_small_dimension_tag_keeps_every_row_of_a_five_row_sheet() -> None:
    data = _book([HEADING] + [["Бат", "Дорж", str(i)] for i in range(5)])

    _, rows = read_rows(_with_dimension(data, "A1:B2"), SHEET)

    assert [number for number, _ in rows] == [2, 3, 4, 5, 6]
    assert [cells[2] for _, cells in rows] == ["0", "1", "2", "3", "4"]


def test_truncated_sheet_xml_raises_import_file_error() -> None:
    data = _book([HEADING] + [["Бат", "Дорж", str(i)] for i in range(20)])
    source = zipfile.ZipFile(io.BytesIO(data))
    sheet_xml = source.read("xl/worksheets/sheet1.xml")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            content = sheet_xml[: len(sheet_xml) // 2] if name == "xl/worksheets/sheet1.xml" else source.read(name)
            target.writestr(name, content)
    source.close()

    with pytest.raises(ImportFileError, match="уншиж чадсангүй"):
        read_rows(buffer.getvalue(), SHEET)


def test_a_workbook_that_unpacks_to_over_100_mb_is_refused() -> None:
    """A small file can hide a huge sheet: the total uncompressed size is checked before the workbook is opened."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (101 * 1024 * 1024))
    with pytest.raises(ImportFileError, match="хэт том"):
        sheet_names(buffer.getvalue())
