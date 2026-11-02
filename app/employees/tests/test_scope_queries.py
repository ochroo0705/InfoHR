"""Query counts with the data scope (spec §8, Task 7). Scope must add a fixed number of queries, never one per person.

People are hired through history.hire, as in test_scope.py. Each measurement of the visible set uses a fresh
User object, so the per-user scope cache (employees.scope.restriction) is cold, as it is at the start of a request.
"""

from datetime import date
from typing import Any, NamedTuple

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from macs.models import Branch

from employees import access
from employees.models import Department, Employee
from employees.services import history, macs_writes

from .conftest import hire_values, link_login
from .helpers import make_branch

pytestmark = pytest.mark.django_db

START = date(2026, 1, 5)
PASSWORD = "x-long-pass-123"  # noqa: S105
SMALL = 5  # the first measurement: the five people of the org below
LARGE = 40  # the second measurement: 35 more people
# Queries for visible_employees() of an unlimited HR user (measured once, 2026-10-29): has_perm loads the user and
# group permissions (2), the AccessScope lookup finds no limit (1, the one extra query scope adds), and the employee
# query itself (1). Without the AccessScope lookup it would be 3.
UNLIMITED_VISIBLE_QUERIES = 4
LIST_GROWTH_ALLOWANCE = 3


class Org(NamedTuple):
    north: Branch
    south: Branch
    root: Department
    child: Department  # below root: in scope through include_sub_departments
    other: Department  # not in scope
    lead: Employee
    mid: Employee  # manager chain: lead > mid > low > deep (three levels under the lead)
    low: Employee
    deep: Employee
    outsider: Employee  # branch south, department other: outside every rule of the limited user


def _hire(
    actor: User, job_values: dict[str, Any], n: int, branch: Branch, department: Department, manager: Employee | None
) -> Employee:
    register_no = f"УБ{n:08d}"
    values = {**hire_values(register_no), "family_name": "Батын", "given_name": f"Ажилтан{n}"}
    job = {**job_values, "department": department, "manager": manager}
    employee = history.hire(values, {}, start=START, job=job, salary=None, by=actor)
    Employee.objects.filter(pk=employee.pk).update(branch_id=branch.pk, department_id=department.pk)
    return employee


def _org(actor: User, job_values: dict[str, Any]) -> Org:
    north = make_branch("Хойд")
    south = make_branch("Өмнөд")
    root = macs_writes.save_department("Удирдлага")
    child = macs_writes.save_department("Хэлтэс А")
    other = macs_writes.save_department("Бусад")
    Department.objects.filter(pk=child.pk).update(parent_id_value=root.pk)
    lead = _hire(actor, job_values, 1, north, root, None)
    mid = _hire(actor, job_values, 2, north, child, lead)
    low = _hire(actor, job_values, 3, north, child, mid)
    deep = _hire(actor, job_values, 4, north, root, low)
    outsider = _hire(actor, job_values, 5, south, other, None)
    return Org(north, south, root, child, other, lead, mid, low, deep, outsider)


def _grow(actor: User, job_values: dict[str, Any], org: Org, first: int, last: int) -> None:
    """Hire people numbered first..last (inclusive). They alternate branches and cycle departments; every fourth
    one reports to `mid`, so some of them are in the lead's team."""
    for n in range(first, last + 1):
        branch = org.north if n % 2 else org.south
        department = (org.root, org.child, org.other)[n % 3]
        manager = org.mid if n % 4 == 0 else None
        _hire(actor, job_values, n, branch, department, manager)


def _user(name: str, role: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # a fresh object: no permission cache from creation


def _limited_user(org: Org) -> User:
    """An HR user with every scope mode on: branch north, department root with its subs, and the lead's team."""
    user = _user("hr_scope_limited", roles.HR)
    link_login(org.lead, user)
    AccessScope.objects.create(
        user=user,
        limited=True,
        branch_ids=[org.north.pk],
        department_ids=[org.root.pk],
        include_sub_departments=True,
        own_team=True,
    )
    return User.objects.get(pk=user.pk)


def _visible_queries(pk: int) -> int:
    fresh = User.objects.get(pk=pk)  # fetched before counting, so the lookup itself is not measured
    with CaptureQueriesContext(connection) as ctx:
        list(access.visible_employees(fresh))
    return len(ctx.captured_queries)


def _list_page_queries(pk: int) -> int:
    client = Client()
    client.force_login(User.objects.get(pk=pk))
    client.get(reverse("employees:list"))  # warm-up: the first request of the day can run the daily sync
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(reverse("employees:list"))
    assert response.status_code == 200
    return len(ctx.captured_queries)


def test_scope_query_count_does_not_grow_with_people(actor: User, job_values: dict[str, Any]) -> None:
    org = _org(actor, job_values)
    pk = _limited_user(org).pk
    small = _visible_queries(pk)
    _grow(actor, job_values, org, SMALL + 1, LARGE)
    large = _visible_queries(pk)

    seen = set(access.visible_employees(User.objects.get(pk=pk)).values_list("pk", flat=True))
    assert {org.lead.pk, org.mid.pk, org.low.pk, org.deep.pk} <= seen
    assert org.outsider.pk not in seen
    assert len(seen) > SMALL  # the grown org really has people in scope, so the count covers a real filter
    assert small == large, f"visible_employees queries: {small} with {SMALL} people, {large} with {LARGE}"


def test_employee_list_page_query_count_does_not_grow_with_people(actor: User, job_values: dict[str, Any]) -> None:
    org = _org(actor, job_values)
    limited_pk = _limited_user(org).pk
    unlimited_pk = _user("hr_scope_open", roles.HR).pk
    limited_small, unlimited_small = _list_page_queries(limited_pk), _list_page_queries(unlimited_pk)
    _grow(actor, job_values, org, SMALL + 1, LARGE)
    limited_large, unlimited_large = _list_page_queries(limited_pk), _list_page_queries(unlimited_pk)

    limited_growth = limited_large - limited_small
    unlimited_growth = unlimited_large - unlimited_small
    numbers = (
        f"limited {limited_small} -> {limited_large} (growth {limited_growth}), "
        f"unlimited {unlimited_small} -> {unlimited_large} (growth {unlimited_growth}); "
        f"{SMALL} vs {LARGE} people"
    )
    assert limited_growth <= unlimited_growth, f"scope adds per-person queries: {numbers}"
    assert limited_growth <= LIST_GROWTH_ALLOWANCE, f"list page grows with headcount: {numbers}"


def test_unlimited_user_pays_one_extra_query(actor: User, job_values: dict[str, Any]) -> None:
    _org(actor, job_values)
    pk = _user("hr_scope_open_count", roles.HR).pk
    assert _visible_queries(pk) == UNLIMITED_VISIBLE_QUERIES
