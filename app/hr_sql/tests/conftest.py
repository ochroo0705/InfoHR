"""Shared Firebird fixtures for the governed SQL tests: the installed objects, and a small world of committed
employees, branches and logins with different rights.

Firebird only. Committed rows are made on `default` in autocommit (django_db_blocker.unblock), because the governed
connection is another connection and sees only committed rows. Every fixture removes what it made.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connections
from employees.models import EmployeeExt, ensure_ext
from macs.models import Branch, Employee
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.connection import governed_connection

PASSWORD = "x-long-pass-123"  # noqa: S105 (a throw-away test login)


def _firebird_only() -> None:
    if connections["default"].vendor != "firebird":
        pytest.skip("the governed views are Firebird objects")


def _drop_objects() -> None:
    with connections["default"].cursor() as cursor:
        cursor.execute("DROP VIEW GOV_LOANS")
        cursor.execute("DROP VIEW GOV_SALARY")
        cursor.execute("DROP VIEW GOV_ORDERS")
        cursor.execute("DROP VIEW GOV_LEAVE")
        cursor.execute("DROP VIEW GOV_CHILDREN")
        cursor.execute("DROP VIEW GOV_EMPLOYEES")
        cursor.execute("DROP TABLE GOV_SCOPE")


@pytest.fixture
def governed_objects(django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    """Installs the governed objects (committed) and drops them after the test."""
    _firebird_only()
    with django_db_blocker.unblock():
        call_command("governed_views", "install")
        try:
            yield
        finally:
            governed_connection().close()  # the connection must let go of the objects before DROP
            _drop_objects()


@dataclass(frozen=True)
class World:
    branch_a: Branch
    branch_b: Branch
    emp_a: Employee  # in branch A, linked to the `own` login
    emp_b: Employee  # in branch B
    emp_none: Employee  # in branch B, linked to nobody
    hr: User  # HR role: every employee
    limited: User  # HR role, AccessScope limited to branch A
    own: User  # Employee role, linked to emp_a only
    nobody: User  # Employee role, no linked record
    inactive: User  # HR role, switched off
    accountant: User  # Accountant role (has macs.view_salary), every employee
    admin: User  # Admin role (has macs.view_salary), every employee
    auditor: User  # Auditor role: system log only, no employee data


def _login(name: str, role: str | None) -> User:
    user = User.objects.create_user(f"{name}_{uuid.uuid4().hex[:8]}", password=PASSWORD)
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # a fresh permission cache


@pytest.fixture
def world(django_db_blocker: DjangoDbBlocker) -> Iterator[World]:
    """A few committed employees and logins with different rights. Removed after the test."""
    _firebird_only()
    with django_db_blocker.unblock():
        tag = uuid.uuid4().hex[:6]
        branch_a = Branch.objects.create(name=f"Салбар А {tag}")
        branch_b = Branch.objects.create(name=f"Салбар Б {tag}")
        emp_a = Employee.objects.create(
            given_name="Тест", family_name="А", gender="M", branch=branch_a, birth_date=date(1980, 5, 17)
        )
        emp_b = Employee.objects.create(
            given_name="Тест", family_name="Б", gender="F", branch=branch_b, birth_date=date(1990, 11, 2)
        )
        emp_none = Employee.objects.create(
            given_name="Тест", family_name="В", gender="M", branch=branch_b, birth_date=date(1970, 1, 30)
        )
        hr = _login("gov_hr", roles.HR)
        limited = _login("gov_limited", roles.HR)
        AccessScope.objects.create(user=limited, limited=True, branch_ids=[branch_a.pk])
        limited = User.objects.get(pk=limited.pk)
        own = _login("gov_own", roles.EMPLOYEE)
        ext = ensure_ext(emp_a)
        ext.user = own
        ext.save(update_fields=["user"])
        nobody = _login("gov_nobody", roles.EMPLOYEE)
        inactive = _login("gov_inactive", roles.HR)
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        inactive = User.objects.get(pk=inactive.pk)
        accountant = _login("gov_accountant", roles.ACCOUNTANT)
        admin = _login("gov_admin", roles.ADMIN)
        auditor = _login("gov_auditor", roles.AUDITOR)
        made = World(
            branch_a=branch_a,
            branch_b=branch_b,
            emp_a=emp_a,
            emp_b=emp_b,
            emp_none=emp_none,
            hr=hr,
            limited=limited,
            own=own,
            nobody=nobody,
            inactive=inactive,
            accountant=accountant,
            admin=admin,
            auditor=auditor,
        )
        try:
            yield made
        finally:
            EmployeeExt.objects.filter(employee__in=[emp_a, emp_b, emp_none]).delete()
            Employee.objects.filter(pk__in=[emp_a.pk, emp_b.pk, emp_none.pk]).delete()
            User.objects.filter(
                pk__in=[hr.pk, limited.pk, own.pk, nobody.pk, inactive.pk, accountant.pk, admin.pk, auditor.pk]
            ).delete()
            Branch.objects.filter(pk__in=[branch_a.pk, branch_b.pk]).delete()
