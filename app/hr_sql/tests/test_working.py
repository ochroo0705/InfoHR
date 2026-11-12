"""The WORKING column of GOV_EMPLOYEES, through the governed views: it must equal what the employee list says. Firebird
only.

The expected value is computed with the employee list's own functions (employees/listing.py: row_for and is_working),
never with a copy of the rule. Employees and job records are committed through the ORM (autocommit on `default`),
because the governed connection is another connection and sees only committed rows. Each test removes what it made.
"""

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from accounts.models import User
from django.utils import timezone
from employees import history_range
from employees.access import visible_employees
from employees.listing import employee_rows, is_working
from employees.models import ChangeType, ContractType, EmployeeType, JobRecord, JobStatus
from macs.models import Department, Employee, Position
from pytest_django.plugin import DjangoDbBlocker
from sqlcore.runner import Answered, Refused, run_question

from hr_sql.host import HrHost
from hr_sql.tests.conftest import World


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def extra(django_db_blocker: DjangoDbBlocker, ready: World) -> Iterator[dict[str, Employee]]:
    """Five more committed employees, one for each case the employee list treats differently."""
    tag = uuid.uuid4().hex[:6]
    made: dict[str, Employee] = {}
    with django_db_blocker.unblock():
        position = Position.objects.get_or_create(name="Нягтлан")[0]
        department = Department.objects.get_or_create(name="Санхүү")[0]

        def person(key: str, **fields: object) -> Employee:
            employee = Employee.objects.create(
                given_name=f"Ажил{key}{tag}", family_name="Тест", gender="M", branch=ready.branch_a, **fields
            )
            made[key] = employee
            return employee

        def job(employee: Employee, start: date, end: date | None, status: str) -> None:
            JobRecord.objects.create(
                employee=employee,
                **history_range.span_kwargs(start, end),
                position=position,
                department=department,
                employee_type=EmployeeType.FULL_TIME,
                status=status,
                contract_type=ContractType.OPEN_ENDED,
                change_type=ChangeType.HIRE,
            )

        # HR job history that has ended: the last job is LEFT and its end is in the past.
        job(person("ended_left"), date(2020, 1, 1), date(2025, 6, 30), JobStatus.LEFT)
        # HR job history that has ended, but whose status still says ACTIVE: no job holds today, so the list says left.
        job(person("ended_active"), date(2020, 1, 1), date(2025, 6, 30), JobStatus.ACTIVE)
        # No HR job history, and a MACS emptype that means not working (3 dismissed).
        person("macs_left", emptype=3)
        # No HR job history, and a MACS emptype that means working.
        person("macs_working", emptype=1)
        # A job that holds today with an end date far in the future: working.
        job(person("future_end"), date(2024, 1, 1), date(2099, 12, 31), JobStatus.ACTIVE)
        try:
            yield made
        finally:
            JobRecord.objects.filter(employee__in=made.values()).delete()
            Employee.objects.filter(pk__in=[e.pk for e in made.values()]).delete()


def _int(value: object) -> int:
    return int(str(value))


def _answer(user: User, sql: str) -> Answered:
    outcome = run_question(HrHost(), user, sql)
    if isinstance(outcome, Refused):
        pytest.fail(f"Refused: {outcome.reason}")
    assert isinstance(outcome, Answered)
    return outcome


def _list_rule(user: User) -> dict[int, bool]:
    """Each visible employee's id and whether the employee list counts them as working today."""
    rows = employee_rows(visible_employees(user), timezone.localdate())
    return {row.employee.pk: is_working(row) for row in rows}


def test_working_flag_matches_the_employee_list(ready: World, extra: dict[str, Employee]) -> None:
    expected = {pk: 1 if working else 0 for pk, working in _list_rule(ready.hr).items()}

    answer = _answer(ready.hr, "SELECT EMP_ID, WORKING FROM GOV_EMPLOYEES")
    got = {_int(row[0]): _int(row[1]) for row in answer.result.rows}

    assert got == expected
    assert {extra[key].pk for key in extra} <= set(got)
    assert got[extra["ended_left"].pk] == 0
    assert got[extra["ended_active"].pk] == 0
    assert got[extra["macs_left"].pk] == 0
    assert got[extra["macs_working"].pk] == 1
    assert got[extra["future_end"].pk] == 1


def test_head_count_question_counts_only_working(ready: World, extra: dict[str, Employee]) -> None:
    rule = _list_rule(ready.hr)
    working = sum(1 for flag in rule.values() if flag)

    answer = _answer(ready.hr, "SELECT COUNT(*) FROM GOV_EMPLOYEES WHERE WORKING = 1")

    assert _int(answer.result.rows[0][0]) == working
    assert 0 < working < len(rule)  # leavers exist, so the filter is doing something
