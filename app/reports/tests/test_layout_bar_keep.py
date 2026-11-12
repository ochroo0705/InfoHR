"""The layout bar's hidden inputs carry the layout parameters that have no select in the bar (lyear, lweek: set by the
header links), and never the ones the bar itself has a select for. A layout switch drops every layout parameter."""

import re
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

KEY = "layout-bar-keep"
PAGE = f"/reports/{KEY}/"
BAR = re.compile(r'<form[^>]*aria-label="Харагдацын багана".*?</form>', re.DOTALL)


def _people() -> list[Any]:
    return [
        SimpleNamespace(
            name=f"Ажилтан {n:02d}",
            dept=("Санхүү", "Ачаа")[n % 2],
            start=date(2026, 11, 1) + timedelta(days=n),
            end=date(2026, 11, 1) + timedelta(days=n + 3),
        )
        for n in range(1, 13)
    ]


@pytest.fixture
def bar_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
            Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date"),
            Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date"),
        ),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _people(),
        group_options=("dept",),
        layouts=("board", "calendar", "timeline", "chart", "pivot"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _bar(page: str) -> str:
    match = BAR.search(page)
    assert match is not None, "the layout bar form is not on the page"
    return match.group(0)


def _hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{name}" value="{value}">'


def test_timeline_bar_keeps_the_year_window_once(
    client: Client, login_as: Callable[..., User], bar_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "2026"}).content.decode()
    bar = _bar(page)
    assert bar.count(_hidden("lyear", "2026")) == 1
    for name in ("lgroup", "lgrain", "lval2"):
        assert f'<input type="hidden" name="{name}"' not in bar, name


def test_calendar_week_bar_keeps_the_week(client: Client, login_as: Callable[..., User], bar_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lby": "start", "lweek": "2026-11-09"}).content.decode()
    assert _hidden("lweek", "2026-11-09") in _bar(page)


def test_layout_switch_links_drop_the_year_and_the_week(
    client: Client, login_as: Callable[..., User], bar_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(
        PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "2026", "lweek": "2026-11-09"}
    )
    urls = response.context["layout_urls"]
    assert "table" in urls
    for name, url in urls.items():
        assert "lyear=" not in url, (name, url)
        assert "lweek=" not in url, (name, url)


def test_month_view_bar_has_no_week(client: Client, login_as: Callable[..., User], bar_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lby": "start"}).content.decode()
    assert '<input type="hidden" name="lweek"' not in _bar(page)
