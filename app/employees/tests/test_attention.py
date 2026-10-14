from datetime import date, timedelta
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from employees import attention
from employees.listing import employee_rows
from employees.models import Employee, SalaryInsurance, SetupItem
from employees.services import history

from .conftest import new_employee
from .test_views import login_as

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def user_in(role: str, name: str = "u1") -> User:
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return u


def texts(user: User, today: date = TODAY) -> list[str]:
    from employees.models import Employee as E

    return [a.text for a in attention.items(user, employee_rows(E.objects.all(), today), today)]


@pytest.fixture
def emp(hired: Employee) -> Employee:
    hired.emergency_name, hired.emergency_phone = "А", "99"
    hired.setup_required = False
    hired.save()
    SalaryInsurance.objects.create(employee=hired, account_no="123")
    return hired


@pytest.mark.parametrize(("delta", "shown"), [(-1, False), (0, True), (14, True), (15, False)])
def test_probation_boundaries(emp: Employee, delta: int, shown: bool) -> None:
    emp.probation_end = TODAY + timedelta(days=delta)
    emp.save()
    assert any("Туршилтын" in t for t in texts(user_in("HR"))) is shown


@pytest.mark.parametrize(("delta", "text"), [(0, "дуусна"), (30, "дуусна"), (31, None), (-1, "дууссан")])
def test_contract_boundaries(emp: Employee, delta: int, text: str | None) -> None:
    job = emp.job_records.get()
    job.contract_end = TODAY + timedelta(days=delta)
    job.save()
    found = [t for t in texts(user_in("HR")) if t.startswith("Гэрээ")]
    assert (found == []) if text is None else (len(found) == 1 and found[0].endswith(text))


def test_setup_rule_uses_viewer_visible_items(emp: Employee) -> None:
    emp.setup_required = True
    emp.save()
    hr = user_in("HR")
    assert "Бүрдүүлэлт дутуу" in texts(hr)
    emp.setup_required = False
    emp.save()
    assert "Бүрдүүлэлт дутуу" not in texts(hr)


def test_accountant_sees_neither_setup_nor_personal(emp: Employee) -> None:
    emp.setup_required, emp.emergency_name = True, ""
    emp.save()
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")
    got = texts(user_in("Accountant"))
    assert got == ["Банкны мэдээлэл бүртгээгүй"]


def test_hr_never_sees_bank_rule(emp: Employee) -> None:
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")
    emp.emergency_phone = ""
    emp.save()
    got = texts(user_in("HR"))
    assert got == ["Яаралтай үед холбогдох хүн бүртгээгүй"]


def test_employee_role_empty(emp: Employee) -> None:
    emp.emergency_name = ""
    emp.save()
    assert texts(user_in("Employee")) == []


def test_left_excluded_and_sorted(emp: Employee, actor: User, job_values: dict[str, Any]) -> None:
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")
    other = history.hire(new_employee("УБ00000002"), start=date(2025, 1, 1), job=job_values, salary=None, by=actor)
    other.family_name = "Аавын"
    other.save()
    admin = User.objects.create_superuser("root", password="x-long-pass-123")  # noqa: S106
    rows = employee_rows(Employee.objects.all(), TODAY)
    names = [a.employee.full_name for a in attention.items(admin, rows, TODAY) if a.kind == "bank"]
    assert names == ["Аавын Сараа", "Батын Сараа"]
    history.change_job(
        other, effective=date(2025, 6, 1), changes={"status": "left"}, change_type="correction", note="", by=actor
    )
    rows = employee_rows(Employee.objects.all(), TODAY)
    assert {a.employee.pk for a in attention.items(admin, rows, TODAY)} == {emp.pk}


def test_strip_on_full_page_only(client: Client, emp: Employee) -> None:
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")
    login_as(client, "Accountant")
    url = reverse("employees:list")
    assert "Анхаарах (1)" in client.get(url).content.decode()
    assert "Анхаарах" not in client.get(url, HTTP_HX_REQUEST="true").content.decode()


def _fully_ticked_without_bank(emp: Employee) -> None:
    emp.setup_required = True
    emp.user = User.objects.create_user("linked", password="x-long-pass-123")  # noqa: S106
    emp.save()
    for key in ("contract", "id_copy", "equipment"):
        SetupItem.objects.create(employee=emp, key=key)
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")


def test_setup_complete_for_hr_but_not_admin_when_only_bank_missing(emp: Employee) -> None:
    _fully_ticked_without_bank(emp)
    assert "Бүрдүүлэлт дутуу" not in texts(user_in("HR"))
    admin = User.objects.create_superuser("root", password="x-long-pass-123")  # noqa: S106
    assert "Бүрдүүлэлт дутуу" in texts(admin)


def test_missing_salary_insurance_row_flags_bank_for_accountant(emp: Employee) -> None:
    SalaryInsurance.objects.filter(employee=emp).delete()
    assert "Банкны мэдээлэл бүртгээгүй" in texts(user_in("Accountant"))
