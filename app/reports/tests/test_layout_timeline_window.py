"""The timeline year window (lyear): the axis is the calendar year, bars are clipped to it, rows outside it count as
off the axis and never use the bar cap; the header's arrows, «Бүгд» and «Он» links on the page."""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec, Timeline
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
END = Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")


def _row(name: str, start: object = None, end: object = None) -> Any:
    return SimpleNamespace(name=name, dept="X", start=start, end=end)


def _spec(by: Column | None = START, by2: Column | None = END) -> LayoutSpec:
    return LayoutSpec(layout="timeline", by=by, by2=by2, value=(None, "count"), chart="bar", month=date(2026, 11, 1))


def _build(rows: list[Any], spec: LayoutSpec | None = None) -> Timeline:
    spec = spec or _spec()
    table = Table(
        columns=[NAME, DEPT, START, END],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec,
    )
    return layouts_mod.build_timeline(table, spec, (), TODAY)


def _window(year: int) -> LayoutSpec:
    return replace(_spec(), year=year)


# ---- the axis and the clipping ----


def test_window_axis_is_the_year() -> None:
    timeline = _build([_row("Бат", start=date(2026, 3, 1), end=date(2026, 3, 5))], _window(2026))
    assert timeline.first == date(2026, 1, 1)
    assert timeline.last == date(2026, 12, 31)
    assert timeline.clipped is False


def test_bar_crossing_the_edge_is_clipped() -> None:
    timeline = _build([_row("Бат", start=date(2025, 12, 1), end=date(2026, 2, 10))], _window(2026))
    bar = timeline.bars[0]
    assert bar.left_pct == 0.0
    assert bar.start == date(2025, 12, 1)  # the real dates stay for the tooltip
    assert bar.end == date(2026, 2, 10)
    assert bar.width_pct == pytest.approx(41 / 365 * 100)  # 1 Jan to 10 Feb, both days counted


def test_rows_outside_count_as_off_axis() -> None:
    rows = [
        _row("Ended before", start=date(2025, 12, 1), end=date(2025, 12, 31)),
        _row("Starts after", start=date(2027, 1, 1), end=date(2027, 1, 5)),
        _row("Inside", start=date(2026, 5, 1), end=date(2026, 5, 2)),
    ]
    timeline = _build(rows, _window(2026))
    assert timeline.off_axis == 2
    assert timeline.shown == 1
    assert [bar.item.title for bar in timeline.bars] == ["Inside"]
    assert timeline.over_cap == 0


def test_outside_rows_do_not_consume_the_cap() -> None:
    outside = [_row(f"Old {n:03d}", start=date(2025, 3, 1), end=date(2025, 3, 2)) for n in range(150)]
    inside = [_row(f"In {n}", start=date(2026, 6, 1), end=date(2026, 6, 3)) for n in range(3)]
    timeline = _build(outside + inside, _window(2026))
    assert len(timeline.bars) == 3
    assert timeline.shown == 3
    assert timeline.off_axis == 150
    assert timeline.over_cap == 0


def test_overlapping_rows_past_the_cap_are_over_cap() -> None:
    inside = [_row(f"In {n:03d}", start=date(2026, 6, 1), end=date(2026, 6, 3)) for n in range(102)]
    timeline = _build(inside, _window(2026))
    assert timeline.shown == 100
    assert timeline.off_axis == 0
    assert timeline.over_cap == 2


def test_no_window_is_unchanged() -> None:
    rows = [
        _row("Бат", start=date(2026, 1, 1), end=date(2026, 1, 10)),
        _row("Оюу", start=date(2026, 2, 1), end=date(2026, 3, 1)),
    ]
    timeline = _build(rows)  # no spec.year
    assert timeline.first == date(2026, 1, 1)
    assert timeline.last == date(2026, 3, 1)
    assert timeline.clipped is False
    assert timeline.off_axis == 0
    assert timeline.shown == 2


# ---- the page: the header, its links and the bounds ----


KEY = "timeline-window-test"
PAGE = f"/reports/{KEY}/"
SALARY = 8765432


@pytest.fixture
def use_rows(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], None]:
    """Register a report over these rows: name, dept, start and end (dates) and a hidden salary."""

    def _use(rows: list[Any]) -> None:
        report = Report(
            key=KEY,
            title="Цагийн тайлан",
            filters=(),
            columns=(
                Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
                Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
                Column(key="start", label="Эхэлсэн", value=lambda r: r.start, kind="date"),
                Column(key="end", label="Дууссан", value=lambda r: r.end, kind="date"),
                Column(
                    key="pay",
                    label="Цалин",
                    value=lambda r: SALARY,
                    needs="macs.view_salary",
                    numeric=True,
                    money=True,
                    kind="number",
                ),
            ),
            default_columns=("name", "dept"),
            rows=lambda user, filters: rows,
            group_options=("dept",),
            layouts=("board", "calendar", "timeline"),
        )
        monkeypatch.setitem(REPORTS, KEY, report)

    return _use


def _anchor_href(page: str, text: str) -> str:
    """The href of the link whose text is this (the link has no other text inside it)."""
    match = re.search(r'<a [^>]*href="([^"]*)"[^>]*>' + re.escape(text) + "</a>", page)
    assert match is not None, f"no link {text}"
    return match.group(1)


def _rows_2026() -> list[Any]:
    return [
        _row("Ажилтан 01", start=date(2026, 1, 1), end=date(2026, 1, 10)),
        _row("Ажилтан 02", start=date(2026, 2, 1), end=date(2026, 3, 1)),
    ]


def test_all_link_clears_the_year(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows(_rows_2026())
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "2026"}).content.decode()
    href = _anchor_href(page, "Бүгд")
    assert "lyear=all" in href  # «Бүгд» is no window now (the default is this year), not an empty lyear
    assert "lyear=2026" not in href
    assert "layout=timeline" in href


def test_year_arrows_stop_at_the_bounds(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows(_rows_2026())
    login_as(client, "HR")
    base = {"layout": "timeline", "lby": "start", "lby2": "end"}
    first = client.get(PAGE, {**base, "lyear": "1900"}).content.decode()
    assert 'aria-label="Өмнөх жил"' not in first  # no link before 1900
    assert 'aria-label="Дараах жил"' in first
    assert 'aria-disabled="true"' in first
    assert "Өмнөх жил</span>" in first  # the grey span carries the same name

    last = client.get(PAGE, {**base, "lyear": "2100"}).content.decode()
    assert 'aria-label="Дараах жил"' not in last  # no link after 2100
    assert "Дараах жил</span>" in last
    assert 'aria-label="Өмнөх жил"' in last


def test_enter_link_without_a_window(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    """«Он» without a window opens today's year, not the axis' first year: the axis here starts in 2008."""
    use_rows([_row("Ажилтан 00", start=date(2008, 5, 1), end=date(2008, 6, 1)), *_rows_2026()])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert 'title="Нэг жилээр харах"' in page
    assert f"lyear={timezone.localdate().year}" in _anchor_href(page, "Он")
    assert "lyear=2008" not in _anchor_href(page, "Он")


def test_header_is_absent_for_an_empty_table(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([])
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "2026"}).content.decode()
    assert "data-timeline-tools" not in page
    assert "Бүгд</a>" not in page
