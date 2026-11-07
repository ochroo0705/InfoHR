from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.db import DatabaseError, IntegrityError, connection
from macs.models import ClothesSize

from employees.models import Employee, EmployeeExt, ensure_ext
from employees.services import history, macs_writes


@pytest.fixture(autouse=True)
def _no_offboarding_templates(request: pytest.FixtureRequest) -> None:
    """The migration seeds an offboarding checklist template that gates every termination. The event tests of this
    app are about the events, so they run without it; the gate has its own tests in app/checklists."""
    if request.node.get_closest_marker("django_db") is None and "db" not in request.fixturenames:
        return
    request.getfixturevalue("db")
    from checklists.models import ChecklistTemplate

    ChecklistTemplate.objects.update(active=False)


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """DailySyncMiddleware runs the sync (it rewrites contract and job columns from the job records) on the first
    signed-in request of each process, so whichever test made that request saw the rewrite and a test that wrote a
    column straight into the row failed when run alone. Tests call sync_all_employees themselves when they want it;
    the ones that exercise the middleware opt back in with @pytest.mark.real_daily_sync."""
    if request.node.get_closest_marker("real_daily_sync") is not None:
        return
    from employees import daily_sync

    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


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


def duplicate_start_refused(trigger: str) -> AbstractContextManager[Any]:
    """Expects a second history row with the same start day to be refused.

    PostgreSQL: the unique (employee, start_date) constraint raises IntegrityError.
    Firebird: the BEFORE INSERT no-overlap trigger named in `trigger` refuses the row first (exception 59, a
    DatabaseError). Both refuse the same thing: two periods of one employee that start on the same day.
    """
    if connection.vendor == "firebird":
        return pytest.raises(DatabaseError, match=trigger)
    return pytest.raises(IntegrityError)


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
