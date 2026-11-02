import io
import time
from datetime import date, timedelta
from typing import Any

import pytest
from accounts.models import User
from openpyxl import Workbook

from employees.models import Employee, StaffImportDraft
from employees.staff_import.matching import auto_match
from employees.staff_import.plan import build_preview
from employees.staff_import.run import run_import

pytestmark = pytest.mark.django_db

SHEET = "Ажилтан"
HEADINGS = ["Овог", "Нэр", "Регистр", "Ажилд орсон огноо", "Хэлтэс", "Албан тушаал"]
DEPARTMENTS = ["Санхүү", "Худалдаа", "Үйлдвэрлэл", "Хүний нөөц", "Захиргаа"]
POSITIONS = [f"Албан тушаал {number}" for number in range(1, 11)]
ROW_COUNT = 500
PREVIEW_QUERY_LIMIT = 40
PREVIEW_SECONDS = 10
IMPORT_SECONDS = 120


def scale_rows(count: int) -> list[list[object]]:
    """Valid, unique rows: the register number is UB + YYMMDD + 2 digits, so each person has a different birth date
    (the import reads birth date and gender from it, and the file has no such columns). 5 departments and 10
    positions are reused across the rows."""
    return [
        [
            f"Овог {number}",
            f"Нэр {number}",
            f"УБ{date(1960, 1, 1) + timedelta(days=number):%y%m%d}11",  # 11: odd last digit, a man
            date(2026, 3, 1),
            DEPARTMENTS[number % len(DEPARTMENTS)],
            POSITIONS[number % len(POSITIONS)],
        ]
        for number in range(count)
    ]


def make_scale_draft(rows: list[list[object]]) -> StaffImportDraft:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = SHEET
    ws.append(HEADINGS)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return StaffImportDraft.objects.create(
        filename="staff_500.xlsx",
        data=buffer.getvalue(),
        sheet=SHEET,
        header_rows=1,
        mapping=auto_match(HEADINGS, remembered={}, allow_salary=False),
        date_format="iso",
    )


def report(capsys: Any, line: str) -> None:
    """Prints a timing line even when pytest captures output, so the real numbers show in the run log."""
    with capsys.disabled():
        print(line)


def test_import_of_500_rows(actor: User, capsys: Any) -> None:
    draft = make_scale_draft(scale_rows(ROW_COUNT))

    started = time.perf_counter()
    preview = build_preview(draft, allow_salary=False)
    preview_seconds = time.perf_counter() - started
    assert preview.new == ROW_COUNT

    started = time.perf_counter()
    run_import(draft, by=actor, allow_salary=False)
    import_seconds = time.perf_counter() - started

    report(capsys, f"[scale] preview of {ROW_COUNT} rows: {preview_seconds:.2f} s")
    report(capsys, f"[scale] run_import of {ROW_COUNT} rows (includes its own preview): {import_seconds:.2f} s")
    report(capsys, f"[scale] per person (run_import): {import_seconds / ROW_COUNT * 1000:.1f} ms")

    draft.refresh_from_db()
    assert draft.state == "imported"
    assert draft.created_count == ROW_COUNT
    assert draft.rejected_count == 0
    assert Employee.objects.count() == ROW_COUNT
    assert import_seconds < IMPORT_SECONDS


def test_preview_of_500_rows_is_quick(actor: User, django_assert_max_num_queries: Any) -> None:
    draft = make_scale_draft(scale_rows(ROW_COUNT))

    started = time.perf_counter()
    with django_assert_max_num_queries(PREVIEW_QUERY_LIMIT):
        preview = build_preview(draft, allow_salary=False)
    elapsed = time.perf_counter() - started

    assert preview.new == ROW_COUNT
    assert preview.errors == 0
    assert elapsed < PREVIEW_SECONDS
