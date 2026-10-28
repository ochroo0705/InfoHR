from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone
from employees.models import Employee
from employees.services import macs_writes
from employees.services.order_register import age_on
from macs.models import BodyRow, ComplaintRow, Department, SkillWorkRow, TrainingRow

from reports.development_lists import COMPLAINTS, HEALTH_CHECKS, SKILL_TASKS, TRAINING
from reports.filters import Filters
from reports.types import Column, Report

from .conftest import count_queries, legacy

pytestmark = pytest.mark.django_db

YEAR = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))


@pytest.fixture(autouse=True)
def no_production_rows() -> None:
    """The test database may hold production training, health, skill task and complaint rows; each test starts empty."""
    TrainingRow.objects.all().delete()
    BodyRow.objects.all().delete()
    SkillWorkRow.objects.all().delete()
    ComplaintRow.objects.all().delete()


def _training(employee: Employee, on: date | None, tr_type: int = 1, description: str = "Програм") -> TrainingRow:
    """A training row as the personal tab writes one (personal_writes.add with kind «training»)."""
    return TrainingRow.objects.create(
        employee=employee,
        tr_type=tr_type,
        description=description,
        start_date=on,
        days=5,
        amount=Decimal("250000.00"),
        pay_type=2,
        training_center="Монгол Бизнес",
        start_year=on.year if on else 2026,
    )


def _body(employee: Employee, on: date | None) -> BodyRow:
    """A health check row as the personal tab writes one (personal_writes.add with kind «body»)."""
    return BodyRow.objects.create(
        employee=employee,
        inserted_ognoo=on,
        term_type="Жилийн",
        end_date=date(2027, 4, 1),
        ear="Хэвийн",
        conclusion="Эрүүл",
    )


def _column(report: Report, key: str) -> Column:
    return next(c for c in report.columns if c.key == key)


def test_training_rows_in_period_with_type_filter(hr_user: User, hired: Employee) -> None:
    _training(hired, date(2026, 2, 10), tr_type=1, description="Дотоод")
    _training(hired, date(2026, 5, 1), tr_type=2, description="Гадаад")
    _training(hired, date(2025, 12, 31))
    assert [r.item.start_date for r in TRAINING.rows(hr_user, YEAR)] == [date(2026, 2, 10), date(2026, 5, 1)]
    foreign = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), tr_type=2)
    assert [r.item.description for r in TRAINING.rows(hr_user, foreign)] == ["Гадаад"]


def test_training_row_without_date_is_left_out(hr_user: User, hired: Employee) -> None:
    _training(hired, None)
    _training(hired, date(2026, 3, 3))
    assert len(TRAINING.rows(hr_user, YEAR)) == 1


def test_training_amount_is_money_column(hr_user: User, hired: Employee) -> None:
    _training(hired, date(2026, 3, 3))
    amount = _column(TRAINING, "amount")
    assert amount.money and amount.numeric
    assert amount.value(TRAINING.rows(hr_user, YEAR)[0]) == Decimal("250000.00")


def test_training_type_and_pay_type_names(hr_user: User, hired: Employee) -> None:
    _training(hired, date(2026, 3, 3), tr_type=2)  # pay_type 2 is «Өөрөө»
    row = TRAINING.rows(hr_user, YEAR)[0]
    assert _column(TRAINING, "type").value(row) == "Гадаад"
    assert _column(TRAINING, "pay_type").value(row) == "Өөрөө"


def test_health_checks_working_people_only(hr_user: User, hired: Employee, left_employee: Employee) -> None:
    _body(hired, date(2026, 4, 1))
    _body(left_employee, date(2026, 2, 1))  # left on 2026-03-01: the row is not in the list
    assert [r.row.employee.pk for r in HEALTH_CHECKS.rows(hr_user, YEAR)] == [hired.pk]


