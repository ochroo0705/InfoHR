from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User

from employees.models import Department, Employee, Position
from employees.services import history


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("hr_actor", password="x-long-pass-123")  # noqa: S106


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": Position.objects.create(name="Нягтлан"),
        "department": Department.objects.create(name="Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def new_employee(register_no: str = "УБ99112233") -> Employee:
    return Employee(
        family_name="Батын",
        given_name="Сараа",
        register_no=register_no,
        birth_date=date(1999, 11, 22),
        gender="female",
        work_phone="99112233",
        first_hire_date=date(2026, 1, 5),
    )


@pytest.fixture
def hired(actor: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(new_employee(), start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)
