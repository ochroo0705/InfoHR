"""The governed job history view (Task 7): GOV_JOB_HISTORY, on Firebird, through run_question.

Firebird only. Job period rows are committed (autocommit on `default`), because the governed connection is another
connection and sees only committed rows. The rows are removed again after each test. Job periods are written through the
ORM, as employees/tests and hr_sql/tests/test_working.py do: the history service's guard is a docstring, not code.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from employees import history_range
from employees.models import ChangeType, ContractType, EmployeeType, JobRecord, JobStatus
from macs.models import Department, Position
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import OPEN_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

JOB_COLUMNS = [
    "JOB_ID",
    "EMP_ID",
    "START_DATE",
    "END_DATE",
    "DEPARTMENT_NAME",
    "POSITION_NAME",
    "MANAGER_NAME",
    "STATUS",
    "EMPLOYEE_TYPE",
    "CONTRACT_TYPE",
    "CONTRACT_NUMBER",
    "CONTRACT_START",
    "CONTRACT_END",
    "CHANGE_TYPE",
]
PRIVATE_NOTE = "private job note"


@dataclass(frozen=True)
class Made:
    world: World
    emp_a_ids: list[int]  # job rows of emp_a (branch A); two periods, so one person has two
    emp_b_ids: list[int]  # job row of emp_b (branch B); its manager is emp_b itself
    manager_row_id: int  # the emp_a row whose manager is emp_b (branch B, outside the limited scope)
    manager_name: str  # emp_b's given name and family name, as the view shows it to HR


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed job periods for emp_a (branch A, manager emp_b) and emp_b (branch B). Removed after the test."""
    row_ids: list[int] = []
    with django_db_blocker.unblock():
        position = Position.objects.get_or_create(name="Нягтлан")[0]
        department = Department.objects.get_or_create(name="Санхүү")[0]
        try:
            first_a = JobRecord.objects.create(
                employee=ready.emp_a,
                **history_range.span_kwargs(date(2015, 3, 1), date(2019, 12, 31)),
                position=position,
                department=department,
                manager=ready.emp_b,
                employee_type=EmployeeType.FULL_TIME,
                status=JobStatus.LEFT,
                contract_type=ContractType.OPEN_ENDED,
                change_type=ChangeType.HIRE,
                note=PRIVATE_NOTE,
            )
            second_a = JobRecord.objects.create(
                employee=ready.emp_a,
                **history_range.span_kwargs(date(2020, 1, 1), None),
                position=position,
                department=department,
                manager=ready.emp_b,
                employee_type=EmployeeType.CONTRACT,
                status=JobStatus.ACTIVE,
                contract_type=ContractType.FIXED_TERM,
                contract_no="ГЭР-1",
                contract_start=date(2020, 1, 1),
                contract_end=date(2024, 12, 31),
                change_type=ChangeType.PROMOTION,
                note=PRIVATE_NOTE,
            )
            row_b = JobRecord.objects.create(
                employee=ready.emp_b,
                **history_range.span_kwargs(date(2018, 6, 1), None),
                position=position,
                department=department,
                manager=None,
                employee_type=EmployeeType.PART_TIME,
                status=JobStatus.ACTIVE,
                contract_type=ContractType.OPEN_ENDED,
                change_type=ChangeType.TRANSFER,
                note="",
            )
            row_ids = [first_a.pk, second_a.pk, row_b.pk]
            yield Made(
                world=ready,
                emp_a_ids=[first_a.pk, second_a.pk],
                emp_b_ids=[row_b.pk],
                manager_row_id=second_a.pk,
                manager_name=f"{ready.emp_b.given_name} {ready.emp_b.family_name}",
            )
        finally:
            JobRecord.objects.filter(pk__in=row_ids).delete()


def test_job_history_scope(made: Made) -> None:
    world = made.world
    ids = [*made.emp_a_ids, *made.emp_b_ids]
    sql = f"SELECT JOB_ID FROM GOV_JOB_HISTORY WHERE JOB_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in rows(world.own, sql)}

    assert hr_ids == set(ids)  # HR sees both branches
    assert limited_ids == set(made.emp_a_ids)  # the branch limit keeps branch B out
    assert own_ids == set(made.emp_a_ids)  # own record only

    # many rows per person: two periods for emp_a and one for emp_b, so two people
    people = rows(
        world.hr,
        f"SELECT COUNT(DISTINCT EMP_ID) FROM GOV_JOB_HISTORY WHERE JOB_ID IN ({id_list(ids)})",  # noqa: S608
    )
    assert int(str(people[0][0])) == 2


