"""The leak matrix (Task 14a of the governed SQL plan): every role, every governed view, through run_question. Firebird.

Each question is `SELECT COUNT(*) FROM <view>` (or a listing of EMP_ID for the scope checks). The expected answer
comes from the ORM (employees/access.py::visible_employees and the models), never from the views. A view outside
the asker's catalogue must be refused; a view inside it must answer with exactly the ORM count. Nothing in between.

Employees, leave, orders, salary, loans and family rows are committed (autocommit on `default`), because the governed
connection is another connection and sees only committed rows. Every row a test makes is removed again.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.db import connection
from employees.access import own_employee, visible_employees
from employees.models import ChangeType, HrOrder, OrderState, OrderType, SalaryRecord
from macs.models import (
    Branch,
    FamilyRelation,
    FamilyRow,
    LeaveAssign,
    LeaveTypeRow,
    LoanRefRow,
    LoanRow,
)
from pytest_django.plugin import DjangoDbBlocker
from sqlcore.limits import Limits
from sqlcore.runner import Answered, Refused, run_question

from hr_sql.catalogue import catalogue_for
from hr_sql.host import HrHost
from hr_sql.tests.conftest import PASSWORD, World

VIEWS = ("GOV_EMPLOYEES", "GOV_CHILDREN", "GOV_LEAVE", "GOV_ORDERS", "GOV_SALARY", "GOV_LOANS")
SALARY_VIEWS = ("GOV_SALARY", "GOV_LOANS")
LISTING = Limits(max_rows=100_000)  # id listings: the whole test database must fit, so nothing is cut
PRIVATE_NOTE = "private leak-matrix note"


@dataclass(frozen=True)
class Data:
    world: World
    leave_a: int
    leave_b: int
    order_a: int
    order_b: int
    salary_a: int
    salary_b: int
    loan_a: int
    loan_b: int
    child_a: int
    child_b: int


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def data(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Data]:
    """One committed row of each governed kind for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    tag = uuid.uuid4().hex[:6]
    with django_db_blocker.unblock():
        leave_type = LeaveTypeRow.objects.create(name=f"Матрикс {tag}")
        relation = FamilyRelation.objects.filter(fm_type="son").first()
        made_relation = relation is None
        if relation is None:
            relation = FamilyRelation.objects.create(name=f"Хүү {tag}", fm_type="son")
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO loan_refs (description, ref_type) VALUES (%s, %s) RETURNING ref_id", [f"Матрикс {tag}", 1]
            )
            reason_id = int(cursor.fetchone()[0])
        reason = LoanRefRow.objects.get(pk=reason_id)
        leave_a = LeaveAssign.objects.create(
            employee=ready.emp_a,
            leave_type=leave_type,
            date1=date(2026, 3, 1),
            date2=date(2026, 3, 5),
            status=LeaveAssign.APPROVED,
            adays=5,
            comment=PRIVATE_NOTE,
        )
        leave_b = LeaveAssign.objects.create(
            employee=ready.emp_b,
            leave_type=leave_type,
            date1=date(2026, 4, 1),
            date2=date(2026, 4, 2),
            status=LeaveAssign.APPROVED,
            adays=2,
            comment=PRIVATE_NOTE,
        )
        order_a = HrOrder.objects.create(
            employee=ready.emp_a,
            is_hire=True,  # the model's check allows is_hire with no event; the test needs no event
            order_type=OrderType.HIRED,
            state=OrderState.SIGNED,
            number=f"A{tag}"[:10],
            date=date(2026, 1, 2),
            summary="Матрикс A",
            issued_by="test",
        )
        order_b = HrOrder.objects.create(
            employee=ready.emp_b,
            is_hire=True,
            order_type=OrderType.DEPARTMENT,
            state=OrderState.SIGNED,
            number=f"B{tag}"[:10],
            date=date(2026, 1, 3),
            summary="Матрикс B",
            issued_by="test",
        )
        salary_a = SalaryRecord.objects.create(
            employee=ready.emp_a,
            start_date=date(2026, 1, 1),
            base_salary=Decimal("1111111.11"),
            change_type=ChangeType.HIRE,
            note=PRIVATE_NOTE,
        )
        salary_b = SalaryRecord.objects.create(
            employee=ready.emp_b,
            start_date=date(2026, 1, 1),
            base_salary=Decimal("222222.22"),
            change_type=ChangeType.HIRE,
            note=PRIVATE_NOTE,
        )
        loan_a = LoanRow.objects.create(
            employee=ready.emp_a,
            get_date=date(2026, 2, 1),
            end_date=date(2027, 2, 1),
            amount=Decimal("300000.00"),
            pay_permonth=Decimal("25000.00"),
            loan_ref=reason,
        )
        loan_b = LoanRow.objects.create(
            employee=ready.emp_b,
            get_date=date(2026, 2, 1),
            end_date=date(2027, 2, 1),
            amount=Decimal("400000.00"),
            pay_permonth=Decimal("33333.33"),
            loan_ref=reason,
        )
        child_a = FamilyRow.objects.create(employee=ready.emp_a, relation_id=relation.pk, given_name=f"A{tag}")
        child_b = FamilyRow.objects.create(employee=ready.emp_b, relation_id=relation.pk, given_name=f"B{tag}")
        try:
            yield Data(
                world=ready,
                leave_a=leave_a.pk,
                leave_b=leave_b.pk,
                order_a=order_a.pk,
                order_b=order_b.pk,
                salary_a=salary_a.pk,
                salary_b=salary_b.pk,
                loan_a=loan_a.pk,
                loan_b=loan_b.pk,
                child_a=child_a.pk,
                child_b=child_b.pk,
            )
        finally:
            FamilyRow.objects.filter(pk__in=[child_a.pk, child_b.pk]).delete()
            LoanRow.objects.filter(pk__in=[loan_a.pk, loan_b.pk]).delete()
            SalaryRecord.objects.filter(pk__in=[salary_a.pk, salary_b.pk]).delete()
            HrOrder.objects.filter(pk__in=[order_a.pk, order_b.pk]).delete()
            LeaveAssign.objects.filter(pk__in=[leave_a.pk, leave_b.pk]).delete()
            LoanRefRow.objects.filter(pk=reason.pk).delete()
            LeaveTypeRow.objects.filter(pk=leave_type.pk).delete()
            if made_relation:
                FamilyRelation.objects.filter(pk=relation.pk).delete()


