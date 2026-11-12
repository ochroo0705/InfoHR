"""Chart sort by value (lsort: value high to low, valueasc low to high), Task 7: the points, keys and series stay
aligned; None values, the blank «—» and the folded «Бусад» stay last in that order; a line chart and a date category
ignore the sort; the layout bar shows the «Эрэмбэ» select for a chart only."""

from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
POS = Column(key="pos", label="Албан тушаал", value=lambda r: r.pos, kind="text")
AMOUNT = Column(key="amount", label="Тоо дүн", value=lambda r: r.amount, kind="number", numeric=True)
WHEN = Column(key="when", label="Огноо", value=lambda r: r.when, kind="date")
KEY = "layout-sort-test"
PAGE = f"/reports/{KEY}/"


def _row(dept: str, amount: object = 0, pos: str = "X", when: date | None = None) -> Any:
    return SimpleNamespace(dept=dept, amount=amount, pos=pos, when=when)


def _spec(
    value: tuple[Column | None, str] = (AMOUNT, "sum"),
    by: Column = DEPT,
    by2: Column | None = None,
    chart: str = "bar",
    sort: str = "",
    grain: str = "",
) -> LayoutSpec:
    return LayoutSpec(
        layout="chart",
        by=by,
        by2=by2,
        value=value,
        chart=chart,
        month=date(2026, 11, 1),
        grain=grain,
        sort=sort,
    )


def _build(rows: list[Any], spec: LayoutSpec) -> layouts_mod.Chart:
    table = Table(
        columns=[DEPT, POS, AMOUNT, WHEN],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec,
    )
    return layouts_mod.build_chart(table, spec)


# One row per department: alpha 4, bravo 9, charlie 9 (a tie with bravo), delta has only a blank amount (None),
# and the blank department («—») has 50, the biggest figure of all, which still goes last.
MIXED = [
    _row("alpha", 4),
    _row("bravo", 9),
    _row("charlie", 9),
    _row("delta", None),
    _row("", 50),
]


def test_value_desc() -> None:
    chart = _build(MIXED, _spec(sort="value"))
    assert [p.label for p in chart.points] == ["bravo", "charlie", "alpha", "delta", "—"]
    assert [p.value for p in chart.points] == [9, 9, 4, None, 50]
    assert chart.keys == ["bravo", "charlie", "alpha", "delta", ""]


def test_valueasc() -> None:
    rows = [_row("alpha", 4), _row("bravo", 9), _row("charlie", 1)]
    chart = _build(rows, _spec(sort="valueasc"))
    assert [p.label for p in chart.points] == ["charlie", "alpha", "bravo"]
    assert [p.value for p in chart.points] == [1, 4, 9]
    assert chart.keys == ["charlie", "alpha", "bravo"]


def test_folded_and_blank_stay_last() -> None:
    chart = _build(MIXED, _spec(sort="value"))
    assert chart.folded is False
    assert chart.keys[-1] == ""  # the blank «—» is last, after the None value
    assert chart.keys[-2] == "delta"  # the None value is before the blank

    # 31 named departments: the 29 first (k00..k28) are drawn, k29 and k30 fold into «Бусад» (30 + 31 = 61)
    many = [_row(f"k{i:02d}", i + 1) for i in range(31)]
    folded = _build(many, _spec(sort="value"))
    assert folded.folded is True
    assert folded.points[-1].label == layouts_mod.FOLDED
    assert folded.points[-1].value == 61
    assert folded.keys[-1] is None
    assert folded.points[0].label == "k28"
    assert folded.points[0].value == 29


def test_line_chart_ignores_sort() -> None:
    chart = _build(MIXED, _spec(sort="value", chart="line"))
    assert chart.kind == "line"
    assert [p.label for p in chart.points] == ["alpha", "bravo", "charlie", "delta", "—"]


