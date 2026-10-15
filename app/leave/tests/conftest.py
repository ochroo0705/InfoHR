from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from employees.models import Department, Employee, Position
from employees.services import history

from leave.models import LeaveType


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("leave_actor", password="x-long-pass-123")  # noqa: S106


def make_employee(by: User, *, hired: date, register_no: str = "УБ99112233", prior_months: int = 0) -> Employee:
    job: dict[str, Any] = {
        "position": Position.objects.get_or_create(name="Нягтлан")[0],
        "department": Department.objects.get_or_create(name="Санхүү")[0],
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    e = Employee(
        family_name="Батын",
        given_name="Сараа",
        register_no=register_no,
        birth_date=date(1990, 1, 1),
        gender="female",
        work_phone="99112233",
        first_hire_date=hired,
        prior_service_years=prior_months // 12,
        prior_service_months=prior_months % 12,
    )
    return history.hire(e, start=hired, job=job, salary=Decimal("2500000"), by=by)


@pytest.fixture
def employee(actor: User) -> Employee:
    return make_employee(actor, hired=date(2024, 3, 1))


@pytest.fixture
def annual(db: None) -> LeaveType:
    return LeaveType.objects.get(code=LeaveType.ANNUAL)