def test_health_check_age_and_gender(hr_user: User, hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(birth_date=date(1990, 6, 15), gender="F")
    _body(hired, date(2026, 4, 1))
    row = HEALTH_CHECKS.rows(hr_user, YEAR)[0]
    assert _column(HEALTH_CHECKS, "age").value(row) == age_on(date(1990, 6, 15), timezone.localdate())
    assert _column(HEALTH_CHECKS, "gender").value(row) == "Эмэгтэй"


@pytest.mark.parametrize("key", ["training", "health-checks"])
@pytest.mark.parametrize("role", ["Accountant", "Employee"])
def test_both_refuse_accountant_and_employee_role(
    client: Client, login_as: Callable[..., User], key: str, role: str
) -> None:
    login_as(client, role, "viewer")
    assert client.get(f"/reports/{key}/").status_code == 403


@pytest.mark.parametrize("key", ["training", "health-checks"])
def test_pages_print_and_excel_open(client: Client, login_hr: User, key: str) -> None:
    for suffix in ("", "print/", "excel/"):
        assert client.get(f"/reports/{key}/{suffix}").status_code == 200


def _three_people(actor: User, job_values: dict[str, Any], hired: Employee) -> list[Employee]:
    """Three different people, legacy first (the one-person baseline is legacy too). Legacy people have no HR job row,
    so their job is built from MACS ids. The per-person job lookup (history.job_on) is inside rows() by design."""
    return [legacy(actor, job_values), hired, legacy(actor, job_values)]


def test_training_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    first, *others = _three_people(actor, job_values, hired)
    _training(first, date(2026, 2, 10))
    one = count_queries(TRAINING, hr_user, YEAR)
    for person in others:
        _training(person, date(2026, 2, 11))
    assert len(TRAINING.rows(hr_user, YEAR)) == 3
    three = count_queries(TRAINING, hr_user, YEAR)
    assert three[1] - three[0] == one[1] - one[0]  # rendering adds the same queries for 1 and 3 people


def test_health_check_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    first, *others = _three_people(actor, job_values, hired)
    _body(first, date(2026, 2, 10))
    one = count_queries(HEALTH_CHECKS, hr_user, YEAR)
    for person in others:
        _body(person, date(2026, 2, 11))
    assert len(HEALTH_CHECKS.rows(hr_user, YEAR)) == 3
    three = count_queries(HEALTH_CHECKS, hr_user, YEAR)
    assert three[1] - three[0] == one[1] - one[0]  # rendering adds the same queries for 1 and 3 people


def _skill_task(
    employee: Employee, on: date | None, department: Any = None, description: str = "Даалгавар"
) -> SkillWorkRow:
    """A skill task row as the skill-work table holds one (norm is NOT NULL)."""
    return SkillWorkRow.objects.create(
        employee=employee,
        description=description,
        norm=Decimal("5.00"),
        department=department,
        sdate=on,
        comment="Тайлбар",
    )


def _complaint(employee: Employee, on: date, ctype: int = 1, kind: int = 1) -> ComplaintRow:
    """A customer complaint row as the complaints table holds one (date, type and name are NOT NULL)."""
    return ComplaintRow.objects.create(employee=employee, cdate=on, ctype=ctype, complaint_name=kind, comment="Гомдол")


def test_skill_task_department_is_the_rows_own(hr_user: User, hired: Employee) -> None:
    # The person is in «Санхүү» (job_values); the task was recorded against «Үйлдвэрлэл».
    other = macs_writes.save_department("Үйлдвэрлэл")
    _skill_task(hired, date(2026, 3, 3), department=other)
    row = SKILL_TASKS.rows(hr_user, YEAR)[0]
    assert _column(SKILL_TASKS, "task_department").value(row) == "Үйлдвэрлэл"
    assert row.row.job is not None and row.row.job.department.name == "Санхүү"
    by_task_dept = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), department=other.pk)
    assert len(SKILL_TASKS.rows(hr_user, by_task_dept)) == 1
    finance = Department.objects.get(name="Санхүү")
    by_person_dept = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), department=finance.pk)
    assert SKILL_TASKS.rows(hr_user, by_person_dept) == []


def test_skill_task_without_department_shows_blank(hr_user: User, hired: Employee) -> None:
    _skill_task(hired, date(2026, 3, 3), department=None)
    assert _column(SKILL_TASKS, "task_department").value(SKILL_TASKS.rows(hr_user, YEAR)[0]) is None


def test_skill_tasks_period_filter(hr_user: User, hired: Employee) -> None:
    _skill_task(hired, date(2026, 2, 10), description="Январь")
    _skill_task(hired, date(2026, 6, 1), description="Зургадугаар")
    _skill_task(hired, date(2025, 12, 31), description="Өмнөх")
    _skill_task(hired, None, description="Огноогүй")
    assert [r.item.description for r in SKILL_TASKS.rows(hr_user, YEAR)] == ["Январь", "Зургадугаар"]


def test_complaint_type_and_kind_names(hr_user: User, hired: Employee) -> None:
    _complaint(hired, date(2026, 3, 3), ctype=2, kind=2)
    row = COMPLAINTS.rows(hr_user, YEAR)[0]
    assert _column(COMPLAINTS, "type").value(row) == "Ур чадвар"
    assert _column(COMPLAINTS, "kind").value(row) == "Санал асуулга"


def test_complaints_period_filter(hr_user: User, hired: Employee) -> None:
    _complaint(hired, date(2026, 2, 10))
    _complaint(hired, date(2026, 12, 31))
    _complaint(hired, date(2025, 12, 31))
    assert [r.item.cdate for r in COMPLAINTS.rows(hr_user, YEAR)] == [date(2026, 2, 10), date(2026, 12, 31)]


@pytest.mark.parametrize("key", ["skill-tasks", "complaints"])
@pytest.mark.parametrize("role", ["Accountant", "Employee"])
def test_skill_tasks_and_complaints_refuse_accountant_and_employee(
    client: Client, login_as: Callable[..., User], key: str, role: str
) -> None:
    login_as(client, role, "viewer")
    assert client.get(f"/reports/{key}/").status_code == 403


@pytest.mark.parametrize("key", ["skill-tasks", "complaints"])
def test_skill_tasks_and_complaints_pages_print_and_excel_open(client: Client, login_hr: User, key: str) -> None:
    for suffix in ("", "print/", "excel/"):
        assert client.get(f"/reports/{key}/{suffix}").status_code == 200


def test_skill_task_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    first, *others = _three_people(actor, job_values, hired)
    _skill_task(first, date(2026, 2, 10), department=macs_writes.save_department("Үйлдвэрлэл"))
    one = count_queries(SKILL_TASKS, hr_user, YEAR)
    for person in others:
        _skill_task(person, date(2026, 2, 11), department=macs_writes.save_department("Үйлдвэрлэл"))
    assert len(SKILL_TASKS.rows(hr_user, YEAR)) == 3
    three = count_queries(SKILL_TASKS, hr_user, YEAR)
    assert three[1] - three[0] == one[1] - one[0]  # rendering adds the same queries for 1 and 3 people


def test_complaint_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    first, *others = _three_people(actor, job_values, hired)
    _complaint(first, date(2026, 2, 10))
    one = count_queries(COMPLAINTS, hr_user, YEAR)
    for person in others:
        _complaint(person, date(2026, 2, 11))
    assert len(COMPLAINTS.rows(hr_user, YEAR)) == 3
    three = count_queries(COMPLAINTS, hr_user, YEAR)
    assert three[1] - three[0] == one[1] - one[0]  # rendering adds the same queries for 1 and 3 people
