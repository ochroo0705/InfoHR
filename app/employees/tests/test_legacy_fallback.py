"""Employees with a MACS row but no HR job/salary history show the MACS values (QC 1a–1c)."""

from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone

from employees.listing import current_salary, row_for
from employees.models import Employee, ensure_ext
from employees.services import macs_writes

from .conftest import hire_values
from .test_insurance_columns import login_as

pytestmark = pytest.mark.django_db


def _legacy(actor: User, job_values: dict[str, Any], **columns: Any) -> Employee:
    emp = macs_writes.create_employee(hire_values(), {}, code=macs_writes.next_code(), by=actor)
    ensure_ext(emp)
    values = {"department": job_values["department"], "position": job_values["position"], "salary": Decimal("1800000")}
    Employee.objects.filter(pk=emp.pk).update(**{**values, **columns})
    return Employee.objects.get(pk=emp.pk)


def test_legacy_row_shows_macs_department_status_and_salary(actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values)
    row = row_for(emp, timezone.localdate())
    assert row.legacy and row.state == "active"
    assert row.job is not None and row.job.department_id == job_values["department"].pk and row.job.pk is None
    salary = current_salary(emp, timezone.localdate())
    assert salary is not None and salary.base_salary == Decimal("1800000") and salary.pk is None


@pytest.mark.parametrize(("columns", "state"), [({"emptype": 3}, "left"), ({"taken_leave": 1}, "long_leave")])
def test_legacy_state_follows_macs_flags(
    actor: User, job_values: dict[str, Any], columns: dict[str, Any], state: str
) -> None:
    assert row_for(_legacy(actor, job_values, **columns), timezone.localdate()).state == state


def test_no_fallback_once_hr_has_history(hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(salary=Decimal("1"))
    hired = Employee.objects.get(pk=hired.pk)
    assert not row_for(hired, timezone.localdate()).legacy
    assert current_salary(hired, timezone.localdate()).base_salary == Decimal("2500000")  # type: ignore[union-attr]


def test_legacy_detail_page_shows_values_and_event_menu(
    client: Client, actor: User, job_values: dict[str, Any]
) -> None:
    emp = _legacy(actor, job_values)
    login_as(client, "Accountant")
    body = client.get(f"/employees/{emp.pk}/").content.decode()
    assert "Санхүү" in body and "1,800,000" in body.replace("\u202f", ",").replace(" ", ",")
    assert f"/employees/{emp.pk}/event/salary_change/" in body  # QC 1d: the first event starts the HR history


def test_legacy_list_shows_working_employee(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values)
    login_as(client, "Accountant")
    assert f'href="/employees/{emp.pk}/"' in client.get("/employees/").content.decode()  # default hides only "left"
