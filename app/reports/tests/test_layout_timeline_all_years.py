"""«Бүгд» (lyear=all) is the timeline with no window and no 5-year clip: the axis covers every drawn date. Without it
the old clip stays for a spec built that way. The cap of 100 bars and the tick labels (at most 24) still hold."""

from collections.abc import Callable
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters, parse_filters
from reports.layouts import LayoutSpec, Timeline, resolve
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


def _spec(all_years: bool) -> LayoutSpec:
    return LayoutSpec(
        layout="timeline",
        by=START,
        by2=END,
        value=(None, "count"),
        chart="bar",
        month=date(2026, 11, 1),
        all_years=all_years,
    )


def _build(rows: list[Any], spec: LayoutSpec) -> Timeline:
    table = Table(
        columns=[NAME, DEPT, START, END],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec,
    )
    return layouts_mod.build_timeline(table, spec, (), TODAY)


# the demo-like span: a row from 2008 and one in 2026
SPAN_ROWS = [
    _row("Ажилтан 00", start=date(2008, 5, 5), end=date(2008, 6, 1)),
    _row("Ажилтан 01", start=date(2026, 2, 1), end=date(2026, 3, 1)),
]


# ---- the axis ----


def test_all_years_axis_covers_every_date() -> None:
    timeline = _build(SPAN_ROWS, _spec(all_years=True))
    assert timeline.first == date(2008, 5, 5)
    assert timeline.last == date(2026, 3, 1)
    assert timeline.clipped is False
    assert timeline.off_axis == 0
    assert [bar.item.title for bar in timeline.bars] == ["Ажилтан 00", "Ажилтан 01"]


def test_without_all_years_the_old_clip_stays() -> None:
    timeline = _build(SPAN_ROWS, _spec(all_years=False))
    assert timeline.clipped is True
    assert timeline.off_axis == 1  # the 2026 row starts after the 5-year limit
    assert [bar.item.title for bar in timeline.bars] == ["Ажилтан 00"]


def test_all_years_still_caps_bars_at_100() -> None:
    rows = [_row(f"Нэр {n}", start=date(2026, 1, 1) + timedelta(days=n), end=date(2026, 1, 2)) for n in range(150)]
    timeline = _build(rows, _spec(all_years=True))
    assert timeline.shown == 100
    assert len(timeline.bars) == 100
    assert timeline.total == 150
    assert timeline.over_cap == 50
    assert timeline.off_axis == 0


def test_wide_span_has_at_most_24_ticks() -> None:
    rows = [_row("Урт", start=date(1960, 1, 1), end=date(2020, 6, 30))]  # a 61-year axis
    timeline = _build(rows, _spec(all_years=True))
    assert timeline.clipped is False
    assert 0 < len(timeline.ticks) <= 24
    assert timeline.ticks[0].label == "1960"  # the first tick is always kept
    assert timeline.ticks[0].left_pct == pytest.approx(0.0)
    lefts = [tick.left_pct for tick in timeline.ticks]
    assert lefts == sorted(lefts) and len(set(lefts)) == len(lefts)
    assert all(0.0 <= left <= 100.0 for left in lefts)


# ---- the address ----


def _report() -> Report:
    return Report(
        key="timeline-all-years-resolve",
        title="Тайлан",
        filters=(),
        columns=(NAME, DEPT, START, END),
        default_columns=("name",),
        rows=lambda user, filters: [],
        layouts=("table", "timeline", "chart"),
    )


def test_resolve_sets_all_years_only_for_lyear_all(accountant_user: User) -> None:
    report = _report()
    everything = resolve(report, accountant_user, Filters(layout="timeline", lyear="all"))
    assert everything.all_years is True
    assert everything.year is None
    assert resolve(report, accountant_user, Filters(layout="timeline", lyear="2024")).all_years is False
    assert resolve(report, accountant_user, Filters(layout="timeline", lyear="")).all_years is False
    assert resolve(report, accountant_user, Filters(layout="chart", lyear="all")).all_years is False


def test_lyear_all_parses_to_all_years() -> None:
    assert parse_filters(QueryDict("layout=timeline&lyear=all")).lyear == "all"


# ---- the page ----

KEY = "timeline-all-years-test"
PAGE = f"/reports/{KEY}/"


@pytest.fixture
def use_rows(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], None]:
    """Register a timeline report over these rows: name, dept, start and end (dates)."""

    def _use(rows: list[Any]) -> None:
        report = Report(
            key=KEY,
            title="Цагийн тэнхлэг",
            filters=(),
            columns=(NAME, DEPT, START, END),
            default_columns=("name", "dept"),
            rows=lambda user, filters: rows,
            layouts=("table", "timeline"),
        )
        monkeypatch.setitem(REPORTS, KEY, report)

    return _use


def test_page_with_lyear_all_shows_every_year_and_no_clip_note(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows(SPAN_ROWS)
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert page.count("data-bar") == 2
    assert "Хугацааны хүрээ" not in page  # the 5-year note is gone with «Бүгд»
    assert "Хүрээнээс гадуур" not in page
    assert ">2009</span>" in page  # the first January inside the axis
    assert ">2025</span>" in page  # the years in between are labelled too
