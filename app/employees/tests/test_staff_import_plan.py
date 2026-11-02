import io
from typing import Any

import pytest
from macs.models import Bank, Branch, Department, Position
from openpyxl import Workbook

from employees.models import DepartmentExt, Employee, StaffImportDraft
from employees.services import macs_writes
from employees.staff_import.matching import auto_match
from employees.staff_import.plan import Preview, build_preview

pytestmark = pytest.mark.django_db

SHEET = "Ажилтан"
# (field key, column heading). The headings are the recognised aliases, so auto_match maps them.
COLUMNS = (
    ("family_name", "Овог"),
    ("given_name", "Нэр"),
    ("register_no", "Регистр"),
    ("passport_no", "Паспорт"),
    ("birth_date", "Төрсөн огноо"),
    ("gender", "Хүйс"),
    ("start", "Ажилд орсон огноо"),
    ("department", "Хэлтэс"),
    ("position", "Албан тушаал"),
    ("branch", "Салбар"),
    ("bank", "Банк"),
    ("base_salary", "Цалин"),
)
HEADINGS = [heading for _, heading in COLUMNS]

# A complete row for a new person with a register number. A test changes cells by keyword.
BASE: dict[str, Any] = {
    "family_name": "Бат",
    "given_name": "Дорж",
    "register_no": "УБ99112244",
    "start": "2026-03-01",
    "department": "Санхүү",
    "position": "Нягтлан",
}


def person(**changes: Any) -> list[object]:
    cells = {**BASE, **changes}
    return [cells.get(key) for key, _ in COLUMNS]


def make_draft(rows: list[list[object]], *, defaults: dict[str, str] | None = None) -> StaffImportDraft:
    """A draft over one sheet: the heading row, then `rows`. The mapping is the one the upload step would make."""
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
        mapping=auto_match(HEADINGS, remembered={}, allow_salary=True),
        defaults=defaults or {},
        date_format="iso",
    )


def counts() -> tuple[int, int, int]:
    return Department.objects.count(), Position.objects.count(), Employee.objects.count()


def test_existing_register_number_is_a_duplicate(hired: Employee) -> None:
    preview = build_preview(make_draft([person(register_no="УБ99112233")]), allow_salary=True)

    row = preview.rows[0]
    assert row.status == "duplicate"
    assert row.note == "Системд бүртгэлтэй"
    assert preview.duplicates == 1
    assert preview.new == 0


def test_register_number_is_compared_ignoring_case_and_spaces(hired: Employee) -> None:
    preview = build_preview(make_draft([person(register_no="уб 99112233")]), allow_salary=True)

    assert preview.rows[0].status == "duplicate"
    assert preview.rows[0].note == "Системд бүртгэлтэй"


def test_second_row_with_the_same_new_register_is_an_in_file_duplicate() -> None:
    preview = build_preview(make_draft([person(), person(given_name="Сараа")]), allow_salary=True)

    first, second = preview.rows
    assert first.status == "new"
    assert second.status == "duplicate"
    assert second.note == "Файлд давхардсан (мөр 2)"
    assert preview.new == 1
    assert preview.duplicates == 1


def test_passport_only_row_matches_an_existing_passport(hired: Employee) -> None:
    macs_writes.update_employee_columns(hired, {"passport_no": "A12345678"})
    row = person(register_no=None, passport_no="a 12345678", birth_date="1990-01-01", gender="Эрэгтэй")

    preview = build_preview(make_draft([row]), allow_salary=True)

    assert preview.rows[0].status == "duplicate"
    assert preview.rows[0].note == "Системд бүртгэлтэй"


def test_passport_is_not_compared_with_register_numbers(hired: Employee) -> None:
    row = person(register_no=None, passport_no="УБ99112233", birth_date="1990-01-01", gender="Эрэгтэй")

    preview = build_preview(make_draft([row]), allow_salary=True)

    assert preview.rows[0].status == "new"


def test_unknown_bank_is_an_error_and_not_counted_as_new() -> None:
    preview = build_preview(make_draft([person(bank="Тодорхойгүй банк")]), allow_salary=True)

    row = preview.rows[0]
    assert row.status == "error"
    assert row.errors == ["Банк олдсонгүй: Тодорхойгүй банк"]
    assert preview.new == 0
    assert preview.errors == 1


