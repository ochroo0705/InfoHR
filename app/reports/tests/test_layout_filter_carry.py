"""The filter bar keeps the layout's new address parameters (lgrain, lshow, lsort, lval2, lrep, lweek, lyear, lgroup,
lorder) as hidden inputs, only when they are set, so a change of any bar filter keeps the view's own options."""

from collections.abc import Callable
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client

from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "layout-filter-carry"
PAGE = f"/reports/{KEY}/"
NEW = ("lgrain", "lshow", "lsort", "lval2", "lrep", "lweek", "lyear", "lgroup", "lorder")
DEPTS = ("Санхүү", "Ачаа")

# each parameter, the value it is set to, and an address for a layout that uses it (see layouts.used_params)
CASES: dict[str, tuple[str, dict[str, str]]] = {
    "lgrain": ("quarter", {"layout": "chart", "lby": "start", "lval": "count"}),
    "lshow": ("pct", {"layout": "chart", "lby": "dept", "lval": "count"}),
    "lsort": ("value", {"layout": "chart", "lby": "dept"}),
    "lval2": ("days:sum", {"layout": "pivot", "lby": "dept", "lval": "count"}),
    "lrep": ("1", {"layout": "calendar", "lby": "start"}),
    "lweek": ("2026-11-02", {"layout": "calendar", "lby": "start"}),
    "lyear": ("2026", {"layout": "timeline", "lby": "start", "lby2": "end"}),
    "lgroup": ("dept", {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}),
    "lorder": ("count", {"layout": "board", "lby": "dept"}),
}


def _people() -> list[Any]:
    return [
        SimpleNamespace(
            name=f"Ажилтан {n:02d}",
            dept=DEPTS[n % 2],
            start=date(2026, 11, 1) + timedelta(days=n),
            end=date(2026, 11, 1) + timedelta(days=n + 3),
            days=n,
        )
        for n in range(1, 13)
    ]


@pytest.fixture
def carry_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
            Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date"),
            Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date"),
            Column(key="days", label="Өдөр", value=lambda r: r.days, numeric=True, kind="number"),
        ),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _people(),
        group_options=("dept",),
        layouts=("board", "calendar", "timeline", "chart", "pivot"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{name}" value="{value}">'


def test_filter_form_keeps_each_new_parameter(
    client: Client, login_as: Callable[..., User], carry_report: Report
) -> None:
    login_as(client, "HR")
    for name in NEW:
        value, address = CASES[name]
        page = client.get(PAGE, {**address, name: value}).content.decode()
        assert _hidden(name, value) in page, name
        # the same address without this parameter: its hidden input does not appear
        without = client.get(PAGE, address).content.decode()
        assert f'<input type="hidden" name="{name}"' not in without, name


def test_filter_form_keeps_no_new_parameter_when_none_is_set(
    client: Client, login_as: Callable[..., User], carry_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "chart", "lby": "dept", "lval": "count"}).content.decode()
    for name in NEW:
        assert f'<input type="hidden" name="{name}"' not in page, name


def test_filter_form_keeps_nothing_for_a_table(
    client: Client, login_as: Callable[..., User], carry_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"lby": "dept", "lval": "count"}).content.decode()
    for name in NEW:
        assert f'<input type="hidden" name="{name}"' not in page, name


def test_filter_form_keeps_nothing_for_a_table_with_the_new_parameters_set(
    client: Client, login_as: Callable[..., User], carry_report: Report
) -> None:
    login_as(client, "HR")
    address = {name: CASES[name][0] for name in NEW}
    page = client.get(PAGE, address).content.decode()
    for name in NEW:
        assert f'<input type="hidden" name="{name}"' not in page, name
