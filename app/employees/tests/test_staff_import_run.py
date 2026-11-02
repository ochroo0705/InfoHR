import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.db import IntegrityError
from django.utils import timezone
from macs.models import Bank, Department, Position
from openpyxl import Workbook, load_workbook

from employees.models import (
    ActivityEntry,
    DepartmentExt,
    Employee,
    HrOrder,
    JobRecord,
    PositionExt,
    SalaryRecord,
    StaffImportDraft,
)
from employees.services import history
from employees.staff_import import run
from employees.staff_import.matching import auto_match
from employees.staff_import.run import REJECTED_SHEET, run_import

from .conftest import named
from .test_customer_row import _rows

pytestmark = pytest.mark.django_db

SHEET = "Ажилтан"
COLUMNS = (
    ("family_name", "Овог"),
    ("given_name", "Нэр"),
    ("register_no", "Регистр"),
    ("birth_date", "Төрсөн огноо"),
    ("gender", "Хүйс"),
    ("start", "Ажилд орсон огноо"),
    ("department", "Хэлтэс"),
    ("position", "Албан тушаал"),
    ("bank", "Банк"),
    ("account_no", "Дансны дугаар"),
    ("taxpayer_no", "Татвар төлөгчийн дугаар"),
    ("base_salary", "Цалин"),
)
HEADINGS = [heading for _, heading in COLUMNS]
BASE: dict[str, Any] = {
    "family_name": "Бат",
    "given_name": "Дорж",
    "register_no": "УБ99112244",
    "start": date(2026, 3, 1),
    "department": "Санхүү",
    "position": "Нягтлан",
}


def person(**changes: Any) -> list[object]:
    cells = {**BASE, **changes}
    return [cells.get(key) for key, _ in COLUMNS]


def make_draft(rows: list[list[object]]) -> StaffImportDraft:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = SHEET
    ws.append(HEADINGS)
    for row in rows:
        ws.append(row)
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.data_type = "s"  # a text cell in Excel, not a formula
    buffer = io.BytesIO()
    wb.save(buffer)
    return StaffImportDraft.objects.create(
        filename="staff.xlsx",
        data=buffer.getvalue(),
        sheet=SHEET,
        header_rows=1,
        mapping=auto_match(HEADINGS, remembered={}, allow_salary=True),
        date_format="iso",
    )


def read_back(values: list[object]) -> tuple[object, ...]:
    """What openpyxl gives back for the cells: a date comes back as a datetime at midnight."""
    return tuple(datetime.combine(v, time()) if isinstance(v, date) else v for v in values)


def rejected_sheet(draft: StaffImportDraft) -> list[tuple[Any, ...]]:
    assert draft.rejected_file is not None
    wb = load_workbook(io.BytesIO(bytes(draft.rejected_file)))
    assert wb.sheetnames == [REJECTED_SHEET]
    return list(wb[REJECTED_SHEET].iter_rows(values_only=True))


def test_good_rows_are_created_and_bad_row_is_rejected(actor: User) -> None:
    named(Bank, "Хаан банк")
    draft = make_draft(
        [
            person(register_no="УБ99112244"),
            person(register_no="УБ99112255", given_name="Сэрэн", bank="Олдохгүй банк"),
            person(register_no="УБ99112266", given_name="Оюун"),
        ]
    )

    run_import(draft, by=actor, allow_salary=True)

    draft.refresh_from_db()
    assert draft.state == "imported"
    assert draft.created_count == 2
    assert draft.rejected_count == 1
    assert draft.duplicate_count == 0
    assert Employee.objects.count() == 2
    rows = rejected_sheet(draft)
    assert rows[0][:-1] == tuple(HEADINGS)
    assert rows[0][-1] == "Алдаа"
    assert rows[1][:-1] == read_back(person(register_no="УБ99112255", given_name="Сэрэн", bank="Олдохгүй банк"))
    assert "Банк олдсонгүй" in rows[1][-1]


