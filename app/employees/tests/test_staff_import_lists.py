"""The optional list sheets of a staff workbook: family, education, training, address and the others."""

import io
from datetime import date

import pytest
from accounts.models import User
from macs.models import City, District, EducationLevel, FamilyRelation
from openpyxl import Workbook, load_workbook

from employees.models import Employee, StaffImportDraft
from employees.staff_import.lists import BY_KIND, LINK_LABEL, SHEETS
from employees.staff_import.matching import auto_match
from employees.staff_import.plan import build_preview
from employees.staff_import.reader import ImportFileError, read_rows
from employees.staff_import.run import run_import
from employees.staff_import.template import template_bytes

from .conftest import named

pytestmark = pytest.mark.django_db

MAIN = "Ажилтан"
MAIN_HEADINGS = ["Овог", "Нэр", "Регистр", "Ажилд орсон огноо", "Хэлтэс", "Албан тушаал"]


def _person(register: str, given: str = "Дорж") -> list[object]:
    return ["Бат", given, register, date(2026, 3, 1), "Санхүү", "Нягтлан"]


def _draft(main_rows: list[list[object]], lists: dict[str, tuple[list[str], list[list[object]]]]) -> StaffImportDraft:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = MAIN
    ws.append(MAIN_HEADINGS)
    for row in main_rows:
        ws.append(row)
    for title, (headings, rows) in lists.items():
        sheet = wb.create_sheet(title)
        sheet.append(headings)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return StaffImportDraft.objects.create(
        filename="staff.xlsx",
        data=buffer.getvalue(),
        sheet=MAIN,
        header_rows=1,
        mapping=auto_match(MAIN_HEADINGS, remembered={}, allow_salary=False),
        date_format="iso",
    )


def _headings(kind: str, *fields: str) -> list[str]:
    sheet = BY_KIND[kind]
    return [LINK_LABEL, *(sheet.label(name) for name in fields)]


def test_the_template_has_every_list_sheet_with_the_real_headings() -> None:
    wb = load_workbook(io.BytesIO(template_bytes(include_salary=False)))
    assert wb.sheetnames[0] == MAIN
    for sheet in SHEETS:
        assert sheet.title in wb.sheetnames
        assert [cell.value for cell in wb[sheet.title][1]][: len(sheet.headings())] == sheet.headings()


def test_the_template_example_rows_are_skipped_by_the_reader() -> None:
    data = template_bytes(include_salary=False)
    for sheet in SHEETS:
        with pytest.raises(ImportFileError):  # only the example row: "no rows"
            read_rows(data, sheet.title, 1)


def test_list_rows_are_written_for_the_new_person(actor: User) -> None:
    named(FamilyRelation, "Хүү")
    named(EducationLevel, "Дээд")
    city = City.objects.create(name="Улаанбаатар")
    District.objects.create(name="Баянгол", city=city)
    draft = _draft(
        [_person("УБ99112244")],
        {
            "Гэр бүл": (
                _headings("family", "relation", "given_name", "birth_date"),
                [["УБ99112244", "Хүү", "Тэмүүлэн", date(2015, 5, 5)]],
            ),
            "Боловсрол": (
                _headings("education", "org_name", "start_year", "end_year", "edu_level"),
                [["уб99112244", "МУИС", 2008, 2012, "Дээд"]],
            ),
            "Сургалт": (
                _headings("training", "tr_type", "description", "start_year", "amount", "pay_type"),
                [["УБ99112244", "Дотоод", "Excel", 2022, "1,500,000", "Байгууллага"]],
            ),
            "Хаяг": (
                _headings("address", "city", "district", "street"),
                [["УБ99112244", "Улаанбаатар", "Баянгол", "1-р хороо"]],
            ),
        },
    )

    run_import(draft, by=actor, allow_salary=False)

    draft.refresh_from_db()
    assert draft.list_results == {"family": [1, 0], "education": [1, 0], "training": [1, 0], "address": [1, 0]}
    assert draft.rejected_file is None
    employee = Employee.objects.get()
    from macs.models import AddressRow, FamilyRow, QualificationRow, TrainingRow

    family = FamilyRow.objects.get(employee=employee)
    assert (family.given_name, family.relation.name, family.birth_date) == ("Тэмүүлэн", "Хүү", date(2015, 5, 5))
    education = QualificationRow.objects.get(employee=employee)
    assert (education.org_name, education.start_year, education.end_year) == ("МУИС", 2008, 2012)
    assert education.edu_level is not None and education.edu_level.name == "Дээд"
    training = TrainingRow.objects.get(employee=employee)
    assert (training.tr_type, training.pay_type, int(training.amount)) == (1, 3, 1500000)
    address = AddressRow.objects.get(employee=employee)
    assert address.street == "1-р хороо" and address.district.name == "Баянгол"


