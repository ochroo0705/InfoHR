"""The governed salary and loan views (Task 8): GOV_SALARY and GOV_LOANS, offered only with macs.view_salary.

Firebird only. Salary and loan rows are committed (autocommit on `default`), because the governed connection is
another connection and sees only committed rows. The rows and the extra logins are removed after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.db import connection, transaction
from employees.models import ChangeType, SalaryRecord
from macs.models import LoanRefRow, LoanRow
from pytest_django.plugin import DjangoDbBlocker
from sqlcore.runner import DEFAULT_LIMITS, Answered, Refused, run_question

from hr_sql.catalogue import catalogue_for
from hr_sql.connection import GOVERNED_ALIAS, governed_connection
from hr_sql.host import HrHost
from hr_sql.tests.conftest import PASSWORD, World

SALARY_COLUMNS = ["SALARY_ID", "EMP_ID", "START_DATE", "END_DATE", "BASE_SALARY", "CHANGE_TYPE"]
LOAN_COLUMNS = ["LOAN_ID", "EMP_ID", "LOAN_DATE", "END_DATE", "AMOUNT", "MONTHLY_PAYMENT", "REASON"]
SALARY_VIEWS = ("GOV_SALARY", "GOV_LOANS")
PRIVATE_NOTE = "private salary note"
LOAN_AMOUNT = Decimal("1234567.89")


@dataclass(frozen=True)
class Money:
    world: World
    salary_a: int  # SalaryRecord id of emp_a (branch A), base salary 1234567.89
    salary_b: int  # SalaryRecord id of emp_b (branch B)
    loan_a: int  # LoanRow id of emp_a, reason REASON_TEXT
    loan_b: int  # LoanRow id of emp_b
    reason_text: str


def _make_login(name: str, role: str) -> User:
    user = User.objects.create_user(f"{name}_{uuid.uuid4().hex[:8]}", password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # a fresh permission cache


def _group_has_salary_right(role: str) -> bool:
    return (
        Group.objects.get(name=role)
        .permissions.filter(codename="view_salary", content_type__app_label="macs")
        .exists()
    )


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def money(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Money]:
    """Committed salary and loan rows for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    tag = uuid.uuid4().hex[:6]
    reason_text = f"Тест үндэслэл {tag}"
    salary_ids: list[int] = []
    loan_ids: list[int] = []
    with django_db_blocker.unblock():
        # loan_refs has a NOT NULL ref_type the mirror does not map: insert as SQL with ref_type 1 (loan reasons).
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO loan_refs (description, ref_type) VALUES (%s, %s) RETURNING ref_id", [reason_text, 1]
            )
            reason_id = int(cursor.fetchone()[0])
        reason = LoanRefRow.objects.get(pk=reason_id)
        try:
            salary_a = SalaryRecord.objects.create(
                employee=ready.emp_a,
                start_date=date(2026, 1, 1),
                base_salary=LOAN_AMOUNT,
                change_type=ChangeType.HIRE,
                note=PRIVATE_NOTE,
            )
            salary_b = SalaryRecord.objects.create(
                employee=ready.emp_b,
                start_date=date(2026, 1, 1),
                base_salary=Decimal("900000.50"),
                change_type=ChangeType.HIRE,
                note=PRIVATE_NOTE,
            )
            salary_ids = [salary_a.pk, salary_b.pk]
            loan_a = LoanRow.objects.create(
                employee=ready.emp_a,
                get_date=date(2026, 2, 1),
                end_date=date(2027, 2, 1),
                amount=LOAN_AMOUNT,
                pay_permonth=Decimal("102880.66"),
                loan_ref=reason,
            )
            loan_b = LoanRow.objects.create(
                employee=ready.emp_b,
                get_date=date(2026, 3, 1),
                end_date=date(2027, 3, 1),
                amount=Decimal("500000.00"),
                pay_permonth=Decimal("41666.67"),
                loan_ref=reason,
            )
            loan_ids = [loan_a.pk, loan_b.pk]
            yield Money(
                world=ready,
                salary_a=salary_a.pk,
                salary_b=salary_b.pk,
                loan_a=loan_a.pk,
                loan_b=loan_b.pk,
                reason_text=reason_text,
            )
        finally:
            LoanRow.objects.filter(pk__in=loan_ids).delete()
            SalaryRecord.objects.filter(pk__in=salary_ids).delete()
            LoanRefRow.objects.filter(pk=reason.pk).delete()


