"""The week view of the calendar: the Monday-first week of lweek, the 12-entry cap, a week over a month or year edge,
repeats and multi-day entries inside the week, today, the year-bound arrows, the header toggle, the empty table, and the
month view's «+N» link to its week (Decision 4 of docs/superpowers/plans/2026-11-11-report-view-gaps.md)."""

import re
from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters, parse_filters
from reports.layouts import Day, LayoutSpec, Week, build_week, resolve, used_params
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
END = Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")


def _row(name: str, start: object = None, end: object = None, dept: str = "X") -> Any:
    return SimpleNamespace(name=name, dept=dept, start=start, end=end)


def _spec(
    by: Column | None = START, by2: Column | None = None, week: date | None = date(2026, 11, 2), rep: bool = False
) -> LayoutSpec:
    return LayoutSpec(
        layout="calendar",
        by=by,
        by2=by2,
        value=(None, "count"),
        chart="bar",
        month=date(2026, 11, 1),
        rep=rep,
        week=week,
    )


def _table(rows: list[Any], spec: LayoutSpec) -> Table:
    return Table(
        columns=[NAME, DEPT, START, END],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec,
    )


def _build(rows: list[Any], spec: LayoutSpec, today: date = TODAY) -> Week:
    return build_week(_table(rows, spec), spec, (), today)


def _day(week: Week, day: date) -> Day:
    for cell in week.days:
        if cell.day == day:
            return cell
    raise AssertionError(f"{day} is not in the week")


def _titles(week: Week, day: date) -> list[str]:
    return [item.title for item in _day(week, day).items]


def test_week_has_seven_days_monday_first() -> None:
    week = _build([], _spec(week=date(2026, 11, 2)))
    assert week.start == date(2026, 11, 2)
    assert week.start.weekday() == 0
    assert week.end == date(2026, 11, 8)
    assert len(week.days) == 7
    assert [d.day for d in week.days] == [date(2026, 11, n) for n in range(2, 9)]
    assert all(d.in_month is True for d in week.days)


def test_week_crossing_a_month_and_year() -> None:
    week = _build([], _spec(week=date(2026, 12, 28)))
    assert [d.day for d in week.days][0] == date(2026, 12, 28)
    assert [d.day for d in week.days][-1] == date(2027, 1, 3)
    assert week.next == "2027-01-04"
    assert week.prev == "2026-12-21"


def test_week_cap_is_12_with_more() -> None:
    assert layouts_mod.WEEK_PER_DAY == 12
    rows = [_row(f"Нэр {i:02d}", start=date(2026, 11, 4)) for i in range(15)]
    week = _build(rows, _spec(week=date(2026, 11, 2)))
    day = _day(week, date(2026, 11, 4))
    assert len(day.items) == 12
    assert day.more == 3
    assert [item.title for item in day.items][0] == "Нэр 00"


def test_week_normalises_any_day_to_its_monday(accountant_user: User) -> None:
    report = Report(
        key="week-resolve",
        title="Тайлан",
        filters=(),
        columns=(NAME, DEPT, START, END),
        default_columns=("name",),
        rows=lambda user, filters: [],
        layouts=("calendar",),
    )
    spec = resolve(report, accountant_user, parse_filters(QueryDict("layout=calendar&lweek=2026-11-05&lby=start")))
    assert spec.week == date(2026, 11, 2)


def test_week_keeps_multi_day_entries() -> None:
    rows = [_row("Бат", start=date(2026, 11, 5), end=date(2026, 11, 8))]
    week = _build(rows, _spec(by2=END, week=date(2026, 11, 2)))
    shown = [d.day for d in week.days if any(i.title == "Бат" for i in d.items)]
    assert shown == [date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 8)]


def test_week_repeat_birthday() -> None:
    rows = [_row("Бат", start=date(1990, 11, 5))]
    week = _build(rows, _spec(week=date(2026, 11, 2), rep=True))
    items = _day(week, date(2026, 11, 5)).items
    assert [item.title for item in items] == ["Бат"]
    assert items[0].note == "36 жил"
    assert _titles(week, date(2026, 11, 6)) == []


def test_week_today_marked() -> None:
    week = _build([], _spec(week=date(2026, 11, 2)), today=date(2026, 11, 4))
    assert [d.day for d in week.days if d.is_today] == [date(2026, 11, 4)]
    outside = _build([], _spec(week=date(2026, 11, 2)), today=date(2026, 12, 1))
    assert not any(d.is_today for d in outside.days)


def test_year_bounds_clamp_at_the_start() -> None:
    week = _build([], _spec(week=date(1900, 1, 1)))
    assert week.start == date(1900, 1, 1)
    assert week.prev == week.start.isoformat()  # the same Monday: the arrow is drawn disabled
    assert week.next == "1900-01-08"


def test_year_bounds_clamp_at_the_end() -> None:
    week = _build([], _spec(week=date(2100, 12, 31)))
    assert week.start == date(2100, 12, 27)
    assert week.next == week.start.isoformat()
    assert week.prev == "2100-12-20"


