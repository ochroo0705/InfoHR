from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.utils import timezone
from employees.models import Employee

from reports.ages import REPORT
from reports.filters import Filters, parse_filters
from reports.survey_common import bracket
from reports.table import build_table

from .conftest import legacy

pytestmark = pytest.mark.django_db


def _set_birth(employee: Employee, on: date | None) -> None:
    Employee.objects.filter(pk=employee.pk).update(birth_date=on)


def test_age_and_bracket_on_the_chosen_date(hr_user: User, hired: Employee) -> None:
    _set_birth(hired, date(1970, 5, 1))
    before = REPORT.rows(hr_user, Filters(as_of=date(2026, 4, 30)))
    assert [p.age for p in before] == [55]
    assert bracket(before[0].age) == "55–59"
    after = REPORT.rows(hr_user, Filters(as_of=date(2026, 5, 1)))
    assert [p.age for p in after] == [56]


def test_person_without_birth_date_has_blank_age_and_bracket_and_sorts_last(
    hr_user: User, actor: User, hired: Employee, job_values: dict[str, Any]
) -> None:
    _set_birth(hired, None)
    older = legacy(actor, job_values, birth_date=date(1950, 1, 1))
    people = REPORT.rows(hr_user, Filters())
    assert [p.row.employee.pk for p in people] == [older.pk, hired.pk]
    assert people[-1].age is None
    assert bracket(people[-1].age) is None


def test_group_by_bracket_splits_and_orders_the_groups(
    client: Client, login_hr: User, actor: User, job_values: dict[str, Any]
) -> None:
    """Two people in different brackets: two group headers, the younger bracket first, each with its count."""
    legacy(actor, job_values, birth_date=date(timezone.localdate().year - 60, 1, 1))  # 60 ба түүнээс дээш
    legacy(actor, job_values, birth_date=date(timezone.localdate().year - 24, 1, 1))  # 24 хүртэл
    page = client.get("/reports/ages/", {"group": "bracket"}).content.decode()
    young = page.index("24 хүртэл · 1")
    old = page.index("60 ба түүнээс дээш · 1")
    assert young < old
    assert "25–34 · 0" not in page  # an empty bracket has no group header


def test_sort_by_age_puts_people_without_birth_date_last(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    legacy(actor, job_values, birth_date=date(1990, 1, 1))
    legacy(actor, job_values, birth_date=None)
    legacy(actor, job_values, birth_date=date(1950, 1, 1))
    ages_of: dict[str, list[Any]] = {}
    for sort in ("age", "-age"):
        table = build_table(REPORT, hr_user, parse_filters(QueryDict(f"sort={sort}")))
        index = [c.key for c in table.columns].index("age")
        ages_of[sort] = [row[index].value for row in table.groups[0][1]]
    assert ages_of["age"] == [36, 76, None]
    assert ages_of["-age"] == [76, 36, None]


def test_bracket_boundaries_at_24_25_59_60(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    as_of = date(2026, 6, 1)
    for birth in (date(2002, 1, 1), date(2001, 1, 1), date(1967, 1, 1), date(1966, 1, 1)):
        legacy(actor, job_values, birth_date=birth)  # ages 24, 25, 59, 60 on as_of
    found = sorted((p.age, bracket(p.age)) for p in REPORT.rows(hr_user, Filters(as_of=as_of)))
    assert found == [
        (24, "24 хүртэл"),
        (25, "25–34"),
        (59, "55–59"),
        (60, "60 ба түүнээс дээш"),
    ]


def test_state_filter_left_people(hr_user: User, left_employee: Employee) -> None:
    people = REPORT.rows(hr_user, Filters(state="left"))
    assert [p.row.employee.pk for p in people] == [left_employee.pk]


def test_accountant_and_employee_role_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/ages/").status_code == 403
    client.logout()
    login_as(client, "Employee", "emp")
    assert client.get("/reports/ages/").status_code == 403
