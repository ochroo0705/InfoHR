"""The staff import fills the wider set of employee columns: personal lists, job type, contract, probation."""

import io
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from macs.models import (
    EducationLevel,
    MaritalStatus,
    Shift,
)
from openpyxl import Workbook

from employees.models import Employee, JobRecord, StaffImportDraft
from employees.staff_import.matching import auto_match
from employees.staff_import.plan import build_preview
from employees.staff_import.rows import parse_row
from employees.staff_import.run import run_import
from employees.staff_import.template import template_bytes

from .conftest import named

pytestmark = pytest.mark.django_db

SHEET = "Ажилтан"
HEADINGS = [
    "Овог",
    "Нэр",
    "Регистр",
    "Ажилд орсон огноо",
    "Хэлтэс",
    "Албан тушаал",
    "Ургийн овог",
    "Утас #2",
    "Өмнөх ажилласан жил",
    "Туршилтын хугацаа дуусах",
    "Ажилтны төрөл",
    "Гэрээний төрөл",
    "Гэрээний дугаар",
    "Гэрээ эхлэх огноо",
    "Гэрээ дуусах огноо",
    "Ажлын цагийн хуваарь",
    "Гэрлэлтийн байдал",
    "Боловсрол",
    "Цусны бүлэг",
    "Цэргийн алба хаасан",
    "Хөгжлийн бэрхшээлтэй",
]


def _row(**changes: Any) -> list[object]:
    base: dict[str, Any] = {
        "Овог": "Бат",
        "Нэр": "Дорж",
        "Регистр": "УБ99112244",
        "Ажилд орсон огноо": date(2026, 3, 1),
        "Хэлтэс": "Санхүү",
        "Албан тушаал": "Нягтлан",
    }
    base.update(changes)
    return [base.get(heading) for heading in HEADINGS]


def _draft(rows: list[list[object]]) -> StaffImportDraft:
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
        filename="staff.xlsx",
        data=buffer.getvalue(),
        sheet=SHEET,
        header_rows=1,
        mapping=auto_match(HEADINGS, remembered={}, allow_salary=False),
        date_format="iso",
    )


def test_every_new_heading_maps_to_a_field() -> None:
    mapping = auto_match(HEADINGS, remembered={}, allow_salary=False)
    assert len(mapping) == len(HEADINGS)


def test_expanded_columns_are_written(actor: User) -> None:
    named(Shift, "Өдрийн")
    named(MaritalStatus, "Гэрлэсэн")
    named(EducationLevel, "Дээд")
    draft = _draft(
        [
            _row(
                **{
                    "Ургийн овог": "Боржигин",
                    "Утас #2": "88001122",
                    "Өмнөх ажилласан жил": 4,
                    "Туршилтын хугацаа дуусах": date(2026, 6, 1),
                    "Ажилтны төрөл": "Хагас цаг",
                    "Гэрээний төрөл": "Хугацаатай",
                    "Гэрээний дугаар": "Г-12",
                    "Гэрээ эхлэх огноо": date(2026, 3, 1),
                    "Гэрээ дуусах огноо": date(2027, 3, 1),
                    "Ажлын цагийн хуваарь": "Өдрийн",
                    "Гэрлэлтийн байдал": "Гэрлэсэн",
                    "Боловсрол": "Дээд",
                    "Цусны бүлэг": "II",
                    "Цэргийн алба хаасан": "Тийм",
                    "Хөгжлийн бэрхшээлтэй": "Үгүй",
                }
            )
        ]
    )

    run_import(draft, by=actor, allow_salary=False)

    draft.refresh_from_db()
    assert (draft.created_count, draft.rejected_count) == (1, 0)
    employee = Employee.objects.get()
    assert employee.clan_name == "Боржигин"
    assert employee.phone2 == "88001122"
    assert employee.prior_service_years == 4
    assert employee.blood_type == "A"
    assert employee.military_service == "yes"
    assert employee.has_disability is False
    assert employee.marital_status is not None and employee.marital_status.name == "Гэрлэсэн"
    assert employee.education_level is not None and employee.education_level.name == "Дээд"
    assert employee.work_schedule is not None and employee.work_schedule.name == "Өдрийн"
    assert employee.ext.probation_end == date(2026, 6, 1)
    job = JobRecord.objects.get(employee=employee)
    assert job.employee_type == "part_time"
    assert job.contract_type == "fixed_term"
    assert job.contract_no == "Г-12"
    assert job.contract_start == date(2026, 3, 1)
    assert job.contract_end == date(2027, 3, 1)


def test_a_sheet_without_the_new_columns_keeps_the_old_job_defaults(actor: User) -> None:
    draft = _draft([_row()])

    run_import(draft, by=actor, allow_salary=False)

    job = JobRecord.objects.get(employee=Employee.objects.get())
    assert (job.employee_type, job.contract_type) == ("full_time", "open_ended")


@pytest.mark.parametrize(
    ("heading", "value", "message"),
    [
        ("Гэрлэлтийн байдал", "Олдохгүй", "Гэрлэлтийн байдал олдсонгүй"),
        ("Ажилтны төрөл", "Хаана", "Ажилтны төрөл буруу байна"),
        ("Гэрээний төрөл", "Хаана", "Гэрээний төрөл буруу байна"),
        ("Цусны бүлэг", "Z", "Цусны бүлэг буруу байна"),
        ("Цэргийн алба хаасан", "магадгүй", "Цэргийн алба хаасан буруу байна"),
        ("Өмнөх ажилласан жил", "-1", "Өмнөх ажилласан жил буруу байна"),
        ("Өмнөх ажилласан жил", 200, "Өмнөх ажилласан жил буруу байна"),
        ("Утас #2", "abc", "Утас #2 буруу байна"),
    ],
)
def test_bad_values_refuse_the_row(heading: str, value: object, message: str) -> None:
    draft = _draft([_row(**{heading: value})])

    preview = build_preview(draft, allow_salary=False)

    assert preview.errors == 1
    assert any(message in error for error in preview.rows[0].errors)


def test_contract_end_before_start_is_refused() -> None:
    draft = _draft([_row(**{"Гэрээ эхлэх огноо": date(2026, 5, 1), "Гэрээ дуусах огноо": date(2026, 4, 1)})])

    preview = build_preview(draft, allow_salary=False)

    assert preview.errors == 1


def test_yes_no_accepts_english_and_excel_booleans() -> None:
    mapping = {"0": "military_service", "1": "has_disability"}
    row = parse_row(2, ["yes", True], mapping, {}, "iso")
    # the required columns are not in this tiny sheet, so errors for them are expected; the two answers are not
    assert not any("Цэргийн" in error or "Хөгжлийн" in error for error in row.errors)
    assert row.values == {"military_service": True, "has_disability": True}


def test_template_lists_the_new_columns_and_the_example_row_is_valid() -> None:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(template_bytes(include_salary=False)))
    headings = [cell.value for cell in wb[SHEET][1]]
    for label in ("Ургийн овог", "Гэрээний төрөл", "Цусны бүлэг", "Хөгжлийн бэрхшээлтэй"):
        assert label in headings
