"""Salary/insurance fields and probation months are production employee columns (macs 0003)."""

from datetime import date
from typing import Any

from accounts.models import User
from django.test import Client
from leave.services import entitlement
from macs.models import InsuredCategory

from employees.models import Employee
from employees.services import history, macs_writes, records

from .conftest import hire_values


def login_as(client: Client, role: str, name: str = "viewer") -> User:
    from django.contrib.auth.models import Group

    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def test_salary_form_saves_to_employee_row_and_logs(client: Client, hired: Employee) -> None:
    category = InsuredCategory.objects.create(name="Тест ангилал")
    login_as(client, "Accountant")
    data = {
        "si-social_insurance_no": "НД-001",
        "si-health_insurance_no": "ЭМ-002",
        "si-insured_category": category.pk,
        "si-taxpayer_no": "TAX-3",
        "si-has_disability": "on",
    }
    assert client.post(f"/employees/{hired.pk}/save/", data).status_code == 303
    hired.refresh_from_db()
    assert hired.social_insurance_no == "НД-001"
    assert hired.health_insurance_no == "ЭМ-002"
    assert hired.insured_category_id == category.pk
    assert hired.taxpayer_no == "TAX-3"
    assert hired.has_disability is True
    entry = hired.activity.get(message__contains="Цалин, даатгалын")
    assert entry.sensitive
    assert {"field": "Хөгжлийн бэрхшээлтэй", "old": "Үгүй", "new": "Тийм"} in entry.changes
    assert {"field": "НДД-ийн дугаар", "old": "", "new": "НД-001"} in entry.changes


def test_hire_stores_insurance_columns(actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(hire_values("УБ55667788"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    records.update_salary_insurance(emp, {"social_insurance_no": "НД-H", "taxpayer_no": "T-H"}, actor)
    emp = Employee.objects.get(pk=emp.pk)
    assert emp.social_insurance_no == "НД-H" and emp.taxpayer_no == "T-H"
    assert emp.has_disability is False


def test_legacy_production_values_show_on_detail(client: Client, hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(social_insurance_no="LEG-NDD", health_insurance_no="LEG-EMD")
    login_as(client, "Accountant")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "LEG-NDD" in body and "LEG-EMD" in body


def test_disability_column_drives_leave_entitlement(actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(hire_values("УБ55667799"), {}, start=date(2024, 3, 1), job=job_values, salary=None, by=actor)
    records.update_salary_insurance(emp, {"has_disability": True}, actor)
    emp = Employee.objects.get(pk=emp.pk)
    assert "хөгжлийн бэрхшээлтэй" in entitlement.entitled(emp, date(2026, 3, 1)).breakdown


def test_probation_months_on_hire_update_and_clear(actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(
        hire_values("УБ55667700"),
        {"probation_end": date(2026, 4, 5)},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=actor,
    )
    assert Employee.objects.get(pk=emp.pk).probation_months == 3  # 90 days, about 3 months
    records.update_employee(emp, {"probation_end": date(2026, 7, 5)}, actor)
    assert Employee.objects.get(pk=emp.pk).probation_months == 6  # 181 days
    records.update_employee(emp, {"probation_end": None}, actor)
    assert Employee.objects.get(pk=emp.pk).probation_months is None


def test_probation_months_rounding_and_minimum() -> None:
    start = date(2026, 1, 5)
    assert macs_writes.probation_months(start, None) is None
    assert macs_writes.probation_months(start, date(2026, 1, 10)) == 1  # under half a month still counts as 1
    assert macs_writes.probation_months(start, date(2026, 1, 3)) == 1  # end before start still at least 1


def test_probation_counts_from_current_hire_not_first_hire_date(actor: User, job_values: dict[str, Any]) -> None:
    values = hire_values("УБ55667711") | {"first_hire_date": date(2018, 6, 1)}
    emp = history.hire(
        values,
        {"probation_end": date(2026, 4, 5)},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=actor,
    )
    assert Employee.objects.get(pk=emp.pk).probation_months == 3
