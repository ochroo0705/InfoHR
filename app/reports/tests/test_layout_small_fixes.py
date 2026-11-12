"""Two small layout fixes: a stacked chart needs a second category, and a date column takes no sum, average or min/max
as a chart or pivot value."""

import pytest
from accounts.models import User
from django.http import QueryDict

from reports.filters import Filters, parse_filters
from reports.layouts import clean_params, resolve
from reports.types import Column, Report

pytestmark = pytest.mark.django_db


def _report(group_options: tuple[str, ...]) -> Report:
    return Report(
        key="layout-small-fixes",
        title="Тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
            Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date"),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True, money=True),
        ),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=group_options,
        layouts=("chart",),
    )


def _filters(raw: str) -> Filters:
    return parse_filters(QueryDict(raw))


def test_stacked_chart_with_one_category_is_drawn_as_a_plain_bar(accountant_user: User) -> None:
    spec = resolve(_report(("dept",)), accountant_user, _filters("layout=chart&lchart=stacked"))
    assert spec.chart == "bar"
    assert spec.by2 is None


def test_stacked_chart_with_two_categories_stays_stacked(accountant_user: User) -> None:
    spec = resolve(_report(("dept", "name")), accountant_user, _filters("layout=chart&lchart=stacked"))
    assert spec.chart == "stacked"
    assert spec.by is not None and spec.by2 is not None
    assert spec.by2.key == "dept"  # the first category (name) is the main one, the other is the second


def test_date_column_max_is_refused_as_a_value(accountant_user: User) -> None:
    cleaned = clean_params(_report(("dept",)), accountant_user, _filters("layout=chart&lval=start:max"))
    assert cleaned["lval"] == ""


def test_number_column_max_is_kept_as_a_value(accountant_user: User) -> None:
    cleaned = clean_params(_report(("dept",)), accountant_user, _filters("layout=chart&lval=pay:max"))
    assert cleaned["lval"] == "pay:max"


def test_count_is_kept_as_a_value(accountant_user: User) -> None:
    cleaned = clean_params(_report(("dept",)), accountant_user, _filters("layout=chart&lval=count"))
    assert cleaned["lval"] == "count"
