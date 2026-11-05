from collections.abc import Callable
from datetime import date

import pytest
from accounts.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from employees.models import Employee, EmployeeExt, JobRecord
from macs.models import Department, Position
from reports.filters import Filters
from reports.staff_list import REPORT
from reports.table import build_table

from assistant.demo_data import assistant_data_allowed, build, demo_people
from assistant.resolver import resolve
from assistant.tests.helpers import hire_one

DAY = date(2026, 11, 5)


@pytest.mark.parametrize(
    ("db_name", "debug", "engine", "allowed"),
    [
        ("info_hr_demo", True, "postgresql", True),
        ("info_hr_demo_orders", True, "postgresql", True),
        ("info_hr", True, "postgresql", False),
        ("info_hr_demo", True, "firebird", False),
        ("info_hr_demo", False, "postgresql", False),
        ("test_info_hr_demo", True, "postgresql", False),
        ("", True, "postgresql", False),
    ],
)
def test_guard_allows_only_demo_postgres_debug(db_name: str, debug: bool, engine: str, allowed: bool) -> None:
    assert assistant_data_allowed(db_name, debug, engine) is allowed


@pytest.mark.django_db
def test_build_creates_the_required_rows() -> None:
    counts = build(DAY)

    departments = set(Department.objects.values_list("name", flat=True))
    assert {"Санхүү", "IT", "Худалдан авалт (Төв)", "Худалдан авалт (Баруун)"} <= departments
    assert len(departments) >= 6
    assert "Борлуулалт" not in departments
    positions = set(Position.objects.values_list("name", flat=True))
    assert {"Програмист", "Борлуулалтын менежер", "Төслийн менежер"} <= positions

    people = list(demo_people())
    assert 40 <= len(people) <= 80
    assert counts["people"] == len(people)
    job_types = set(JobRecord.objects.filter(employee__in=people).values_list("emptype", flat=True))
    assert {1, 2, 3, 4, 5, 6} <= job_types
    assert {e.gender for e in people} == {"M", "F"}
    assert {e.first_hire_date.year for e in people} == set(range(2015, 2027))
    contract_ends = [j.contract_end for j in JobRecord.objects.filter(employee__in=people, emptype=5)]
    assert all(end is not None for end in contract_ends)
    ends = [end for end in contract_ends if end is not None]
    assert any(end.year == 2026 and end.month == 11 for end in ends)
    assert any(end.year == 2026 and end.month == 12 for end in ends)
    assert EmployeeExt.objects.filter(employee__in=people, probation_end__isnull=False).count() >= 2
    with_salary = sum(1 for e in people if e.salary_records.exists())
    assert with_salary >= 0.6 * len(people)


@pytest.mark.django_db
def test_build_twice_adds_nothing() -> None:
    first = build(DAY)
    assert first["people"] > 0
    before = demo_people().count()

    second = build(DAY)

    assert second == {"people": 0, "departments": 0, "positions": 0}
    assert demo_people().count() == before


@pytest.mark.django_db
def test_build_leaves_existing_people_alone(role_user: Callable[[str], User]) -> None:
    existing = hire_one(role_user("hr"))

    build(DAY)

    assert Employee.objects.filter(pk=existing.pk).exists()
    assert not demo_people().filter(pk=existing.pk).exists()


@pytest.mark.django_db
def test_command_refuses_outside_the_demo_database() -> None:
    # The test settings have DEBUG off and a test_ database name, so the guard refuses before anything is written.
    with pytest.raises(CommandError):
        call_command("seed_assistant_demo")
    assert not demo_people().exists()


@pytest.mark.django_db
def test_lookups_resolve_the_demo_names() -> None:
    build(DAY)

    assert resolve("department", "Санхүү").status == "one"
    assert resolve("department", "IT").status == "one"
    assert resolve("position", "Програмист").status == "one"
    assert resolve("department", "худалдан авалт").status == "several"


@pytest.mark.django_db
def test_staff_table_counts_type_five(role_user: Callable[[str], User]) -> None:
    build(DAY)
    user = role_user("hr")
    type_five = JobRecord.objects.filter(employee__in=demo_people(), emptype=5).count()
    assert type_five >= 2

    assert build_table(REPORT, user, Filters(emptype=5)).count == type_five