def test_date_category_ignores_sort() -> None:
    rows = [
        _row("a", 0, when=date(2026, 1, 5)),
        _row("b", 0, when=date(2026, 3, 2)),
        _row("c", 0, when=date(2026, 3, 9)),
    ]
    chart = _build(rows, _spec(value=(None, "count"), by=WHEN, sort="value", grain="month"))
    assert [p.label for p in chart.points] == ["2026-01", "2026-02", "2026-03"]
    assert [p.value for p in chart.points] == [1, 0, 2]


def test_stacked_series_follow_the_points() -> None:
    rows = [
        _row("A", 1, pos="X"),
        _row("A", 2, pos="Y"),
        _row("B", 10, pos="X"),
        _row("B", 1, pos="Y"),
        _row("C", 4, pos="X"),
        _row("C", 5, pos="Y"),
    ]
    chart = _build(rows, _spec(by2=POS, chart="stacked", sort="value"))
    assert chart.kind == "stacked"
    assert chart.keys == ["B", "C", "A"]
    assert [p.value for p in chart.points] == [11, 9, 3]
    by_label = {s.label: s.values for s in chart.series}
    assert by_label["X"] == [10, 4, 1]
    assert by_label["Y"] == [1, 5, 2]


@pytest.fixture
def sort_report(monkeypatch: pytest.MonkeyPatch) -> None:
    report = Report(
        key=KEY,
        title="Тайлан",
        filters=(),
        columns=(DEPT, POS, AMOUNT),
        default_columns=("dept",),
        rows=lambda user, filters: MIXED,
        group_options=("dept", "pos"),
        layouts=("chart", "board"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)


@pytest.mark.django_db
def test_layout_bar_shows_the_sort_select_for_a_chart_only(
    client: Client, login_as: Callable[..., User], sort_report: None
) -> None:
    login_as(client, "HR")
    chart = client.get(PAGE, {"layout": "chart", "lby": "dept", "lsort": "valueasc"})
    assert chart.context["spec"].layout == "chart"
    content = chart.content.decode()
    assert 'name="lsort"' in content
    assert "Эрэмбэ" in content
    assert '<option value="valueasc" selected>Утгаар өсөх</option>' in content
    assert '<option value="value">Утгаар буурах</option>' in content
    assert '<option value="">Ангилалаар</option>' in content

    board = client.get(PAGE, {"layout": "board", "lby": "dept"})
    assert board.context["spec"].layout == "board"
    assert 'name="lsort"' not in board.content.decode()


DATED_ROWS = [
    _row("alpha", 4, pos="X", when=date(2026, 1, 5)),
    _row("bravo", 9, pos="Y", when=date(2026, 2, 3)),
    _row("alpha", 2, pos="Y", when=date(2026, 2, 9)),
]


@pytest.fixture
def dated_sort_report(monkeypatch: pytest.MonkeyPatch) -> None:
    report = Report(
        key=KEY,
        title="Тайлан",
        filters=(),
        columns=(DEPT, POS, AMOUNT, WHEN),
        default_columns=("dept",),
        rows=lambda user, filters: DATED_ROWS,
        group_options=("dept", "pos"),
        layouts=("chart",),
    )
    monkeypatch.setitem(REPORTS, KEY, report)


@pytest.mark.django_db
def test_sort_select_follows_the_category_not_the_second_one(
    client: Client, login_as: Callable[..., User], dated_sort_report: None
) -> None:
    login_as(client, "HR")
    # a text category stacked by a date second category: the sort applies to the text category, so the select shows
    stacked = client.get(PAGE, {"layout": "chart", "lchart": "stacked", "lby": "dept", "lby2": "when"})
    assert stacked.context["spec"].by.key == "dept"
    assert stacked.context["spec"].by2.key == "when"
    assert 'name="lsort"' in stacked.content.decode()
    # a date category: the sort is a no-op there, so the select is hidden
    dated = client.get(PAGE, {"layout": "chart", "lby": "when"})
    assert dated.context["spec"].by.key == "when"
    assert 'name="lsort"' not in dated.content.decode()