def test_a_bad_list_row_is_refused_and_goes_to_the_rejected_file(actor: User) -> None:
    named(FamilyRelation, "Хүү")
    draft = _draft(
        [_person("УБ99112244")],
        {
            "Гэр бүл": (
                _headings("family", "relation", "given_name"),
                [["УБ99112244", "Хүү", "Тэмүүлэн"], ["УБ99112244", "Олдохгүй", "Сараа"]],
            )
        },
    )

    preview = build_preview(draft, allow_salary=False)
    assert (preview.lists["family"].ok, preview.lists["family"].refused) == (1, 1)
    assert "Хамаарал олдсонгүй" in preview.lists["family"].rows[1].errors[0]

    run_import(draft, by=actor, allow_salary=False)

    draft.refresh_from_db()
    assert draft.list_results == {"family": [1, 1]}
    assert draft.created_count == 1 and draft.rejected_count == 0
    assert draft.rejected_file is not None
    wb = load_workbook(io.BytesIO(bytes(draft.rejected_file)))
    assert wb.sheetnames == ["Гэр бүл"]  # no refused staff rows, so no staff sheet
    rows = list(wb["Гэр бүл"].iter_rows(values_only=True))
    assert rows[1][:3] == ("УБ99112244", "Олдохгүй", "Сараа")
    assert "Хамаарал олдсонгүй" in rows[1][-1]


def test_a_row_for_a_person_not_in_the_main_sheet_is_refused(actor: User) -> None:
    draft = _draft(
        [_person("УБ99112244")],
        {"Шагнал урамшил": (_headings("award", "award_name"), [["УБ00000001", "Шилдэг"]])},
    )

    preview = build_preview(draft, allow_salary=False)

    row = preview.lists["award"].rows[0]
    assert row.status == "error"
    assert "ийм дугаартай ажилтан алга" in row.errors[0]


def test_list_rows_of_a_person_already_in_the_system_are_skipped(actor: User) -> None:
    first = _draft([_person("УБ99112244")], {})
    run_import(first, by=actor, allow_salary=False)
    second = _draft(
        [_person("УБ99112244")],
        {"Шагнал урамшил": (_headings("award", "award_name"), [["УБ99112244", "Шилдэг"]])},
    )

    preview = build_preview(second, allow_salary=False)
    run_import(second, by=actor, allow_salary=False)

    assert preview.lists["award"].rows[0].status == "skipped"
    second.refresh_from_db()
    assert second.list_results == {"award": [0, 1]}
    assert Employee.objects.count() == 1


def test_running_the_same_file_twice_never_doubles_list_rows(actor: User) -> None:
    from macs.models import AwardRow

    lists = {"Шагнал урамшил": (_headings("award", "award_name"), [["УБ99112244", "Шилдэг"]])}
    run_import(_draft([_person("УБ99112244")], lists), by=actor, allow_salary=False)
    run_import(_draft([_person("УБ99112244")], lists), by=actor, allow_salary=False)

    assert AwardRow.objects.count() == 1


def test_a_list_sheet_without_the_link_heading_is_refused() -> None:
    draft = _draft([_person("УБ99112244")], {"Шагнал урамшил": (["Шагналын нэр"], [["Шилдэг"]])})

    with pytest.raises(ImportFileError):
        build_preview(draft, allow_salary=False)


def test_a_list_sheet_with_only_headings_adds_nothing(actor: User) -> None:
    draft = _draft([_person("УБ99112244")], {"Шагнал урамшил": (_headings("award", "award_name"), [])})

    run_import(draft, by=actor, allow_salary=False)

    draft.refresh_from_db()
    assert draft.created_count == 1
    assert draft.list_results == {"award": [0, 0]}


def test_a_sheet_that_is_not_a_list_sheet_is_ignored(actor: User) -> None:
    draft = _draft([_person("УБ99112244")], {"Тэмдэглэл": (["А"], [["Б"]])})

    preview = build_preview(draft, allow_salary=False)

    assert preview.lists == {}


@pytest.mark.parametrize("kind", [sheet.kind for sheet in SHEETS])
def test_every_column_names_a_real_form_field(kind: str) -> None:
    sheet = BY_KIND[kind]
    from employees.forms import FORMS

    for name, _ in sheet.columns:
        assert name in FORMS[kind].base_fields, (kind, name)
    labels = [sheet.label(name) for name, _ in sheet.columns]
    assert len(labels) == len(set(labels)), kind  # a heading must name one column only
