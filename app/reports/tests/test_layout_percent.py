"""Percent mode of a chart or pivot (lshow: pct, rowpct, colpct): the shares, the None rules, the label, the
templates and the summary that print and Excel use (Task 6)."""

from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.template.loader import render_to_string
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.registry import REPORTS
from reports.summary import summary_of
from reports.table import Table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
POS = Column(key="pos", label="Албан тушаал", value=lambda r: r.pos, kind="text")
AMOUNT = Column(key="amount", label="Тоо дүн", value=lambda r: r.amount, kind="number", numeric=True)
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", money=True, numeric=True)
KEY = "layout-percent-test"
PAGE = f"/reports/{KEY}/"


def _row(name: str, dept: str, pos: str = "X", amount: object = 0, pay: object = None) -> Any:
    return SimpleNamespace(name=name, dept=dept, pos=pos, amount=amount, pay=pay)


def _spec(
    layout: str,
    by: Column = DEPT,
    by2: Column | None = None,
    value: tuple[Column | None, str] = (None, "count"),
    show: str = "pct",
) -> LayoutSpec:
    return LayoutSpec(layout=layout, by=by, by2=by2, value=value, chart="bar", month=date(2026, 11, 1), show=show)


def _table(rows: list[Any], spec: LayoutSpec) -> Table:
    return Table(
        columns=[NAME, DEPT, POS, AMOUNT, PAY],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec,
    )


def _chart(rows: list[Any], spec: LayoutSpec) -> layouts_mod.Chart:
    return layouts_mod.build_chart(_table(rows, spec), spec)


def _pivot(rows: list[Any], spec: LayoutSpec) -> layouts_mod.Pivot:
    return layouts_mod.build_pivot(_table(rows, spec), spec)


# Department A has X once and Y three times (4 rows); B has X twice and Y twice (4 rows). Total 8.
GRID = [
    _row("a1", "A", "X"),
    _row("a2", "A", "Y"),
    _row("a3", "A", "Y"),
    _row("a4", "A", "Y"),
    _row("b1", "B", "X"),
    _row("b2", "B", "X"),
    _row("b3", "B", "Y"),
    _row("b4", "B", "Y"),
]


def test_chart_pct_sums_to_about_100() -> None:
    rows = [_row("a", "A"), _row("b1", "B"), _row("b2", "B"), _row("c1", "C"), _row("c2", "C"), _row("c3", "C")]
    chart = _chart(rows, _spec("chart"))
    assert chart.percent is True
    assert [p.label for p in chart.points] == ["A", "B", "C"]
    assert [p.value for p in chart.points] == [16.7, 33.3, 50.0]
    assert sum(p.value for p in chart.points) == pytest.approx(100.0, abs=0.2)
    assert all(p.money is False for p in chart.points)
    assert chart.value_label == "Тоо (%)"


def test_chart_ignores_row_and_column_percent() -> None:
    """A chart honours only pct: rowpct and colpct draw the plain counts."""
    rows = [_row("a", "A"), _row("b1", "B"), _row("b2", "B")]
    chart = _chart(rows, _spec("chart", show="rowpct"))
    assert chart.percent is False
    assert [p.value for p in chart.points] == [1, 2]
    assert chart.value_label == "Тоо"


def test_pivot_rowpct_each_row_about_100() -> None:
    pivot = _pivot(GRID, _spec("pivot", by2=POS, show="rowpct"))
    assert pivot.percent is True
    assert pivot.row_labels == ["A", "B"]
    assert pivot.col_labels == ["X", "Y"]
    assert pivot.cells == [[25.0, 75.0], [50.0, 50.0]]
    assert pivot.row_totals == [100.0, 100.0]
    assert pivot.col_totals == [37.5, 62.5]  # a column total is its share of the grand total
    assert pivot.grand == 100.0
    for line in pivot.cells:
        assert sum(line) == pytest.approx(100.0, abs=0.2)


def test_pivot_colpct() -> None:
    pivot = _pivot(GRID, _spec("pivot", by2=POS, show="colpct"))
    assert pivot.percent is True
    # X has 3 rows, Y has 5 rows: A/X 1 of 3, B/X 2 of 3, A/Y 3 of 5, B/Y 2 of 5
    assert pivot.cells == [[33.3, 60.0], [66.7, 40.0]]
    assert pivot.col_totals == [100.0, 100.0]
    assert pivot.row_totals == [50.0, 50.0]  # a row total is its share of the grand total
    assert pivot.grand == 100.0