def test_job_history_columns(ready: World) -> None:
    assert columns("GOV_JOB_HISTORY") == JOB_COLUMNS


def test_job_history_hides_note(made: Made) -> None:
    ids = [*made.emp_a_ids, *made.emp_b_ids]
    every_column = ", ".join(JOB_COLUMNS)  # the governed checker refuses SELECT *, so name all fourteen
    listing = rows(made.world.hr, f"SELECT {every_column} FROM GOV_JOB_HISTORY WHERE JOB_ID IN ({id_list(ids)})")  # noqa: S608
    assert len(listing) == len(ids)
    for row in listing:
        for cell in row:
            assert PRIVATE_NOTE not in str(cell)


def test_job_history_manager_name_only_in_scope(made: Made) -> None:
    sql = f"SELECT JOB_ID, MANAGER_NAME FROM GOV_JOB_HISTORY WHERE JOB_ID = {made.manager_row_id}"  # noqa: S608

    # emp_b is in branch B: the limited user may see emp_a's period, but not emp_b's name
    limited = rows(made.world.limited, sql)
    assert len(limited) == 1
    assert limited[0][1] in (None, "")

    # HR may see every employee, so the manager's name is shown
    hr = [(int(str(job_id)), name) for job_id, name in rows(made.world.hr, sql)]
    assert hr == [(made.manager_row_id, made.manager_name)]


def test_job_history_masks_salary_change(ready: World, django_db_blocker: DjangoDbBlocker) -> None:
    """A period that began with a pay change is still listed, with an empty CHANGE_TYPE; other periods keep it."""
    every_column = ", ".join(JOB_COLUMNS)  # the governed checker refuses SELECT *, so name all fourteen
    row_ids: list[int] = []
    with django_db_blocker.unblock():
        position = Position.objects.get_or_create(name="Нягтлан")[0]
        department = Department.objects.get_or_create(name="Санхүү")[0]
        try:
            hire_row = JobRecord.objects.create(
                employee=ready.emp_a,
                **history_range.span_kwargs(date(2021, 1, 1), date(2021, 12, 31)),
                position=position,
                department=department,
                manager=None,
                employee_type=EmployeeType.FULL_TIME,
                status=JobStatus.ACTIVE,
                contract_type=ContractType.OPEN_ENDED,
                change_type=ChangeType.HIRE,
                note="",
            )
            row_ids.append(hire_row.pk)
            pay_row = JobRecord.objects.create(
                employee=ready.emp_a,
                **history_range.span_kwargs(date(2022, 1, 1), None),
                position=position,
                department=department,
                manager=None,
                employee_type=EmployeeType.FULL_TIME,
                status=JobStatus.ACTIVE,
                contract_type=ContractType.OPEN_ENDED,
                change_type=ChangeType.SALARY_CHANGE,
                note=PRIVATE_NOTE,
            )
            row_ids.append(pay_row.pk)
            listing = rows(
                ready.hr,
                f"SELECT {every_column} FROM GOV_JOB_HISTORY WHERE JOB_ID IN ({id_list(row_ids)})",  # noqa: S608
            )
            change = {int(str(row[0])): row[13] for row in listing}  # row[13] is CHANGE_TYPE
            assert set(change) == {hire_row.pk, pay_row.pk}  # the pay period is still listed
            assert change[pay_row.pk] in (None, "")
            assert str(change[hire_row.pk]) == ChangeType.HIRE.value
        finally:
            JobRecord.objects.filter(pk__in=row_ids).delete()


def test_job_history_gate(made: Made) -> None:
    assert "GOV_JOB_HISTORY" in OPEN_VIEWS
    sql = "SELECT JOB_ID FROM GOV_JOB_HISTORY"
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    assert rows(made.world.accountant, sql)
    # a user with no record and no right, and an inactive user, are outside the catalogue
    assert "not a governed view" in refusal(made.world.nobody, sql)
    assert "not a governed view" in refusal(made.world.inactive, sql)