def test_used_params_writes_lweek_only_for_calendar() -> None:
    cal = _spec(week=date(2026, 11, 2))
    assert used_params(Filters(), cal).lweek == "2026-11-02"
    board = LayoutSpec(
        layout="board",
        by=None,
        by2=None,
        value=(None, "count"),
        chart="bar",
        month=date(2026, 11, 1),
        week=date(2026, 11, 2),
    )
    assert used_params(Filters(), board).lweek == ""
    table = LayoutSpec(layout="table", by=None, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1))
    assert used_params(Filters(), table).lweek == ""
    month_view = _spec(week=None)
    assert used_params(Filters(), month_view).lweek == ""


# ---- the page ----

KEY = "week-view-test"
PAGE = f"/reports/{KEY}/"
EMPTY_KEY = "week-view-empty"
EMPTY_PAGE = f"/reports/{EMPTY_KEY}/"
TOOLS = re.compile(r"<div data-calendar-tools[^>]*>")


def _people() -> list[Any]:
    # four people start on Tuesday 10 November 2026: one more than the month grid draws
    return [SimpleNamespace(name=f"Ажилтан {n:02d}", dept="Санхүү", start=date(2026, 11, 10)) for n in range(4)]


def _make_report(monkeypatch: pytest.MonkeyPatch, key: str, rows: Callable[..., list[Any]]) -> Report:
    report = Report(
        key=key,
        title="Ажилтны тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
            Column(key="start", label="Эхэлсэн", value=lambda r: r.start, kind="date"),
        ),
        default_columns=("name", "dept"),
        rows=rows,
        group_options=("dept",),
        layouts=("calendar",),
    )
    monkeypatch.setitem(REPORTS, key, report)
    return report


@pytest.fixture
def week_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    return _make_report(monkeypatch, KEY, lambda user, filters: _people())


@pytest.fixture
def empty_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    return _make_report(monkeypatch, EMPTY_KEY, lambda user, filters: [])


def _tools_block(page: str) -> str:
    """The header's tools: from the data-calendar-tools tag up to the week grid (or the month grid)."""
    start = TOOLS.search(page)
    assert start is not None
    end = page.index('<div class="hidden sm:grid', start.end())
    return page[start.start() : end]


def test_week_page_has_toggle_and_arrows(client: Client, login_as: Callable[..., User], week_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lweek": "2026-11-02"}).content.decode()
    tools = _tools_block(page)
    assert "2026-11-02 – 2026-11-08" in page
    assert re.search(r'<a href="[^"]*"[^>]*>Сар</a>', tools) is not None
    assert '<span aria-current="true"' in tools and "7 хоног</span>" in tools
    assert 'aria-label="Өмнөх долоо хоног"' in tools
    assert 'aria-label="Дараах долоо хоног"' in tools
    assert "lweek=2026-10-26" in tools
    assert "lweek=2026-11-09" in tools
    assert "Өнөөдөр</a>" in tools


def test_week_page_arrows_at_the_year_bound_are_disabled(
    client: Client, login_as: Callable[..., User], week_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "calendar", "lweek": "2100-12-31"})
    assert response.status_code == 200
    tools = _tools_block(response.content.decode())
    assert 'aria-disabled="true"' in tools
    assert 'aria-label="Дараах долоо хоног"' not in tools  # the next arrow is the grey span, not a link
    assert 'aria-label="Өмнөх долоо хоног"' in tools
    first = client.get(PAGE, {"layout": "calendar", "lweek": "1900-01-01"})
    assert first.status_code == 200
    assert 'aria-label="Өмнөх долоо хоног"' not in _tools_block(first.content.decode())


def test_month_page_has_week_toggle(client: Client, login_as: Callable[..., User], week_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2025-02", "lby": "start"}).content.decode()
    tools = _tools_block(page)
    assert '<span aria-current="true"' in tools and "Сар</span>" in tools
    assert re.search(r'<a href="([^"]*)"[^>]*>7 хоног</a>', tools) is not None
    # February 2025 starts on a Saturday: the week of its 1st is the Monday 27 January
    assert "lweek=2025-01-27" in tools


def test_month_plus_n_links_to_the_week(client: Client, login_as: Callable[..., User], week_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2026-11", "lby": "start"}).content.decode()
    link = re.search(r'<a href="([^"]*)"[^>]*>\+1</a>', page)
    assert link is not None
    assert "lweek=2026-11-09" in link.group(1)  # 10 November 2026 is a Tuesday: its week starts Monday 9 November
    assert "layout=calendar" in link.group(1)
    assert "lmonth" not in link.group(1)


def test_week_view_empty_table_says_no_data(
    client: Client, login_as: Callable[..., User], empty_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(EMPTY_PAGE, {"layout": "calendar", "lweek": "2026-11-02"}).content.decode()
    assert "Өгөгдөл олдсонгүй" in page
    assert "data-calendar-tools" not in page
