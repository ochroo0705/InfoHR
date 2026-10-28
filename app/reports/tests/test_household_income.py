from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from macs.models import EmployeeIncomeRow, FamilyRelation, FamilyRow, IncomeLevel

from reports.filters import Filters
from reports.household_income import NO_LEVEL, REPORT, IncomeLine

from .conftest import legacy

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def own_levels() -> None:
    """The test database may hold production income bands; each test sets its own."""
    IncomeLevel.objects.all().delete()


def _levels(*bands: tuple[str, int, int]) -> None:
    for name, lower, upper in bands:
        IncomeLevel.objects.create(level=name, lower=lower, upper=upper)


def _family(employee: Employee, count: int) -> None:
    relation = FamilyRelation.objects.create(name="Эхнэр, нөхөр", fm_type="spouse")
    for i in range(count):
        FamilyRow.objects.create(employee=employee, relation=relation, given_name=f"Гишүүн{i}")


def _line(user: User, employee: Employee) -> IncomeLine:
    found: list[IncomeLine] = [x for x in REPORT.rows(user, Filters()) if x.person.row.employee.pk == employee.pk]
    assert len(found) == 1
    return found[0]


def test_income_column_is_used_when_set(accountant_user: User, actor: User, job_values: dict[str, Any]) -> None:
    emp = legacy(actor, job_values, salary=Decimal("1800000"))
    EmployeeIncomeRow.objects.filter(pk=emp.pk).update(income=1200000)
    assert _line(accountant_user, emp).income == 1200000


def test_salary_is_used_when_income_is_zero_or_missing(
    accountant_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    zero = legacy(actor, job_values, salary=Decimal("1800000"))
    EmployeeIncomeRow.objects.filter(pk=zero.pk).update(income=0)
    missing = legacy(actor, job_values, salary=Decimal("900000"))
    EmployeeIncomeRow.objects.filter(pk=missing.pk).update(income=None)
    assert _line(accountant_user, zero).income == 1800000
    assert _line(accountant_user, missing).income == 900000


def test_hr_salary_record_is_used_without_income(accountant_user: User, hired: Employee) -> None:
    """A person hired in HR has a salary record and no income figure: the record's base salary counts."""
    EmployeeIncomeRow.objects.filter(pk=hired.pk).update(income=None)
    assert _line(accountant_user, hired).income == 2500000


def test_zero_income_is_no_band_when_no_band_contains_zero(
    accountant_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    """Income 0 is not above the lower limit 0, so the band (0, 100000] does not cover it."""
    _levels(("A", 0, 100000))
    emp = legacy(actor, job_values, salary=Decimal("0"))
    EmployeeIncomeRow.objects.filter(pk=emp.pk).update(income=None)
    line = _line(accountant_user, emp)
    assert (line.income, line.per_person, line.level) == (0, 0, NO_LEVEL)


def test_zero_income_is_looked_up_in_a_band_that_contains_zero(
    accountant_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    """The lookup runs on a per-person income of 0: a band (-1, 0] holds it."""
    _levels(("Доод", -1, 0))
    emp = legacy(actor, job_values, salary=Decimal("0"))
    EmployeeIncomeRow.objects.filter(pk=emp.pk).update(income=0)
    assert _line(accountant_user, emp).level == "Доод"


def test_family_count_includes_the_employee(accountant_user: User, actor: User, job_values: dict[str, Any]) -> None:
    emp = legacy(actor, job_values)
    EmployeeIncomeRow.objects.filter(pk=emp.pk).update(income=1000000)
    _family(emp, 2)
    line = _line(accountant_user, emp)
    assert line.family_qty == 3
    assert line.per_person == 333333  # integer division


def test_level_boundaries(accountant_user: User, actor: User, job_values: dict[str, Any]) -> None:
    _levels(("A", 0, 100000), ("B", 100000, 500000))
    at_top_of_a = legacy(actor, job_values)
    just_above_a = legacy(actor, job_values)
    above_all = legacy(actor, job_values)
    for emp, income in ((at_top_of_a, 100000), (just_above_a, 100001), (above_all, 500001)):
        EmployeeIncomeRow.objects.filter(pk=emp.pk).update(income=income)
    assert _line(accountant_user, at_top_of_a).level == "A"
    assert _line(accountant_user, just_above_a).level == "B"
    assert _line(accountant_user, above_all).level == NO_LEVEL


def test_accountant_without_personal_right_sees_no_age_or_gender(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    response = client.get("/reports/household-income/")
    assert response.status_code == 200
    page = response.content.decode()
    assert "Өрхийн амьжиргааны баталгаажих түвшний тайлан" in page
    assert ">Нас<" not in page
    assert ">Хүйс<" not in page


def test_admin_sees_age_and_gender_headers(client: Client, login_as: Callable[..., User]) -> None:
    """The positive control for the accountant test: with view_personal the two headers are shown."""
    login_as(client, "Admin", "adm")
    page = client.get("/reports/household-income/").content.decode()
    assert ">Нас<" in page
    assert ">Хүйс<" in page


def test_hr_without_salary_right_is_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr")
    assert client.get("/reports/household-income/").status_code == 403


def test_employee_role_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "emp")
    assert client.get("/reports/household-income/").status_code == 403
