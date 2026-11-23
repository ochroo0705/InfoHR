"""Shared users, rows and fixtures of the log API tests (test_logs_api.py and test_logs_export_api.py).

A test module imports what it uses by name, e.g. `from api.tests.logs_support import hr, own  # noqa: F401`.
This is not a test module: pytest does not collect it.
"""

from datetime import date
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, SystemLogEntry, User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees.models import ActivityEntry, ActivityKind, Employee
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values
from macs.models import Branch

PASSWORD = "x-long-pass-123"  # noqa: S105
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}


def _user(name: str, group: str | None, *, first: str = "", last: str = "") -> User:
    user = User.objects.create_user(name, password=PASSWORD, first_name=first, last_name=last)  # noqa: S106
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _entry(employee: Employee, message: str, **fields: Any) -> ActivityEntry:
    fields.setdefault("kind", ActivityKind.CHANGED)
    return ActivityEntry.objects.create(employee=employee, message=message, **fields)


def _system_entry(message: str, **fields: Any) -> SystemLogEntry:
    fields.setdefault("category", "hr")
    fields.setdefault("action", "login")
    return SystemLogEntry.objects.create(message=message, **fields)


def take_export_switch(role: str) -> None:
    """Take `accounts.export_lists` away from a role group (the migrations give it to HR, Admin and Accountant)."""
    export_perm = Permission.objects.get(codename="export_lists", content_type__app_label="accounts")
    Group.objects.get(name=role).permissions.remove(export_perm)


@pytest.fixture
def hr() -> User:
    return _user("logs_api_hr", roles.HR, first="Оюун", last="Хүний")


@pytest.fixture
def admin() -> User:
    return _user("logs_api_admin", roles.ADMIN, first="Болд", last="Админ")


@pytest.fixture
def auditor() -> User:
    return _user("logs_api_auditor", roles.AUDITOR)


@pytest.fixture
def job_values() -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def own(hr: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(
        hire_values("УБ99120001"),
        {},
        start=date(2026, 1, 5),
        job=dict(job_values),
        salary=None,
        by=hr,
        with_order=False,
    )


@pytest.fixture
def other(hr: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(
        {**hire_values("УБ99120002"), "family_name": "Доржийн", "given_name": "Ганзориг"},
        {},
        start=date(2026, 1, 5),
        job=dict(job_values),
        salary=None,
        by=hr,
        with_order=False,
    )


@pytest.fixture
def scoped(hr: User, job_values: dict[str, Any]) -> tuple[Employee, Employee, User]:
    """Two employees in two branches (inside the north branch, outside it) and a limited HR user who sees north only."""
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    inside = history.hire(
        {**hire_values("УБ00000011"), "family_name": "Дотно", "given_name": "Оюун"},
        {},
        start=date(2026, 1, 5),
        job=dict(job_values),
        salary=None,
        by=hr,
        with_order=False,
    )
    outside = history.hire(
        {**hire_values("УБ00000022"), "family_name": "Гадна", "given_name": "Мөнх"},
        {},
        start=date(2026, 1, 5),
        job=dict(job_values),
        salary=None,
        by=hr,
        with_order=False,
    )
    Employee.objects.filter(pk=inside.pk).update(branch_id=north.pk)
    Employee.objects.filter(pk=outside.pk).update(branch_id=south.pk)
    limited = _user("logs_api_limited", roles.HR)
    AccessScope.objects.create(user=limited, limited=True, branch_ids=[north.pk])
    return inside, outside, User.objects.get(pk=limited.pk)