def test_imported_people_get_no_onboarding_checklist_item(actor: User) -> None:
    draft = make_draft([person()])

    run_import(draft, by=actor, allow_salary=False)

    employee = Employee.objects.get()
    assert employee.ext.setup_required is False


def test_created_employee_has_job_no_order_activity_and_customer_row(actor: User) -> None:
    draft = make_draft([person()])

    run_import(draft, by=actor, allow_salary=True)

    employee = Employee.objects.get()
    job = JobRecord.objects.get(employee=employee)
    assert job.department.name == "Санхүү"
    assert job.position.name == "Нягтлан"
    assert job.employee_type == "full_time"
    assert job.status == "active"
    assert job.contract_type == "open_ended"
    assert job.period.lower == date(2026, 3, 1)
    assert not HrOrder.objects.filter(employee=employee).exists()
    assert ActivityEntry.objects.filter(employee=employee, message__startswith="Ажилтан бүртгэв").exists()
    assert len(_rows(employee)) == 1


def test_missing_department_and_position_are_created_once(actor: User) -> None:
    draft = make_draft(
        [
            person(register_no="УБ99112244", department="Шинэ хэлтэс", position="Шинэ ажил"),
            person(register_no="УБ99112255", given_name="Сэрэн", department="ШИНЭ  хэлтэс", position="Шинэ ажил"),
        ]
    )

    run_import(draft, by=actor, allow_salary=True)

    assert draft.created_count == 2
    department = Department.objects.get(name="Шинэ хэлтэс")
    position = Position.objects.get(name="Шинэ ажил")
    assert Department.objects.filter(name__iexact="Шинэ хэлтэс").count() == 1
    assert Position.objects.filter(name="Шинэ ажил").count() == 1
    assert DepartmentExt.objects.filter(department=department).exists()
    assert PositionExt.objects.filter(position=position).exists()
    for employee in Employee.objects.all():
        job = JobRecord.objects.get(employee=employee)
        assert job.department == department
        assert job.position == position


def test_running_the_same_file_again_creates_nobody(actor: User) -> None:
    rows = [person(register_no="УБ99112244"), person(register_no="УБ99112255", given_name="Сэрэн")]
    first = make_draft(rows)
    run_import(first, by=actor, allow_salary=True)
    second = make_draft(rows)

    run_import(second, by=actor, allow_salary=True)

    assert Employee.objects.count() == 2
    assert second.created_count == 0
    assert second.duplicate_count == 2
    assert second.rejected_count == 0
    assert second.rejected_file is None


