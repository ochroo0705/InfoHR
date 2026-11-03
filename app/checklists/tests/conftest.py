"""Shared fixtures for the checklists tests."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from employees.models import Event
from employees.services import history, macs_writes
from macs.models import Employee, FiredReason


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("hr_actor", password="x-long-pass-123")  # noqa: S106


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(actor: User, job_values: dict[str, Any]) -> Employee:
    values = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "УБ99112233",
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    return history.hire(values, {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)


@pytest.fixture
def fired_reason(db: None) -> FiredReason:
    return FiredReason.objects.get_or_create(name="Нас барсан")[0]


@pytest.fixture
def termination(hired: Employee, actor: User, fired_reason: FiredReason) -> Event:
    """A bare termination row, enough for a checklist to be completed for it."""
    return Event.objects.create(
        employee=hired, type="termination", effective=date(2026, 11, 30), fired_reason=fired_reason, created_by=actor
    )
