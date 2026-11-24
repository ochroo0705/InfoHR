"""The balances page's rules: which people a batch holds, their current period and the waiting date.

The Django view calls `balance_batch`; the API route of Task 5 will call it too, so these tests pin the rules for both.
"""

from datetime import date

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from employees.models import Department, Employee, JobRecord, JobStatus
from employees.services import macs_writes
from macs.models import LeaveTypeRow

from leave.services import ledger, records
from leave.services.balance_page import BalanceLine, balance_batch
from leave.services.records import Draft
from leave.tests.conftest import make_employee

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]

DAY = date(2026, 10, 15)
PASSWORD = "x-long-pass-123"  # noqa: S105


def _named(employee: Employee, family: str, given: str) -> Employee:
    Employee.objects.filter(pk=employee.pk).update(family_name=family, given_name=given)
    employee.refresh_from_db()
    return employee


def test_balance_line_is_a_frozen_value(employee: Employee) -> None:
    line = BalanceLine(employee=employee, period=None, waiting=None)
    assert line.employee is employee
    with pytest.raises(AttributeError):
        line.waiting = DAY  # type: ignore[misc]


def test_only_visible_people_are_listed(actor: User, employee: Employee) -> None:
    dept_a = Department.objects.get(name="Санхүү")
    dept_b = macs_writes.save_department("Бусад")
    outsider = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112299")
    Employee.objects.filter(pk=outsider.pk).update(department=dept_b)  # the scope reads this column

    scoped = User.objects.create_user("scoped_bal_page", password=PASSWORD)
    scoped.groups.add(Group.objects.get(name="HR"))
    AccessScope.objects.create(user=scoped, limited=True, department_ids=[dept_a.pk])

    lines, more = balance_batch(scoped, 0, 60, DAY)
    assert [line.employee.pk for line in lines] == [employee.pk]
    assert more is False


def test_people_who_left_are_absent(actor: User, employee: Employee) -> None:
    leaver = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112300")
    JobRecord.objects.filter(employee=leaver).update(status=JobStatus.LEFT)
    lines, _ = balance_batch(actor, 0, 60, DAY)
    assert [line.employee.pk for line in lines] == [employee.pk]


def test_order_is_family_given_then_pk(actor: User) -> None:
    b = _named(make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112301"), "Бат", "Ариунаа")
    a2 = _named(make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112302"), "Аа", "Зэлээ")
    a1 = _named(make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112303"), "Аа", "Зэлээ")
    lines, _ = balance_batch(actor, 0, 60, DAY)
    assert [line.employee.pk for line in lines] == [a2.pk, a1.pk, b.pk]  # a2 was created first, so its pk is lower


def test_size_and_more_flag(actor: User) -> None:
    people = [
        _named(make_employee(actor, hired=date(2024, 3, 1), register_no=f"УБ991124{n:02d}"), "Батын", f"Нэр{n:02d}")
        for n in range(3)
    ]
    first, more = balance_batch(actor, 0, 2, DAY)
    assert [line.employee.pk for line in first] == [people[0].pk, people[1].pk]
    assert more is True  # one more person follows, and is not returned
    last, more = balance_batch(actor, 2, 2, DAY)
    assert [line.employee.pk for line in last] == [people[2].pk]
    assert more is False


def test_person_with_a_current_grant_has_a_period(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    ledger.manual_grant(employee, date(2026, 3, 1), date(2027, 2, 28), 20, "тест", actor)
    records.record(Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, date(2026, 10, 14))
    (line,), _ = balance_batch(actor, 0, 60, DAY)
    assert line.period is not None
    assert (line.period.granted, line.period.taken, line.period.left) == (20, 3, 17)
    assert line.period.start == date(2026, 3, 1) and line.period.end == date(2027, 2, 28)


def test_person_without_a_current_grant_has_no_period(employee: Employee, actor: User) -> None:
    (line,), _ = balance_batch(actor, 0, 60, DAY)
    assert line.period is None


def test_waiting_is_the_eligibility_date_only_before_it(actor: User) -> None:
    newcomer = make_employee(actor, hired=date(2026, 8, 1), register_no="УБ99112310")
    (before,), _ = balance_batch(actor, 0, 60, DAY)
    assert before.employee.pk == newcomer.pk
    assert before.waiting == date(2027, 2, 1)
    (after,), _ = balance_batch(actor, 0, 60, date(2027, 2, 1))
    assert after.waiting is None


def test_query_count_is_the_same_for_3_and_8_people(actor: User) -> None:
    for n in range(3):
        make_employee(actor, hired=date(2024, 3, 1), register_no=f"УБ99112{320 + n}")
    # Warm-up: the first call fills the user's per-day scope cache; later calls skip that query.
    balance_batch(actor, 0, 60, DAY)
    with CaptureQueriesContext(connection) as small:
        lines, _ = balance_batch(actor, 0, 60, DAY)
    assert len(lines) == 3
    for n in range(5):
        make_employee(actor, hired=date(2024, 3, 1), register_no=f"УБ99112{330 + n}")
    with CaptureQueriesContext(connection) as large:
        lines, _ = balance_batch(actor, 0, 60, DAY)
    assert len(lines) == 8
    assert len(large.captured_queries) == len(small.captured_queries)
