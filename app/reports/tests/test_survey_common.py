from datetime import date
from typing import Any

import pytest
from accounts.models import User
from employees.services import macs_writes
from macs.models import Employee

from reports import staff_list
from reports.filters import Filters
from reports.survey_common import UNKNOWN, bracket, people

from .conftest import legacy

pytestmark = pytest.mark.django_db


def test_bracket_edges() -> None:
    assert bracket(24) == "24 хүртэл"
    assert bracket(25) == "25–34"
    assert bracket(59) == "55–59"
    assert bracket(60) == "60 ба түүнээс дээш"
    assert bracket(None) is None
    assert UNKNOWN == "Заагаагүй"


def test_people_age_counts_full_years_on_the_as_of_date(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    emp = legacy(actor, job_values, birth_date=date(1990, 6, 15))
    before = [p for p in people(hr_user, Filters(as_of=date(2026, 6, 14))) if p.row.employee.pk == emp.pk]
    on = [p for p in people(hr_user, Filters(as_of=date(2026, 6, 15))) if p.row.employee.pk == emp.pk]
    assert [p.age for p in before] == [35]
    assert [p.age for p in on] == [36]


def test_people_has_no_age_without_birth_date(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    emp = legacy(actor, job_values, birth_date=None)
    found = [p for p in people(hr_user, Filters()) if p.row.employee.pk == emp.pk]
    assert [p.age for p in found] == [None]


def test_people_limits_to_visible_and_filters(hr_user: User, hired: Employee) -> None:
    assert [p.row.employee.pk for p in people(hr_user, Filters())] == [hired.pk]
    other = macs_writes.save_department("Борлуулалт")
    assert people(hr_user, Filters(department=other.pk)) == []


def test_people_are_the_staff_list_selection(hr_user: User, hired: Employee, actor: User) -> None:
    """The people come from the staff list's own selection, so the two reports agree on who is on staff."""
    listed = {s.row.employee.pk for s in staff_list.rows(hr_user, Filters())}
    assert {p.row.employee.pk for p in people(hr_user, Filters())} == listed


def test_age_is_none_when_the_day_is_before_the_birth_date(hr_user: User, hired: Employee) -> None:
    """A day before the birth date gives no age yet, never a negative one (as children.py)."""
    Employee.objects.filter(pk=hired.pk).update(birth_date=date(1999, 11, 22))
    found = [p for p in people(hr_user, Filters(state="all", as_of=date(1990, 1, 1))) if p.row.employee.pk == hired.pk]
    assert [p.age for p in found] == [None]
