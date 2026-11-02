"""An intern gets no automatic annual leave grant; HR can still grant days by hand."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from employees.models import ContractType, Department, Employee, EmployeeType, Position
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values
from macs.models import Entitlement, LeaveTypeRow

from leave.services import ledger

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": Position.objects.filter(name="Нягтлан").first() or macs_writes.save_position("Нягтлан"),
        "department": Department.objects.filter(name="Санхүү").first() or macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def _hire(actor: User, job_values: dict[str, Any], employee_type: EmployeeType, register_no: str) -> Employee:
    job = {**job_values, "employee_type": employee_type}
    if employee_type == EmployeeType.INTERN:
        job.update(
            contract_type=ContractType.FIXED_TERM, contract_start=date(2025, 3, 1), contract_end=date(2027, 2, 28)
        )
    values = {**hire_values(register_no), "first_hire_date": date(2025, 3, 1)}
    return history.hire(values, {}, start=date(2025, 3, 1), job=job, salary=None, by=actor)


def test_staff_gets_the_automatic_grant_and_an_intern_does_not(
    actor: User, job_values: dict[str, Any], annual: LeaveTypeRow
) -> None:
    staff = _hire(actor, job_values, EmployeeType.FULL_TIME, "УБ90000001")
    intern = _hire(actor, job_values, EmployeeType.INTERN, "УБ90000002")
    today = date(2026, 11, 2)
    ledger.ensure_grants(staff, today)
    ledger.ensure_grants(intern, today)
    assert Entitlement.objects.filter(employee=staff).exists()
    assert not Entitlement.objects.filter(employee=intern).exists()


def test_hr_can_still_grant_an_intern_by_hand(actor: User, job_values: dict[str, Any], annual: LeaveTypeRow) -> None:
    intern = _hire(actor, job_values, EmployeeType.INTERN, "УБ90000003")
    ledger.manual_grant(intern, date(2026, 3, 1), date(2027, 2, 28), 2, "Дадлагын амралт", actor)
    assert Entitlement.objects.filter(employee=intern, ent_days=2).exists()