@pytest.fixture
def limited_accountant(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[User]:
    """An Accountant limited to branch A. Removed after the test."""
    with django_db_blocker.unblock():
        user = _make_login("gov_acc_limited", roles.ACCOUNTANT)
        AccessScope.objects.create(user=user, limited=True, branch_ids=[ready.branch_a.pk])
        user = User.objects.get(pk=user.pk)
        try:
            yield user
        finally:
            User.objects.filter(pk=user.pk).delete()


def _rows(user: User, sql: str) -> list[tuple[Any, ...]]:
    outcome = run_question(HrHost(), user, sql, DEFAULT_LIMITS)
    if isinstance(outcome, Refused):
        pytest.fail(f"Refused: {outcome.reason}")
    assert isinstance(outcome, Answered)
    return list(outcome.result.rows)


def _refusal(user: User, sql: str) -> str:
    outcome = run_question(HrHost(), user, sql, DEFAULT_LIMITS)
    assert isinstance(outcome, Refused), "the question should have been refused"
    return outcome.reason


def _columns(view: str) -> list[str]:
    with transaction.atomic(using=GOVERNED_ALIAS), governed_connection().cursor() as cursor:
        cursor.execute(f"SELECT * FROM {view} WHERE 1 = 0")  # noqa: S608 (fixed view names)
        return [str(column[0]).strip() for column in cursor.description or ()]


def _ids(rows: list[tuple[Any, ...]]) -> set[int]:
    return {int(str(row[0])) for row in rows}


@pytest.mark.parametrize("role", [roles.ADMIN, roles.HR, roles.ACCOUNTANT, roles.EMPLOYEE, roles.AUDITOR])
def test_salary_views_only_for_roles_with_the_right(
    world: World, django_db_blocker: DjangoDbBlocker, role: str
) -> None:
    with django_db_blocker.unblock():
        user = _make_login("gov_role", role)
        try:
            names = [view.name for view in catalogue_for(user).views]
        finally:
            User.objects.filter(pk=user.pk).delete()

    has_right = _group_has_salary_right(role)
    assert ("GOV_SALARY" in names) is has_right
    assert ("GOV_LOANS" in names) is has_right


def test_salary_views_listed_for_accountant_and_admin_only(world: World) -> None:
    assert [view.name for view in catalogue_for(world.accountant).views][-2:] == list(SALARY_VIEWS)
    assert [view.name for view in catalogue_for(world.admin).views][-2:] == list(SALARY_VIEWS)
    assert not {"GOV_SALARY", "GOV_LOANS"} & {view.name for view in catalogue_for(world.hr).views}


@pytest.mark.parametrize("sql", [
    "SELECT BASE_SALARY FROM GOV_SALARY",
    "SELECT AMOUNT FROM GOV_LOANS",
    "SELECT COUNT(*) FROM GOV_SALARY s JOIN GOV_EMPLOYEES e ON e.EMP_ID = s.EMP_ID",
])
@pytest.mark.parametrize("who", ["hr", "limited", "own", "nobody", "inactive"])
def test_salary_question_refused_without_the_right(money: Money, who: str, sql: str) -> None:
    reason = _refusal(getattr(money.world, who), sql)

    assert "not a governed view" in reason


def test_salary_view_columns(ready: World) -> None:
    assert _columns("GOV_SALARY") == SALARY_COLUMNS
    assert _columns("GOV_LOANS") == LOAN_COLUMNS


def test_accountant_sees_salary_of_every_visible_employee(money: Money) -> None:
    ids = f"{money.salary_a}, {money.salary_b}"
    sql = f"SELECT SALARY_ID FROM GOV_SALARY WHERE SALARY_ID IN ({ids})"  # noqa: S608 (ids are ints)

    assert _ids(_rows(money.world.accountant, sql)) == {money.salary_a, money.salary_b}
    assert _ids(_rows(money.world.admin, sql)) == {money.salary_a, money.salary_b}


def test_limited_accountant_sees_only_branch_salary(money: Money, limited_accountant: User) -> None:
    ids = f"{money.salary_a}, {money.salary_b}"
    sql = f"SELECT SALARY_ID FROM GOV_SALARY WHERE SALARY_ID IN ({ids})"  # noqa: S608 (ids are ints)

    assert _ids(_rows(limited_accountant, sql)) == {money.salary_a}


def test_salary_amount_is_exact(money: Money) -> None:
    rows = _rows(
        money.world.accountant,
        f"SELECT BASE_SALARY FROM GOV_SALARY WHERE SALARY_ID = {money.salary_a}",  # noqa: S608 (id is an int)
    )

    assert rows == [(Decimal("1234567.89"),)]


def test_salary_note_is_not_reachable(money: Money) -> None:
    reason = _refusal(money.world.accountant, "SELECT NOTE FROM GOV_SALARY")

    assert reason.startswith("Column NOTE is not on")
    assert "NOTE" not in _columns("GOV_SALARY")


def test_loans_view_scope_and_reason(money: Money, limited_accountant: User) -> None:
    ids = f"{money.loan_a}, {money.loan_b}"
    sql = f"SELECT LOAN_ID, REASON FROM GOV_LOANS WHERE LOAN_ID IN ({ids})"  # noqa: S608 (ids are ints)

    everyone = {int(str(pk)): reason for pk, reason in _rows(money.world.accountant, sql)}
    limited = {int(str(pk)): reason for pk, reason in _rows(limited_accountant, sql)}

    assert set(everyone) == {money.loan_a, money.loan_b}
    assert everyone[money.loan_a] == money.reason_text
    assert set(limited) == {money.loan_a}


def test_loan_amount_is_exact(money: Money) -> None:
    rows = _rows(
        money.world.accountant,
        f"SELECT AMOUNT FROM GOV_LOANS WHERE LOAN_ID = {money.loan_a}",  # noqa: S608 (id is an int)
    )

    assert rows == [(LOAN_AMOUNT,)]


def test_loans_view_has_no_other_loan_columns(money: Money) -> None:
    columns = _columns("GOV_LOANS")

    assert columns == LOAN_COLUMNS
    assert "PAY_PERMONTH" not in columns
    assert "LOANREF1_IDENT" not in columns


def test_columns_not_in_the_catalogue_are_not_reachable(money: Money) -> None:
    reason = _refusal(money.world.accountant, "SELECT EMP_ID, REGISTER_NO FROM GOV_EMPLOYEES")

    assert reason.startswith("Column REGISTER_NO is not on")


def test_catalogue_describes_the_salary_views_in_plain_words(world: World) -> None:
    views = {view.name: view for view in catalogue_for(world.accountant).views}

    for name, columns in (("GOV_SALARY", SALARY_COLUMNS), ("GOV_LOANS", LOAN_COLUMNS)):
        assert [column.name for column in views[name].columns] == columns
        assert views[name].description
        assert all(column.description for column in views[name].columns)
