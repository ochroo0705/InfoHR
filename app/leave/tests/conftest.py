from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from employees.models import Department, Employee, Position
from employees.services import history, macs_writes
from macs.models import LeaveTypeRow

from leave.models import LeaveSettings, LeaveTypeExt


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("leave_actor", password="x-long-pass-123")  # noqa: S106


def make_employee(by: User, *, hired: date, register_no: str = "УБ99112233", prior_months: int = 0) -> Employee:
    job: dict[str, Any] = {
        "position": Position.objects.filter(name="Нягтлан").first() or macs_writes.save_position("Нягтлан"),
        "department": Department.objects.filter(name="Санхүү").first() or macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": register_no,
        "birth_date": date(1990, 1, 1),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": hired,
        "prior_service_years": prior_months // 12,
        "work_conditions": 1,
    }
    return history.hire(
        values,
        {"prior_service_months": prior_months % 12},
        start=hired,
        job=job,
        salary=Decimal("2500000"),
        by=by,
    )


@pytest.fixture
def employee(actor: User) -> Employee:
    return make_employee(actor, hired=date(2024, 3, 1))


@pytest.fixture
def annual(db: None) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=True, is_paid=True)
    return row


@pytest.fixture
def sick(db: None) -> LeaveTypeRow:
    """A leave type that does not use the annual balance."""
    row = LeaveTypeRow.objects.create(name="Өвчний амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True)
    return row


@pytest.fixture
def grants_on(db: None) -> None:
    """Automatic annual grants on (spec §6): grant periods exist for the employment years."""
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
