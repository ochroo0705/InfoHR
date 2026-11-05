from collections.abc import Callable

import pytest
from accounts.models import User
from django.http import QueryDict
from macs.models import Department
from reports.filters import parse_filters
from reports.staff_list import REPORT
from reports.table import build_table

from assistant.chart_data import ChartData, chart_data
from assistant.tests.helpers import hire_one

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("query", ["", "emptype=5", "gender=F"])
def test_total_equals_table_count(role_user: Callable[[str], User], query: str) -> None:
    user: User = role_user("hr")
    actor: User = role_user("hr")
    hire_one(actor)
    hire_one(actor)

    data = chart_data(user, query, "bar", "department")
    table = build_table(REPORT, user, parse_filters(QueryDict(query)))

    assert data is not None
    assert data.total == table.count
    assert data.total == sum(data.counts)


def test_groups_by_department(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    actor: User = role_user("hr")
    hire_one(actor)
    hire_one(actor)

    data = chart_data(user, "", "pie", "department")

    assert data == ChartData(
        kind="pie",
        by="department",
        by_label="Хэлтэс",
        labels=("Санхүү",),
        counts=(2,),
        total=2,
    )


def test_bad_kind_or_by_is_none(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    assert chart_data(user, "", "line", "department") is None
    assert chart_data(user, "", "bar", "name") is None  # a column, but not a group option
    assert chart_data(user, "", "bar", "bogus") is None


def test_unusable_filter_dropped(role_user: Callable[[str], User]) -> None:
    # hr may not see salary, so a salary bound that would empty the chart is dropped and the chart is unchanged.
    user: User = role_user("hr")
    actor: User = role_user("hr")
    hire_one(actor)
    unfiltered = chart_data(user, "", "pie", "department")

    filtered = chart_data(user, "salary_from=9000000", "pie", "department")

    assert unfiltered is not None
    assert unfiltered.total > 0
    assert filtered == unfiltered


def test_zero_people_gives_empty_chart(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    dept = Department.objects.create(name="Маркетинг")

    data = chart_data(user, f"department={dept.pk}", "bar", "department")

    assert data is not None
    assert data.labels == ()
    assert data.counts == ()
    assert data.total == 0


def test_user_who_may_not_open_the_table_gets_none(role_user: Callable[[str], User]) -> None:
    assert chart_data(role_user("staff"), "", "bar", "department") is None


def test_malformed_or_huge_query_means_no_filters(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    plain = chart_data(user, "", "bar", "department")
    huge = chart_data(user, "&".join(f"k{i}=1" for i in range(2000)), "bar", "department")
    assert plain is not None and huge is not None
    assert huge.total == plain.total