def test_failure_on_one_row_leaves_the_others_created(actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    original = history.hire
    calls: list[int] = []

    def flaky(*args: Any, **kwargs: Any) -> Employee:
        calls.append(1)
        if len(calls) == 2:
            raise IntegrityError("duplicate key value violates unique constraint")
        return original(*args, **kwargs)

    monkeypatch.setattr(history, "hire", flaky)
    draft = make_draft(
        [
            person(register_no="УБ99112244"),
            person(register_no="УБ99112255", given_name="Сэрэн"),
            person(register_no="УБ99112266", given_name="Оюун"),
        ]
    )

    run_import(draft, by=actor, allow_salary=True)

    assert draft.created_count == 2
    assert draft.rejected_count == 1
    assert sorted(Employee.objects.values_list("given_name", flat=True)) == ["Дорж", "Оюун"]
    rows = rejected_sheet(draft)
    assert rows[1][:-1] == read_back(person(register_no="УБ99112255", given_name="Сэрэн"))
    assert rows[1][-1] == "Хадгалж чадсангүй"


def test_salary_columns_are_ignored_when_salary_is_not_allowed(actor: User) -> None:
    named(Bank, "Хаан банк")
    draft = make_draft([person(bank="Хаан банк", account_no="5001234567", taxpayer_no="TX1", base_salary=2500000)])

    run_import(draft, by=actor, allow_salary=False)

    employee = Employee.objects.get()
    assert draft.created_count == 1
    assert not SalaryRecord.objects.filter(employee=employee).exists()
    assert employee.bank_id is None
    assert not employee.account_no
    assert not employee.taxpayer_no


def test_salary_and_taxpayer_are_written_when_allowed(actor: User) -> None:
    named(Bank, "Хаан банк")
    draft = make_draft([person(bank="Хаан банк", account_no="5001234567", taxpayer_no="TX1", base_salary=2500000)])

    run_import(draft, by=actor, allow_salary=True)

    employee = Employee.objects.get()
    record = SalaryRecord.objects.get(employee=employee)
    assert record.base_salary == Decimal("2500000")
    assert employee.taxpayer_no == "TX1"
    assert employee.account_no == "5001234567"
    assert employee.bank_id is not None
    assert Bank.objects.get(pk=employee.bank_id).name == "Хаан банк"


def test_imported_draft_cannot_run_again(actor: User) -> None:
    draft = make_draft([person()])
    run_import(draft, by=actor, allow_salary=True)

    with pytest.raises(ValueError):
        run_import(draft, by=actor, allow_salary=True)


def test_rejected_file_is_none_when_nothing_is_rejected(actor: User) -> None:
    draft = make_draft([person()])

    run_import(draft, by=actor, allow_salary=True)

    assert draft.rejected_count == 0
    assert draft.rejected_file is None
    assert bytes(draft.data) == b""
    assert draft.finished_at is not None


def test_a_draft_already_running_is_refused_and_creates_nobody(actor: User) -> None:
    draft = make_draft([person()])
    StaffImportDraft.objects.filter(pk=draft.pk).update(state="running")

    with pytest.raises(ValueError):
        run_import(draft, by=actor, allow_salary=True)

    assert Employee.objects.count() == 0
    draft.refresh_from_db()
    assert draft.state == "running"


def test_a_run_that_fails_gives_the_draft_back(actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(run, "build_preview", broken)
    draft = make_draft([person()])

    with pytest.raises(RuntimeError):
        run_import(draft, by=actor, allow_salary=True)

    draft.refresh_from_db()
    assert draft.state == "uploaded"
    assert draft.finished_at is None
    assert bytes(draft.data) != b""
    assert Employee.objects.count() == 0


def test_text_that_looks_like_a_formula_stays_text_in_the_rejected_file(actor: User) -> None:
    draft = make_draft([person(given_name="=1+1", bank="Олдохгүй банк")])

    run_import(draft, by=actor, allow_salary=True)

    assert draft.rejected_count == 1
    assert draft.rejected_file is not None
    ws = load_workbook(io.BytesIO(bytes(draft.rejected_file)))[REJECTED_SHEET]
    cell = ws.cell(row=2, column=2)
    assert cell.value == "=1+1"
    assert cell.data_type == "s"


def test_a_claim_sets_started_at(actor: User) -> None:
    draft = make_draft([person(register_no="УБ99112244")])
    run_import(draft, by=actor, allow_salary=True)
    draft.refresh_from_db()
    assert draft.started_at is not None


def test_a_second_draft_cannot_be_claimed_while_the_first_is_running(actor: User) -> None:
    first = make_draft([person(register_no="УБ99112244")])
    StaffImportDraft.objects.filter(pk=first.pk).update(state="running", started_at=timezone.now())
    second = make_draft([person(register_no="УБ99112255")])
    with pytest.raises(run.DraftBusy):
        run_import(second, by=actor, allow_salary=True)
    second.refresh_from_db()
    assert second.state == "uploaded"
    assert not Employee.objects.filter(register_no="УБ99112255").exists()


def test_a_draft_stuck_running_for_over_thirty_minutes_does_not_block(actor: User) -> None:
    stuck = make_draft([person(register_no="УБ99112244")])
    StaffImportDraft.objects.filter(pk=stuck.pk).update(
        state="running", started_at=timezone.now() - timedelta(minutes=31)
    )
    fresh = make_draft([person(register_no="УБ99112255")])
    run_import(fresh, by=actor, allow_salary=True)
    fresh.refresh_from_db()
    assert fresh.state == "imported"