def test_known_bank_is_resolved_to_its_id() -> None:
    bank = Bank.objects.create(name="Хаан банк")

    preview = build_preview(make_draft([person(bank="хаан  банк")]), allow_salary=True)

    assert preview.rows[0].status == "new"
    assert preview.rows[0].values["bank_id"] == bank.pk
    assert "bank" not in preview.rows[0].values


def test_known_branch_is_resolved_to_its_id() -> None:
    branch = Branch.objects.create(name="Төв салбар")

    preview = build_preview(make_draft([person(branch="төв салбар")]), allow_salary=True)

    assert preview.rows[0].values["branch_id"] == branch.pk


def test_unknown_branch_is_an_error() -> None:
    preview = build_preview(make_draft([person(branch="Байхгүй")]), allow_salary=True)

    assert preview.rows[0].errors == ["Салбар олдсонгүй: Байхгүй"]


def test_department_matches_existing_ignoring_case_and_spaces() -> None:
    dep = macs_writes.save_department("Борлуулалт")

    preview = build_preview(make_draft([person(department="борлуулалт ")]), allow_salary=True)

    row = preview.rows[0]
    assert row.status == "new"
    assert row.values["department_id"] == dep.pk
    assert "department" not in row.values
    assert preview.new_departments == []


def test_new_department_is_listed_once_with_its_first_spelling() -> None:
    preview = build_preview(
        make_draft([person(department="Агуулах"), person(register_no="УБ99112255", department="агуулах")]),
        allow_salary=True,
    )

    assert preview.new_departments == ["Агуулах"]
    assert [row.values["department"] for row in preview.rows] == ["Агуулах", "Агуулах"]


def test_new_position_is_listed_once() -> None:
    preview = build_preview(
        make_draft([person(position="Шинэ ажил"), person(register_no="УБ99112255", position="шинэ  ажил")]),
        allow_salary=True,
    )

    assert preview.new_positions == ["Шинэ ажил"]


def test_inactive_department_is_an_error() -> None:
    dep = macs_writes.save_department("Архив")
    DepartmentExt.objects.filter(department=dep).update(active=False)

    preview = build_preview(make_draft([person(department="архив")]), allow_salary=True)

    assert preview.rows[0].status == "error"
    assert preview.rows[0].errors == ["Хэлтэс идэвхгүй байна: архив"]
    assert preview.new_departments == []


def test_department_name_longer_than_the_column_is_an_error() -> None:
    too_long = "А" * 26

    preview = build_preview(make_draft([person(department=too_long)]), allow_salary=True)

    assert preview.rows[0].status == "error"
    assert preview.rows[0].errors == ["Хэлтэс хэт урт байна (дээд тал 25 тэмдэгт)"]
    assert preview.new_departments == []


def test_work_conditions_text_is_resolved_to_its_number() -> None:
    preview = build_preview(make_draft([person()], defaults={"work_conditions": "Хүнд"}), allow_salary=True)

    assert preview.rows[0].values["work_conditions"] == 2


def test_work_conditions_outside_the_choices_is_an_error() -> None:
    preview = build_preview(make_draft([person()], defaults={"work_conditions": "9"}), allow_salary=True)

    assert preview.rows[0].errors == ["Ажлын нөхцөл буруу байна (Хэвийн, Хүнд, Бусад эсвэл 1, 2, 3)"]


def test_salary_columns_are_ignored_without_the_salary_right() -> None:
    bank_row = person(bank="Тодорхойгүй банк", base_salary="2500000")

    preview = build_preview(make_draft([bank_row]), allow_salary=False)

    row = preview.rows[0]
    assert row.status == "new"
    assert row.errors == []
    assert "base_salary" not in row.values
    assert "bank_id" not in row.values
    assert preview.ignored_columns == ["Банк", "Цалин"]


def test_salary_columns_are_imported_with_the_salary_right() -> None:
    preview = build_preview(make_draft([person(base_salary="2500000")]), allow_salary=True)

    assert preview.rows[0].values["base_salary"] == 2500000
    assert preview.ignored_columns == []


def test_preview_writes_nothing() -> None:
    draft = make_draft([person(department="Шинэ хэлтэс", position="Шинэ ажил", register_no="УБ99112244")])
    before = counts()

    preview = build_preview(draft, allow_salary=True)

    assert isinstance(preview, Preview)
    assert preview.new == 1
    assert counts() == before
