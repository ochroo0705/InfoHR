"""The scope fill (GOV_SCOPE from visible_employees) and the role catalogue. Firebird only.

GOV_SCOPE is a global temporary table: each test fills and reads it on the governed connection inside one atomic
block, the same way the host does.
"""

from collections.abc import Iterator

import pytest
from accounts.models import User
from django.contrib.auth.models import AnonymousUser, Permission
from django.db import transaction
from django.utils import timezone
from employees.access import can_view_personal, own_employee, visible_employees
from employees.listing import employee_rows, is_working
from employees.models import Employee
from sqlcore.runner import Answered, Refused, run_question

from hr_sql import scope as scope_module
from hr_sql.catalogue import catalogue_for
from hr_sql.connection import GOVERNED_ALIAS, governed_connection
from hr_sql.host import HrHost
from hr_sql.scope import fill_scope, working_flags
from hr_sql.tests.conftest import World

COLUMNS = {
    "GOV_EMPLOYEES": [
        "EMP_ID",
        "FIRST_NAME",
        "LAST_NAME",
        "DEPARTMENT_NAME",
        "BRANCH_NAME",
        "POSITION_NAME",
        "HIRE_DATE",
        "BIRTH_DATE",
        "GENDER",
        "WORKING",
    ],
    "GOV_CHILDREN": ["CHILD_ID", "EMP_ID", "BIRTH_DATE", "GENDER"],
    "GOV_LEAVE": ["LEAVE_ID", "EMP_ID", "LEAVE_TYPE_NAME", "START_DATE", "END_DATE", "DAYS", "STATUS_NAME"],
    "GOV_ORDERS": ["ORDER_ID", "EMP_ID", "ORDER_TYPE_NAME", "STATE_NAME", "ORDER_NUMBER", "ORDER_DATE", "SUMMARY"],
}


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    """The governed objects and the world, both in place."""
    yield world


def _scope_ids() -> set[int]:
    with governed_connection().cursor() as cursor:
        cursor.execute("SELECT EMP_ID FROM GOV_SCOPE")
        return {int(row[0]) for row in cursor.fetchall()}


def _filled_scope(user: User) -> tuple[int, set[int]]:
    """Fill the scope for `user` and read it back, inside one transaction (the rows vanish at its end)."""
    connection = governed_connection()
    with transaction.atomic(using=GOVERNED_ALIAS):
        count = fill_scope(connection, user)
        return count, _scope_ids()


def _visible_ids(user: User) -> set[int]:
    return {int(pk) for pk in visible_employees(user).values_list("pk", flat=True)}


def test_hr_user_scope_is_every_visible_employee(ready: World) -> None:
    count, ids = _filled_scope(ready.hr)

    assert ids == _visible_ids(ready.hr)
    assert count == len(ids)
    assert {ready.emp_a.pk, ready.emp_b.pk, ready.emp_none.pk} <= ids


def test_limited_user_scope_is_only_the_listed_branch(ready: World) -> None:
    _, ids = _filled_scope(ready.limited)

    assert ids == _visible_ids(ready.limited)
    assert ready.emp_a.pk in ids
    assert ready.emp_b.pk not in ids and ready.emp_none.pk not in ids


def test_own_record_user_gets_exactly_the_own_record(ready: World) -> None:
    count, ids = _filled_scope(ready.own)

    assert ids == {ready.emp_a.pk}
    assert count == 1


def test_user_with_no_right_and_no_record_gets_zero_ids(ready: World) -> None:
    count, ids = _filled_scope(ready.nobody)

    assert ids == set()
    assert count == 0


def test_working_flags_match_the_employee_list(ready: World) -> None:
    """The lean working_flags must give the employee list's answer (listing.row_for + is_working) for everyone."""
    today = timezone.localdate()
    people = Employee.objects.all()
    expected = {row.employee.pk: 1 if is_working(row) else 0 for row in employee_rows(people, today)}

    assert expected  # the world has people
    assert working_flags(people, today) == expected


@pytest.mark.parametrize("block_rows", [1, 2, 100])
def test_scope_fill_is_the_same_whatever_the_block_size(
    ready: World, monkeypatch: pytest.MonkeyPatch, block_rows: int
) -> None:
    """Blocks of 1, 2 (uneven last block) and the real size all write every visible id with its flag."""
    monkeypatch.setattr(scope_module, "_BLOCK_ROWS", block_rows)
    connection = governed_connection()
    with transaction.atomic(using=GOVERNED_ALIAS):
        count = fill_scope(connection, ready.hr)
        with connection.cursor() as cursor:
            cursor.execute("SELECT EMP_ID, WORKING FROM GOV_SCOPE")
            written = {int(pk): int(flag) for pk, flag in cursor.fetchall()}

    assert count == len(written) >= 3
    assert written == working_flags(visible_employees(ready.hr), timezone.localdate())