def test_pivot_pct_is_share_of_grand_total() -> None:
    pivot = _pivot(GRID, _spec("pivot", by2=POS, show="pct"))
    assert pivot.cells == [[12.5, 37.5], [25.0, 25.0]]
    assert pivot.row_totals == [50.0, 50.0]
    assert pivot.col_totals == [37.5, 62.5]
    assert pivot.grand == 100.0


def test_zero_total_gives_none_not_an_error() -> None:
    """A sum over a column of zeros has a zero total: every share is None («—»), and nothing raises."""
    rows = [_row("a", "A", "X", amount=0), _row("b", "B", "Y", amount=0)]
    chart = _chart(rows, _spec("chart", value=(AMOUNT, "sum")))
    assert chart.percent is True
    assert [p.value for p in chart.points] == [None, None]
    pivot = _pivot(rows, _spec("pivot", by2=POS, value=(AMOUNT, "sum"), show="rowpct"))
    assert pivot.cells == [[None, None], [None, None]]
    assert pivot.row_totals == [None, None]
    assert pivot.grand is None


def test_masked_group_stays_none() -> None:
    """A money sum with one person in group A (below REPORTS_MIN_GROUP 3) is hidden. The share of B (600 of 700) would
    give A back as 14.3, so every percent of the money sum is None, totals included, and the note stays (masked)."""
    rows = [
        _row("a1", "A", pay=100),
        _row("b1", "B", pay=100),
        _row("b2", "B", pay=200),
        _row("b3", "B", pay=300),
    ]
    chart = _chart(rows, _spec("chart", value=(PAY, "sum")))
    assert chart.masked is True
    assert chart.percent is True
    assert [p.label for p in chart.points] == ["A", "B"]
    assert [p.value for p in chart.points] == [None, None]
    assert [p.money for p in chart.points] == [False, False]


def test_masked_group_in_rowpct_pivot_hides_every_cell_and_total() -> None:
    """Pivot in rowpct: A has one person (masked), B three. Every cell, row total, column total and the grand total is
    None, because each share is taken over a total that includes A's hidden pay."""
    rows = [
        _row("a1", "A", "X", pay=100),
        _row("b1", "B", "X", pay=100),
        _row("b2", "B", "Y", pay=200),
        _row("b3", "B", "Y", pay=300),
    ]
    pivot = _pivot(rows, _spec("pivot", by2=POS, value=(PAY, "sum"), show="rowpct"))
    assert pivot.masked is True
    assert pivot.percent is True
    assert pivot.cells == [[None, None], [None, None]]
    assert pivot.row_totals == [None, None]
    assert pivot.col_totals == [None, None]
    assert pivot.grand is None


def test_money_sum_without_a_masked_group_gives_shares() -> None:
    """Every group has at least 3 people, so nothing is hidden and the money shares are shown: B is 600 of 700 (85.7),
    A is 100 of 700 (14.3) with 3 people too."""
    rows = [
        _row("a1", "A", pay=100),
        _row("a2", "A", pay=0),
        _row("a3", "A", pay=0),
        _row("b1", "B", pay=100),
        _row("b2", "B", pay=200),
        _row("b3", "B", pay=300),
    ]
    chart = _chart(rows, _spec("chart", value=(PAY, "sum")))
    assert chart.masked is False
    assert [p.value for p in chart.points] == [14.3, 85.7]


def test_avg_ignores_percent() -> None:
    """With an average the figures stay as they are and the label has no «(%)»."""
    rows = [
        _row("a1", "A", pay=100),
        _row("a2", "A", pay=200),
        _row("a3", "A", pay=300),
        _row("b1", "B", pay=400),
        _row("b2", "B", pay=500),
        _row("b3", "B", pay=600),
    ]
    chart = _chart(rows, _spec("chart", value=(PAY, "avg")))
    assert chart.percent is False
    assert [p.value for p in chart.points] == [200, 500]
    assert [p.money for p in chart.points] == [True, True]
    assert "(%)" not in chart.value_label
    pivot = _pivot(rows, _spec("pivot", by2=POS, value=(PAY, "avg"), show="rowpct"))
    assert pivot.percent is False
    assert pivot.money is True
    assert "(%)" not in pivot.value_label


