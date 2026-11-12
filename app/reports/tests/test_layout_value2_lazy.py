"""The pivot's second value on the staff list: its column is loaded even though the salary column is not shown, so the
second grid holds real sums. A viewer without the salary permission gets no second grid and no salary in the page."""

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from employees.templatetags.hr import mnt

from .conftest import legacy

pytestmark = pytest.mark.django_db

PAGE = "/reports/staff-list/"
GRID = re.compile(r'<div class="ptable')
SALARY_EACH = Decimal("1000000")
SALARY_SUM = 3000000  # three people in Санхүү at 1 000 000 each


def _grids(page: str) -> list[str]:
    return [chunk.split("</table>")[0] for chunk in GRID.split(page)[1:]]


@pytest.fixture
def finance_staff(actor: User, job_values: dict[str, Any]) -> list[Employee]:
    """Three people in one department (the minimum group, so the money figure is shown), each on the same salary."""
    return [legacy(actor, job_values, salary=SALARY_EACH) for _ in range(3)]


def test_second_grid_sums_the_salary_when_salary_is_not_a_shown_column(
    client: Client, login_as: Callable[..., User], finance_staff: list[Employee]
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "pivot", "lby": "department", "lval2": "salary:sum"}).content.decode()
    grids = _grids(page)
    assert len(grids) == 2
    assert mnt(SALARY_SUM) in grids[1]  # the real sum, not the «—» of an unloaded column


def test_viewer_without_the_salary_permission_gets_no_second_grid_and_no_salary(
    client: Client, login_as: Callable[..., User], finance_staff: list[Employee]
) -> None:
    login_as(client, "HR")  # view_personal, no macs.view_salary
    page = client.get(PAGE, {"layout": "pivot", "lby": "department", "lval2": "salary:sum"}).content.decode()
    assert len(_grids(page)) == 1
    assert str(SALARY_SUM) not in page
    assert mnt(SALARY_SUM) not in page
    assert str(int(SALARY_EACH)) not in page
    assert mnt(int(SALARY_EACH)) not in page
