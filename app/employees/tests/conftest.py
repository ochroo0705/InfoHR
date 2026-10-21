from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from macs.models import ClothesSize

from employees.models import Employee, EmployeeExt, ensure_ext
from employees.services import history, macs_writes


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


def hire_values(register_no: str = "УБ99112233") -> dict[str, Any]:
    return {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": register_no,
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }


@pytest.fixture
def hired(actor: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)


def _ext(employee: Employee) -> EmployeeExt:
    """The HR row, cached on the employee instance so the test sees its own writes."""
    ext = ensure_ext(employee)
    employee.ext = ext
    return ext


def link_login(employee: Employee, user: User) -> None:
    """Link a login to a production employee (the login lives on the HR row, EmployeeExt.user)."""
    ext = _ext(employee)
    ext.user = user
    ext.save(update_fields=["user"])


def set_ext(employee: Employee, **values: Any) -> None:
    """Set HR-only fields (EmployeeExt) on an employee and save them."""
    ext = _ext(employee)
    for name, value in values.items():
        setattr(ext, name, value)
    ext.save()


def set_account(employee: Employee, number: str) -> None:
    """Bank account number: a production column (Employee.account_no), written through macs_writes."""
    macs_writes.update_employee_columns(employee, {"account_no": number})


def named(model: type[Any], name: str) -> Any:
    """A code-list row (production lookup table) by name; created when the test database has none."""
    defaults = {"size_type": "shoes"} if model is ClothesSize else {}  # the size table needs its kind
    return model.objects.get_or_create(name=name, defaults=defaults)[0]