def test_excel_summary_with_pct_builds() -> None:
    """The print and Excel summary builds from a percent chart and pivot: the same grid shape as without percent."""
    rows = [_row("a", "A"), _row("b1", "B"), _row("b2", "B"), _row("c1", "C"), _row("c2", "C"), _row("c3", "C")]
    plain = summary_of(_table(rows, _spec("chart", show="")))
    pct = summary_of(_table(rows, _spec("chart")))
    assert plain is not None and pct is not None
    assert plain.head == ["Хэлтэс", "Тоо"]
    assert pct.head == ["Хэлтэс", "Тоо (%)"]
    assert len(pct.lines) == len(plain.lines) == 3
    assert [line[1] for line in pct.lines] == [16.7, 33.3, 50.0]
    assert pct.money is False
    pplain = summary_of(_table(GRID, _spec("pivot", by2=POS, show="")))
    ppct = summary_of(_table(GRID, _spec("pivot", by2=POS, show="rowpct")))
    assert pplain is not None and ppct is not None
    assert ppct.head == pplain.head
    assert len(ppct.lines) == len(pplain.lines) == 2
    assert all(len(a) == len(b) for a, b in zip(ppct.lines, pplain.lines, strict=True))
    assert ppct.foot is not None and pplain.foot is not None
    assert len(ppct.foot) == len(pplain.foot)
    assert ppct.foot[-1] == 100.0


def test_figure_prints_a_percent_and_a_dash_for_none() -> None:
    assert render_to_string("reports/layouts/_figure.html", {"value": 12.5, "percent": True}).strip() == "12.5%"
    assert render_to_string("reports/layouts/_figure.html", {"value": 100.0, "percent": True}).strip() == "100.0%"
    assert render_to_string("reports/layouts/_figure.html", {"value": None, "percent": True}).strip() == "—"
    assert render_to_string("reports/layouts/_figure.html", {"value": 7}).strip() == "7"


def _percent_report(layouts: tuple[str, ...]) -> Report:
    return Report(
        key=KEY,
        title="Тайлан",
        filters=(),
        columns=(NAME, DEPT, POS, AMOUNT),
        default_columns=("name", "dept"),
        rows=lambda user, filters: GRID,
        group_options=("dept", "pos"),
        layouts=layouts,
    )


@pytest.fixture
def percent_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(REPORTS, KEY, _percent_report(("chart", "pivot")))


def test_layout_bar_offers_the_percent_select_per_view(
    client: Client, login_as: Callable[..., User], percent_report: None
) -> None:
    login_as(client, "HR")
    chart = client.get(PAGE, {"layout": "chart", "lby": "dept"}).content.decode()
    assert 'name="lshow"' in chart
    assert ">Нийтийн %</option>" in chart
    assert "Мөрийн %" not in chart
    assert "Баганын %" not in chart
    pivot = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lby2": "pos"}).content.decode()
    assert 'name="lshow"' in pivot
    assert ">Мөрийн %</option>" in pivot
    assert ">Баганын %</option>" in pivot
    table = client.get(PAGE, {"layout": "table"}).content.decode()
    assert 'name="lshow"' not in table


def test_chart_page_prints_the_percent(client: Client, login_as: Callable[..., User], percent_report: None) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "chart", "lby": "dept", "lshow": "pct"})
    assert response.status_code == 200
    assert response.context["chart"].percent is True
    content = response.content.decode()
    assert content.count("50.0%") >= 2  # A and B each have 4 of the 8 rows


def test_pivot_page_row_percent_and_chart_ignores_it(
    client: Client, login_as: Callable[..., User], percent_report: None
) -> None:
    login_as(client, "HR")
    pivot = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lby2": "pos", "lshow": "rowpct"})
    assert pivot.context["pivot"].percent is True
    assert "75.0%" in pivot.content.decode()
    chart = client.get(PAGE, {"layout": "chart", "lby": "dept", "lshow": "rowpct"})
    assert chart.context["chart"].percent is False
    assert "%" not in chart.context["chart"].value_label
