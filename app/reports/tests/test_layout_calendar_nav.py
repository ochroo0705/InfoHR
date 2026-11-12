"""The calendar's header: today's cell and the «Өнөөдөр» link, and the month jump form (UI_RULES §4b)."""

import re
from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import Calendar, Day, LayoutSpec
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


def _spec(by: Column | None = START, by2: Column | None = None, month: date = date(2026, 11, 1)) -> LayoutSpec:
    return LayoutSpec(layout="calendar", by=by, by2=by2, value=(None, "count"), chart="bar", month=month)


def _table(rows: list[Any], spec: LayoutSpec) -> Table:
    return Table(
        columns=[NAME, DEPT, START, END],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec,
    )


def _build(rows: list[Any], spec: LayoutSpec) -> Calendar:
    return layouts_mod.build_calendar(_table(rows, spec), spec, (), TODAY)


def _cells(cal: Calendar) -> list[Day]:
    return [cell for week in cal.weeks for cell in week]


def _day(cal: Calendar, day: date) -> Day:
    for cell in _cells(cal):
        if cell.day == day:
            return cell
    raise AssertionError(f"{day} is not in the grid")


def test_today_cell_is_marked() -> None:
    cal = _build([_row("Бат", start=date(2026, 11, 7))], _spec())
    assert _day(cal, date(2026, 11, 7)).is_today is True
    others = [cell.day for cell in _cells(cal) if cell.day != date(2026, 11, 7)]
    assert others and all(_day(cal, d).is_today is False for d in others)


def test_no_today_cell_in_another_month() -> None:
    # October 2026's grid ends on Sunday 1 November, so with today = 1 November that day is on the grid as a
    # spill-over day of another month: it must not be marked
    spec = _spec(month=date(2026, 10, 1))
    cal = layouts_mod.build_calendar(_table([], spec), spec, (), date(2026, 11, 1))
    assert _day(cal, date(2026, 11, 1)).in_month is False
    assert not any(cell.is_today for cell in _cells(cal))


def test_busy_days_keep_is_today() -> None:
    cal = _build([_row("Бат", start=date(2026, 11, 7)), _row("Дорж", start=date(2026, 11, 9))], _spec())
    busy = {cell.day: cell.is_today for cell in cal.busy_days}
    assert busy == {date(2026, 11, 7): True, date(2026, 11, 9): False}


# ---- the page: «Өнөөдөр» and the month form ----

KEY = "calendar-nav-test"
PAGE = f"/reports/{KEY}/"
# the calendar's link (htmx, pushes the address); the top bar has its own «Өнөөдөр» link to the day list
TODAY_LINK = re.compile(r'<a href="([^"]*)"[^>]*hx-push-url="true"[^>]*>Өнөөдөр</a>')
MONTH_FORM = re.compile(r"<form[^>]*data-month-form.*?</form>", re.DOTALL)


def _people() -> list[Any]:
    return [
        SimpleNamespace(name=f"Ажилтан {n:02d}", dept="Санхүү", start=date(2026, 1 + n % 12, 1)) for n in range(1, 6)
    ]


@pytest.fixture
def nav_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
            Column(key="start", label="Эхэлсэн", value=lambda r: r.start, kind="date"),
        ),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _people(),
        group_options=("dept",),
        layouts=("calendar",),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def test_today_link_drops_lmonth(client: Client, login_as: Callable[..., User], nav_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2025-02", "lby": "start"}).content.decode()
    match = TODAY_LINK.search(page)
    assert match is not None
    assert "lmonth" not in match.group(1)
    assert "layout=calendar" in match.group(1)


def test_month_input_present(client: Client, login_as: Callable[..., User], nav_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2025-02", "lby": "start"}).content.decode()
    form = MONTH_FORM.search(page)
    assert form is not None
    text = form.group(0)
    assert 'type="month" name="lmonth" value="2025-02"' in text
    assert 'min="1900-01"' in text and 'max="2100-12"' in text
    assert 'name="layout" value="calendar"' in text


def test_month_form_keeps_layout_and_columns(client: Client, login_as: Callable[..., User], nav_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2025-02", "lby": "start"}).content.decode()
    text = MONTH_FORM.search(page).group(0)
    assert '<input type="hidden" name="layout" value="calendar">' in text
    assert '<input type="hidden" name="lby" value="start">' in text
    assert 'type="hidden" name="lmonth"' not in text


def test_today_cell_has_data_today_on_the_current_month(
    client: Client, login_as: Callable[..., User], nav_report: Report
) -> None:
    login_as(client, "HR")
    today = timezone.localdate()
    page = client.get(PAGE, {"layout": "calendar", "lby": "start"}).content.decode()
    assert re.search(rf'data-day="{today:%Y-%m-%d}"[^>]*data-today', page)
    # only one grid cell is today
    assert len(re.findall(r'<div data-day="[^"]*"[^>]*data-today', page)) == 1


def test_month_tools_sit_in_one_right_group_apart_from_the_heading(
    client: Client, login_as: Callable[..., User], nav_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lmonth": "2025-02", "lby": "start"}).content.decode()
    group = re.search(r"<div data-calendar-tools[^>]*>(.*?)</form>\s*</div>", page, re.DOTALL)
    assert group is not None
    inside = group.group(1)
    assert 'aria-label="Өмнөх сар"' in inside
    assert 'aria-label="Дараах сар"' in inside
    assert "Өнөөдөр</a>" in inside
    assert "data-month-form" in inside
    assert "<h2" not in inside
    assert page.index("<h2") < group.start()  # the heading comes first, on the left
    # the month input carries the label; the form does not repeat it
    assert 'aria-label="Сар сонгох"' not in MONTH_FORM.search(page).group(0).split("<input")[0]
    assert page.count('aria-label="Сар сонгох"') == 1


@pytest.mark.parametrize("params", [{"lmonth": "2025-02"}, {"lweek": "2025-02-03"}], ids=["month", "week"])
def test_tools_container_wraps_on_a_phone(
    client: Client, login_as: Callable[..., User], nav_report: Report, params: dict[str, str]
) -> None:
    # Regression guard (Task 20a): a shrink-0 container kept its natural width (about 460 px) on a 375 px phone, so the
    # month picker overflowed the page sideways. The container must be allowed to shrink and wrap (max-w-full).
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "calendar", "lby": "start", **params}).content.decode()
    tag = re.search(r"<div data-calendar-tools[^>]*>", page)
    assert tag is not None
    classes = re.search(r'class="([^"]*)"', tag.group(0)).group(1).split()
    assert "max-w-full" in classes
    assert "shrink-0" not in classes
