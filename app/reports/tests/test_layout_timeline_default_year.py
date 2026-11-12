"""The timeline's default year window (2026-11-11): with no lyear the timeline shows the current year; lyear=all is
the old 5-year axis with no window; «Он» opens a year only when there is no window. The page links carry the lyear."""

import re
from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.utils import timezone

from reports.filters import Filters, parse_filters
from reports.layouts import LayoutSpec, resolve, used_params
from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
END = Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")
KEY = "timeline-default-year-test"
PAGE = f"/reports/{KEY}/"


def _report(layouts: tuple[str, ...] = ("table", "timeline", "chart")) -> Report:
    return Report(
        key=KEY,
        title="Цагийн тайлан",
        filters=(),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"), DEPT, START, END),
        default_columns=("name",),
        rows=lambda user, filters: [],
        layouts=layouts,
    )


def _spec(layout: str = "timeline", **extra: Any) -> LayoutSpec:
    return LayoutSpec(
        layout=layout, by=None, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1), **extra
    )


def _parse(raw: str) -> Filters:
    return parse_filters(QueryDict(raw))


def _row(name: str, start: object, end: object) -> Any:
    return SimpleNamespace(name=name, dept="X", start=start, end=end)


@pytest.fixture
def use_rows(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], None]:
    """Register a timeline report over these rows: name, dept, start and end (dates)."""

    def _use(rows: list[Any]) -> None:
        report = Report(
            key=KEY,
            title="Цагийн тайлан",
            filters=(),
            columns=(
                Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
                DEPT,
                START,
                END,
            ),
            default_columns=("name", "dept"),
            rows=lambda user, filters: rows,
            layouts=("table", "timeline"),
        )
        monkeypatch.setitem(REPORTS, KEY, report)

    return _use


def _anchor_href(page: str, text: str) -> str:
    """The href of the link whose text is this (the link has no other text inside it)."""
    match = re.search(r'<a [^>]*href="([^"]*)"[^>]*>' + re.escape(text) + "</a>", page)
    assert match is not None, f"no link {text}"
    return match.group(1)


# ---- the resolved window ----


def test_default_window_is_the_current_year(accountant_user: User) -> None:
    spec = resolve(_report(), accountant_user, Filters(layout="timeline"))
    assert spec.year == timezone.localdate().year


def test_lyear_all_means_no_window(accountant_user: User) -> None:
    spec = resolve(_report(), accountant_user, Filters(layout="timeline", lyear="all"))
    assert spec.year is None


def test_lyear_digits_is_the_window(accountant_user: User) -> None:
    spec = resolve(_report(), accountant_user, Filters(layout="timeline", lyear="2024"))
    assert spec.year == 2024


def test_default_window_is_not_used_by_other_layouts(accountant_user: User) -> None:
    spec = resolve(_report(), accountant_user, Filters(layout="chart"))
    assert spec.year is None


# ---- the address ----


def test_used_params_writes_lyear_only_from_the_request() -> None:
    assert used_params(Filters(layout="timeline", lyear=""), _spec(year=timezone.localdate().year)).lyear == ""
    assert used_params(Filters(layout="timeline", lyear="all"), _spec(year=None)).lyear == "all"
    assert used_params(Filters(layout="timeline", lyear="2024"), _spec(year=2024)).lyear == "2024"
    assert used_params(Filters(layout="chart", lyear="2024"), _spec("chart")).lyear == ""
    assert used_params(Filters(layout="table", lyear="2024"), _spec("table")).lyear == ""


def test_year_filter_accepts_all_and_rejects_garbage() -> None:
    assert _parse("lyear=all").lyear == "all"
    assert _parse("lyear=allx").lyear == ""
    assert _parse("lyear=2024").lyear == "2024"


# ---- the page ----


def test_page_without_lyear_shows_this_year_and_the_all_link(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    year = timezone.localdate().year
    use_rows([_row("Ажилтан 01", date(2020, 1, 10), date(2020, 4, 20))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end"}).content.decode()
    assert f'<span class="px-2 font-semibold text-slate-700">{year}</span>' in page
    assert 'aria-label="Өмнөх жил"' in page
    all_href = _anchor_href(page, "Бүгд")
    assert "lyear=all" in all_href
    assert f"lyear={year}" not in all_href
    assert 'title="Нэг жилээр харах"' not in page  # «Он» only without a window


def test_all_then_enter_link_opens_this_year(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    year = timezone.localdate().year
    use_rows([_row("Ажилтан 01", date(2020, 1, 10), date(2020, 4, 20))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert 'aria-label="Өмнөх жил"' not in page  # no window: no arrows
    enter_href = _anchor_href(page, "Он")
    assert f"lyear={year}" in enter_href
    assert "lyear=all" not in enter_href
    assert 'title="Нэг жилээр харах"' in page


def test_layout_bar_keeps_lyear_all_in_its_hidden_inputs(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", date(2020, 1, 10), date(2020, 4, 20))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert '<input type="hidden" name="lyear" value="all">' in page  # the bar's form carries it (two forms render it)


def test_layout_bar_keeps_an_explicit_year_in_its_hidden_inputs(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", date(2020, 1, 10), date(2020, 4, 20))])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "2020"}).content.decode()
    assert '<input type="hidden" name="lyear" value="2020">' in page
