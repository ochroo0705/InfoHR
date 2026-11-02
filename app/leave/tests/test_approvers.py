from datetime import date
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from employees.models import Department, Employee, EmployeeExt, JobRecord
from employees.services import macs_writes
from macs.models import LeaveTypeRow

from leave.models import LeaveRequest, Step
from leave.services.approvers import (
    Approvers,
    Rule,
    approvers,
    can_act,
    manager_user_ids,
    visible_requests,
    waiting_for,
)
from leave.tests.conftest import make_employee

pytestmark = pytest.mark.django_db

DAY = date(2026, 10, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105


def _user(name: str, *, groups: tuple[Group, ...] = (), approve: bool = False) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(*groups)
    if approve:
        user.user_permissions.add(Permission.objects.get(codename="approve_leave", content_type__app_label="accounts"))
    return user


def _group(name: str) -> Group:
    return Group.objects.create(name=name)


def _staff(by: User, n: int) -> Employee:
    return make_employee(by, hired=date(2024, 3, 1), register_no=f"УБ991{n:05d}")


def _link(employee: Employee, user: User) -> None:
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": user})


def _set_manager(employee: Employee, manager: Employee | None) -> None:
    JobRecord.objects.filter(employee=employee).update(manager=manager)


def _request(
    employee: Employee, leave_type: LeaveTypeRow, *steps: Step, created_by: User | None = None
) -> LeaveRequest:
    first = steps[0]
    second = steps[1] if len(steps) > 1 else Step(None, False)
    return LeaveRequest.objects.create(
        employee=employee,
        leave_type=leave_type,
        start_date=DAY,
        end_date=DAY,
        working_days=1,
        step1_group_id=first.group_id,
        step1_manager=first.manager,
        step2_group_id=second.group_id,
        step2_manager=second.manager,
        step_count=len(steps),
        created_by=created_by,
    )


@pytest.fixture
def hr(db: None) -> User:
    """Creates staff records; holds no approval right and is no approver."""
    return _user("hr_creator")


@pytest.fixture
def dept_b(hr: User) -> Department:
    return macs_writes.save_department("Бусад")


def test_role_step_members_are_approvers(hr: User, annual: LeaveTypeRow) -> None:
    group = _group("Нягтлан бодогч")
    m1 = _user("member1", groups=(group,))
    m2 = _user("member2", groups=(group,))
    req = _request(_staff(hr, 1), annual, Step(group.pk, False))
    assert approvers(req, DAY) == Approvers(Rule.ROLE, frozenset({m1.pk, m2.pk}))


def test_role_member_outside_scope_is_not_approver(hr: User, annual: LeaveTypeRow, dept_b: Department) -> None:
    group = _group("Хяналт")
    limited = _user("limited_member", groups=(group,))
    AccessScope.objects.create(user=limited, limited=True, department_ids=[dept_b.pk])
    fallback = _user("fallback_hr", approve=True)
    req = _request(_staff(hr, 1), annual, Step(group.pk, False))  # employee is in "Санхүү", not "Бусад"
    result = approvers(req, DAY)
    assert result.rule == Rule.FALLBACK
    assert limited.pk not in result.user_ids
    assert result.user_ids == {fallback.pk}


def test_manager_step_uses_today_manager(hr: User, annual: LeaveTypeRow) -> None:
    manager_emp = _staff(hr, 2)
    manager = _user("manager")
    _link(manager_emp, manager)
    employee = _staff(hr, 1)
    _set_manager(employee, manager_emp)
    req = _request(employee, annual, Step(None, True))
    assert approvers(req, DAY) == Approvers(Rule.MANAGER, frozenset({manager.pk}))


def test_manager_change_after_submit_moves_request(hr: User, annual: LeaveTypeRow) -> None:
    old_emp = _staff(hr, 2)
    old_manager = _user("old_manager")
    _link(old_emp, old_manager)
    new_emp = _staff(hr, 3)
    new_manager = _user("new_manager")
    _link(new_emp, new_manager)
    employee = _staff(hr, 1)
    _set_manager(employee, old_emp)
    req = _request(employee, annual, Step(None, True))
    assert approvers(req, DAY).user_ids == {old_manager.pk}

    _set_manager(employee, new_emp)
    assert approvers(req, DAY) == Approvers(Rule.MANAGER, frozenset({new_manager.pk}))


def test_manager_without_login_falls_back(hr: User, annual: LeaveTypeRow) -> None:
    manager_emp = _staff(hr, 2)  # no login linked
    employee = _staff(hr, 1)
    _set_manager(employee, manager_emp)
    fallback = _user("fallback_hr", approve=True)
    req = _request(employee, annual, Step(None, True))
    assert approvers(req, DAY) == Approvers(Rule.FALLBACK, frozenset({fallback.pk}))

    inactive = _user("inactive_manager")
    inactive.is_active = False
    inactive.save()
    _link(manager_emp, inactive)
    assert approvers(req, DAY) == Approvers(Rule.FALLBACK, frozenset({fallback.pk}))


def test_requester_never_approves_self(hr: User, annual: LeaveTypeRow) -> None:
    group = _group("Ахлах")
    requester = _user("requester", groups=(group,), approve=True)
    colleague = _user("colleague", groups=(group,))
    employee = _staff(hr, 1)
    _link(employee, requester)
    req = _request(employee, annual, Step(group.pk, False))
    assert approvers(req, DAY) == Approvers(Rule.ROLE, frozenset({colleague.pk}))
    assert can_act(requester, req, DAY) == (False, False)
    assert can_act(colleague, req, DAY) == (True, False)


def test_creator_never_approves_own_request(hr: User, annual: LeaveTypeRow) -> None:
    group = _group("Ахлах 2")
    creator = _user("creator", groups=(group,))
    colleague = _user("colleague2", groups=(group,))
    req = _request(_staff(hr, 1), annual, Step(group.pk, False), created_by=creator)
    assert approvers(req, DAY).user_ids == {colleague.pk}
    assert can_act(creator, req, DAY) == (False, False)


def test_requester_only_member_falls_back(hr: User, annual: LeaveTypeRow) -> None:
    group = _group("Ганц гишүүн")
    requester = _user("only_member", groups=(group,), approve=True)
    employee = _staff(hr, 1)
    _link(employee, requester)
    fallback = _user("fallback_hr2", approve=True)
    req = _request(employee, annual, Step(group.pk, False))
    assert approvers(req, DAY) == Approvers(Rule.FALLBACK, frozenset({fallback.pk}))


def test_deleted_role_goes_to_fallback(hr: User, annual: LeaveTypeRow) -> None:
    fallback = _user("fallback_hr3", approve=True)
    req = _request(_staff(hr, 1), annual, Step(None, False))
    assert approvers(req, DAY) == Approvers(Rule.FALLBACK, frozenset({fallback.pk}))


def test_no_one_left_goes_to_admin(hr: User, annual: LeaveTypeRow) -> None:
    empty_group = _group("Хоосон бүлэг")
    admin_group, _ = Group.objects.get_or_create(name=roles.ADMIN)
    # The Admin role holds approve_leave by default, which would make its members fallback approvers.
    # Remove it here so the ADMIN rule is what is tested.
    admin_group.permissions.remove(Permission.objects.get(codename="approve_leave", content_type__app_label="accounts"))
    admin = _user("admin_user", groups=(admin_group,))
    req = _request(_staff(hr, 1), annual, Step(empty_group.pk, False))
    assert approvers(req, DAY) == Approvers(Rule.ADMIN, frozenset({admin.pk}))


def test_override_by_approve_leave_right(hr: User, annual: LeaveTypeRow) -> None:
    group = _group("Хяналт 2")
    member = _user("member_only", groups=(group,))
    override = _user("hr_override", approve=True)
    req = _request(_staff(hr, 1), annual, Step(group.pk, False))
    assert approvers(req, DAY).user_ids == {member.pk}
    assert can_act(override, req, DAY) == (True, True)
    assert can_act(member, req, DAY) == (True, False)


def test_override_respects_data_scope(hr: User, annual: LeaveTypeRow, dept_b: Department) -> None:
    group = _group("Хяналт 3")
    _user("member_scope", groups=(group,))
    limited_hr = _user("limited_hr", approve=True)
    AccessScope.objects.create(user=limited_hr, limited=True, department_ids=[dept_b.pk])
    req = _request(_staff(hr, 1), annual, Step(group.pk, False))  # employee in "Санхүү"
    assert can_act(limited_hr, req, DAY) == (False, False)


LIMITED_COST = 4  # queries per limited candidate: see the test below
WAITING_FOR_QUERIES = 11  # measured with 3 and with 30 waiting requests: the same count both times


def test_waiting_for_fixed_queries(
    hr: User, annual: LeaveTypeRow, dept_b: Department, django_assert_max_num_queries: Any
) -> None:
    group = _group("Нягтлан бодогч 2")
    approver = _user("approver", groups=(group,))
    limited = _user("limited_approver", groups=(group,))
    AccessScope.objects.create(user=limited, limited=True, department_ids=[dept_b.pk])
    manager_emp = _staff(hr, 2)
    _link(manager_emp, _user("staff_manager"))
    staff = [_staff(hr, n) for n in range(10, 13)]
    for member in staff:
        _set_manager(member, manager_emp)
    for member in staff:
        _request(member, annual, Step(group.pk, False))

    with django_assert_max_num_queries(WAITING_FOR_QUERIES):
        assert len(waiting_for(approver, DAY)) == 3

    for n in range(27):
        _request(staff[n % 3], annual, Step(group.pk, False))

    with django_assert_max_num_queries(WAITING_FOR_QUERIES):
        assert len(waiting_for(approver, DAY)) == 30


def test_waiting_for_query_count_does_not_grow(hr: User, annual: LeaveTypeRow) -> None:
    """Half the requests are manager steps and half group steps. Each request has its own employee and its own
    manager login. The query count must not grow with the number of requests, for the group approver and for a
    manager user alike."""
    group = _group("Нягтлан бодогч 5")
    approver = _user("approver5", groups=(group,))
    manager_users: dict[int, User] = {}

    def add_waiting(first: int, last: int) -> None:
        for n in range(first, last):
            staff = _staff(hr, n)
            manager_emp = _staff(hr, n + 500)
            manager_users[n] = _user(f"own_manager_{n}")
            _link(manager_emp, manager_users[n])
            _set_manager(staff, manager_emp)
            if n % 2 == 0:
                _request(staff, annual, Step(None, True))  # manager step
            else:
                _request(staff, annual, Step(group.pk, False))  # group step

    add_waiting(10, 13)  # 3 waiting requests: 10 and 12 are manager steps, 11 is a group step
    manager_one = manager_users[10]
    with CaptureQueriesContext(connection) as group_few:
        assert len(waiting_for(approver, DAY)) == 1
    with CaptureQueriesContext(connection) as manager_few:
        assert len(waiting_for(manager_one, DAY)) == 1

    add_waiting(13, 25)  # 15 waiting requests in all: 7 group steps (odd), 8 manager steps (even)
    with CaptureQueriesContext(connection) as group_many:
        assert len(waiting_for(approver, DAY)) == 7
    with CaptureQueriesContext(connection) as manager_many:
        assert len(waiting_for(manager_one, DAY)) == 1

    assert len(group_many) == len(group_few)
    assert len(manager_many) == len(manager_few)


def test_waiting_for_excludes_others_and_done_requests(hr: User, annual: LeaveTypeRow) -> None:
    group = _group("Нягтлан бодогч 3")
    approver = _user("approver3", groups=(group,))
    other = _user("other_member", groups=(group,))
    req = _request(_staff(hr, 1), annual, Step(group.pk, False))
    done = _request(_staff(hr, 2), annual, Step(group.pk, False))
    done.status = "approved"
    done.save()
    assert [r.pk for r in waiting_for(approver, DAY)] == [req.pk]
    assert [r.pk for r in waiting_for(other, DAY)] == [req.pk]
    assert waiting_for(_user("stranger"), DAY) == []


def test_manager_user_ids_maps_each_employee(hr: User) -> None:
    manager_emp = _staff(hr, 2)
    manager = _user("mapped_manager")
    _link(manager_emp, manager)
    with_manager = _staff(hr, 1)
    _set_manager(with_manager, manager_emp)
    no_job_manager = _staff(hr, 3)
    _set_manager(no_job_manager, None)
    result = manager_user_ids([with_manager.pk, no_job_manager.pk], DAY)
    assert result == {with_manager.pk: manager.pk, no_job_manager.pk: None}


def test_visible_requests_follow_leave_and_employee_rights(hr: User, annual: LeaveTypeRow) -> None:
    own_emp = _staff(hr, 1)
    other_emp = _staff(hr, 2)
    viewer = _user("viewer")
    _link(own_emp, viewer)
    own_req = _request(own_emp, annual, Step(None, False))
    other_req = _request(other_emp, annual, Step(None, False))

    assert visible_requests(viewer).count() == 0  # no leave.view_leave

    viewer.user_permissions.add(Permission.objects.get(codename="view_leave", content_type__app_label="leave"))
    viewer = User.objects.get(pk=viewer.pk)
    assert list(visible_requests(viewer).values_list("pk", flat=True)) == [own_req.pk]  # own record only

    viewer.user_permissions.add(Permission.objects.get(codename="view_employees", content_type__app_label="macs"))
    viewer = User.objects.get(pk=viewer.pk)
    assert set(visible_requests(viewer).values_list("pk", flat=True)) == {own_req.pk, other_req.pk}


def test_waiting_for_query_count_with_many_limited_role_members(
    hr: User, annual: LeaveTypeRow, dept_b: Department
) -> None:
    """A role of 30 members, each limited by AccessScope to a department, one waiting request.

    Candidates without a limited scope cost no per-user query. A LIMITED member still goes through `restriction`
    (its own scope row, the Admin-group check, the department tree and the employee filter), a small constant per
    limited member that cannot be dropped without rewriting `restriction`. So the count may grow by at most
    LIMITED_COST queries per added limited member, and the cost must not be worse than that.
    """
    group = _group("Нягтлан бодогч 6")
    members: list[User] = []

    def add_members(first: int, last: int) -> None:
        for n in range(first, last):
            member = _user(f"limited_member_{n}", groups=(group,))
            AccessScope.objects.create(user=member, limited=True, department_ids=[dept_b.pk])
            members.append(member)

    _request(_staff(hr, 1), annual, Step(group.pk, False))
    add_members(0, 5)
    with CaptureQueriesContext(connection) as few:
        waiting_for(members[0], DAY)
    add_members(5, 30)
    with CaptureQueriesContext(connection) as many:
        waiting_for(members[0], DAY)
    assert len(many) - len(few) <= LIMITED_COST * 25, (len(few), len(many))


def test_waiting_for_unlimited_members_cost_no_per_user_queries(hr: User, annual: LeaveTypeRow) -> None:
    group = _group("Нягтлан бодогч 7")
    members = [_user(f"free_member_{n}", groups=(group,)) for n in range(5)]
    _request(_staff(hr, 1), annual, Step(group.pk, False))
    with CaptureQueriesContext(connection) as few:
        assert len(waiting_for(members[0], DAY)) == 1
    members += [_user(f"free_member_{n}", groups=(group,)) for n in range(5, 30)]
    with CaptureQueriesContext(connection) as many:
        assert len(waiting_for(members[0], DAY)) == 1
    assert len(many) == len(few)