def _users(world: World) -> dict[str, User]:
    return {
        "hr": world.hr,
        "limited": world.limited,
        "own": world.own,
        "nobody": world.nobody,
        "inactive": world.inactive,
        "accountant": world.accountant,
        "admin": world.admin,
        "auditor": world.auditor,
    }


def _int(value: object) -> int:
    return int(str(value))


def _ids(outcome: Answered | Refused) -> set[int]:
    assert isinstance(outcome, Answered), f"should have been answered: {outcome}"
    return {_int(row[0]) for row in outcome.result.rows}


def _orm_count(view: str, user: User) -> int:
    """The row count of a view as the ORM says it must be for this user (visible employees only)."""
    people = visible_employees(user)
    if view == "GOV_EMPLOYEES":
        return people.count()
    if view == "GOV_CHILDREN":
        return FamilyRow.objects.filter(employee__in=people, relation__fm_type__in=("son", "daughter")).count()
    if view == "GOV_LEAVE":
        return LeaveAssign.objects.filter(employee__in=people).count()
    if view == "GOV_ORDERS":
        return HrOrder.objects.filter(employee__in=people).count()
    if view == "GOV_SALARY":
        return SalaryRecord.objects.filter(employee__in=people).count()
    if view == "GOV_LOANS":
        return LoanRow.objects.filter(employee__in=people).count()
    raise AssertionError(f"unknown view {view}")


def _expected_views(user: User) -> set[str]:
    """Which views a user may ask about, by the rule in hr_sql/catalogue.py written out again here: active, and either
    may see employees or has an own record; the salary views in addition only with macs.view_salary."""
    if not user.is_active:
        return set()
    if not (user.has_perm("macs.view_employees") or own_employee(user) is not None):
        return set()
    views = {"GOV_EMPLOYEES", "GOV_LEAVE", "GOV_ORDERS"}
    if _may_see_personal(user):
        views.add("GOV_CHILDREN")
    if user.has_perm("macs.view_salary"):
        views |= set(SALARY_VIEWS)
    return views


def _may_see_personal(user: User) -> bool:
    """The rule of employees/access.py::can_view_personal written out for the people this user may see: someone
    else's record needs macs.view_personal; without the employee right the user sees only the own record, which
    always passes."""
    return user.has_perm("macs.view_personal") or not user.has_perm("macs.view_employees")


def _listing(user: User, view: str) -> Answered | Refused:
    return run_question(HrHost(), user, f"SELECT EMP_ID FROM {view}", LISTING)  # noqa: S608 (fixed names)


@contextmanager
def _branch_accountant(branch: Branch) -> Iterator[User]:
    """An Accountant (salary right) whose data scope is limited to one branch. Removed afterwards."""
    user = User.objects.create_user(f"gov_mx_acc_{uuid.uuid4().hex[:8]}", password=PASSWORD)
    user.groups.add(Group.objects.get(name=roles.ACCOUNTANT))
    AccessScope.objects.create(user=user, limited=True, branch_ids=[branch.pk])
    user = User.objects.get(pk=user.pk)
    try:
        yield user
    finally:
        User.objects.filter(pk=user.pk).delete()