def test_insert_blocks_split_rows_and_hold_only_integers() -> None:
    blocks = list(scope_module._insert_blocks([(i, i % 2) for i in range(250)]))

    assert [block.count("INSERT") for block in blocks] == [100, 100, 50]
    assert list(scope_module._insert_blocks([])) == []


def test_inactive_user_gets_zero_ids(ready: World) -> None:
    _, ids = _filled_scope(ready.inactive)

    assert ids == set()


def test_scope_refill_replaces_the_previous_user(ready: World) -> None:
    connection = governed_connection()
    with transaction.atomic(using=GOVERNED_ALIAS):
        fill_scope(connection, ready.hr)
        fill_scope(connection, ready.nobody)
        assert _scope_ids() == set()


def test_inactive_user_gets_empty_catalogue(ready: World) -> None:
    assert catalogue_for(ready.inactive).views == ()


def test_anonymous_user_gets_empty_catalogue(ready: World) -> None:
    assert catalogue_for(AnonymousUser()).views == ()  # type: ignore[arg-type]


def test_user_with_no_right_and_no_record_gets_empty_catalogue(ready: World) -> None:
    assert catalogue_for(ready.nobody).views == ()


@pytest.mark.parametrize("who", ["hr", "limited", "own"])
def test_user_who_sees_employees_gets_both_views(ready: World, who: str) -> None:
    user = getattr(ready, who)

    names = [view.name for view in catalogue_for(user).views]

    assert names == ["GOV_EMPLOYEES", "GOV_CHILDREN", "GOV_LEAVE", "GOV_ORDERS"]


def test_catalogue_columns_match_the_firebird_views(ready: World) -> None:
    with transaction.atomic(using=GOVERNED_ALIAS), governed_connection().cursor() as cursor:
        for view in catalogue_for(ready.hr).views:
            cursor.execute(f"SELECT * FROM {view.name} WHERE 1 = 0")  # noqa: S608 (fixed view names)
            names = [str(column[0]).strip() for column in cursor.description or ()]
            assert names == COLUMNS[view.name]
            assert [column.name for column in view.columns] == COLUMNS[view.name]


def _names(user: User, view: str) -> list[str]:
    found = catalogue_for(user).get(view)
    assert found is not None, view
    return [column.name for column in found.columns]


def test_accountant_catalogue_has_no_children_view(ready: World) -> None:
    names = [view.name for view in catalogue_for(ready.accountant).views]

    assert "GOV_CHILDREN" not in names
    assert names == ["GOV_EMPLOYEES", "GOV_LEAVE", "GOV_ORDERS", "GOV_SALARY", "GOV_LOANS"]


def test_accountant_employees_view_has_no_birth_date_or_gender(ready: World) -> None:
    assert "BIRTH_DATE" not in _names(ready.accountant, "GOV_EMPLOYEES")
    assert "GENDER" not in _names(ready.accountant, "GOV_EMPLOYEES")
    assert _names(ready.hr, "GOV_EMPLOYEES") == COLUMNS["GOV_EMPLOYEES"]

    refused = run_question(HrHost(), ready.accountant, "SELECT BIRTH_DATE FROM GOV_EMPLOYEES")  # noqa: S608 (fixed names)
    assert isinstance(refused, Refused), refused
    answered = run_question(HrHost(), ready.hr, "SELECT BIRTH_DATE FROM GOV_EMPLOYEES")  # noqa: S608 (fixed names)
    assert isinstance(answered, Answered), answered


def test_personal_rule_is_can_view_personal(ready: World) -> None:
    """The personal columns and the children view follow employees/access.py::can_view_personal: for someone else's
    record it is the view_personal right; a user without the employee right sees only the own record, which passes."""
    for user in (ready.hr, ready.limited, ready.own, ready.accountant, ready.admin):
        if user.has_perm("macs.view_employees"):
            expected = can_view_personal(user, ready.emp_b)  # a record that is nobody's own
        else:
            own = own_employee(user)
            expected = own is not None and can_view_personal(user, own)
        personal = "BIRTH_DATE" in _names(user, "GOV_EMPLOYEES")
        assert personal is expected, user.username
        assert ("GOV_CHILDREN" in [view.name for view in catalogue_for(user).views]) is expected, user.username

    # The right itself, granted to the accountant directly: the same catalogue as HR.
    perm = Permission.objects.get(codename="view_personal", content_type__app_label="macs")
    ready.accountant.user_permissions.add(perm)
    try:
        granted = User.objects.get(pk=ready.accountant.pk)
        assert "BIRTH_DATE" in _names(granted, "GOV_EMPLOYEES")
        assert "GOV_CHILDREN" in [view.name for view in catalogue_for(granted).views]
    finally:
        ready.accountant.user_permissions.remove(perm)