def test_every_role_sees_only_its_own_catalogue_and_rows(data: Data) -> None:
    for name, user in _users(data.world).items():
        expected = _expected_views(user)
        for view in VIEWS:
            outcome = run_question(HrHost(), user, f"SELECT COUNT(*) FROM {view}")  # noqa: S608 (fixed names)
            if view in expected:
                assert isinstance(outcome, Answered), f"{name} should see {view}: {outcome}"
                got = _int(outcome.result.rows[0][0])
                assert got == _orm_count(view, user), f"{name} on {view}: got {got}"
            else:
                assert isinstance(outcome, Refused), f"{name} must not reach {view}, got {outcome}"


def test_salary_and_loan_views_refused_for_every_role_without_the_right(data: Data) -> None:
    users = _users(data.world)
    for name, user in users.items():
        for view in SALARY_VIEWS:
            outcome = run_question(HrHost(), user, f"SELECT COUNT(*) FROM {view}")  # noqa: S608 (fixed names)
            if view in _expected_views(user):
                assert isinstance(outcome, Answered), f"{name} has the salary right but was refused {view}"
            else:
                assert isinstance(outcome, Refused), f"{name} without the salary right reached {view}: {outcome}"
                assert "not a governed view" in outcome.reason, f"{name} on {view}: {outcome.reason}"
    # the two roles that hold macs.view_salary really do see it
    for name in ("admin", "accountant"):
        for view in SALARY_VIEWS:
            assert isinstance(run_question(HrHost(), users[name], f"SELECT COUNT(*) FROM {view}"), Answered)  # noqa: S608


def test_scope_table_unreachable_for_every_role(data: Data) -> None:
    for name, user in _users(data.world).items():
        for sql in ("SELECT EMP_ID FROM GOV_SCOPE", "SELECT COUNT(*) FROM GOV_SCOPE"):
            outcome = run_question(HrHost(), user, sql)
            assert isinstance(outcome, Refused), f"{name} reached GOV_SCOPE with {sql!r}: {outcome}"
            assert "GOV_SCOPE" in outcome.reason, f"{name}: {outcome.reason}"


def test_limited_role_never_sees_outside_its_branch_in_any_view(data: Data) -> None:
    world = data.world
    visible = {int(pk) for pk in visible_employees(world.limited).values_list("pk", flat=True)}
    assert world.emp_a.pk in visible
    assert world.emp_b.pk not in visible

    with _branch_accountant(world.branch_a) as limited_acc:
        visible_acc = {int(pk) for pk in visible_employees(limited_acc).values_list("pk", flat=True)}
        for user, seen in ((world.limited, visible), (limited_acc, visible_acc)):
            for view in VIEWS:
                outcome = _listing(user, view)
                if view not in _expected_views(user):
                    assert isinstance(outcome, Refused), f"{user.username} reached {view}"
                    continue
                ids = _ids(outcome)
                assert ids <= seen, f"{user.username} saw employees outside its branch in {view}: {ids - seen}"
                assert world.emp_b.pk not in ids and world.emp_none.pk not in ids
            # The branch-A employee is reachable through the employee view, the branch-B one is not.
            assert world.emp_a.pk in _ids(_listing(world.limited, "GOV_EMPLOYEES"))
            assert world.emp_b.pk not in _ids(_listing(world.limited, "GOV_EMPLOYEES"))


def test_inactive_user_gets_nothing(data: Data) -> None:
    inactive = data.world.inactive
    assert catalogue_for(inactive).views == ()
    for view in VIEWS:
        outcome = run_question(HrHost(), inactive, f"SELECT COUNT(*) FROM {view}")  # noqa: S608 (fixed names)
        assert isinstance(outcome, Refused), f"inactive user reached {view}: {outcome}"
    assert _orm_count("GOV_EMPLOYEES", inactive) == 0


def _child_ids(user: User) -> set[int]:
    return _ids(run_question(HrHost(), user, "SELECT CHILD_ID FROM GOV_CHILDREN", LISTING))


def test_children_view_follows_employee_scope(data: Data) -> None:
    world = data.world
    hr_children = _child_ids(world.hr)
    limited_children = _child_ids(world.limited)
    own_children = _child_ids(world.own)

    assert data.child_a in hr_children and data.child_b in hr_children  # HR sees both branches
    assert data.child_a in limited_children and data.child_b not in limited_children  # branch A only
    assert data.child_a in own_children and data.child_b not in own_children  # own record only
    assert isinstance(_listing(world.nobody, "GOV_CHILDREN"), Refused)  # no right and no own record: no view
    assert isinstance(_listing(world.accountant, "GOV_CHILDREN"), Refused)  # employee right, no personal right
