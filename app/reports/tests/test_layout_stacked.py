"""The stacked bar: one stack per value of the second category, totals aggregated from the rows, folding past 7 stacks,
and a plain bar when there is no second category."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from reports import layouts as layouts_mod
from reports.filters import CHARTS, Filters
from reports.layouts import Chart, LayoutSpec
from reports.table import Table
from reports.types import Column

DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
GENDER = Column(key="gender", label="Хүйс", value=lambda r: r.gender, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)


def _row(dept: str, gender: str, pay: object = 0) -> Any:
    return SimpleNamespace(dept=dept, gender=gender, pay=pay)


def _build(rows: list[Any], by2: Column | None = GENDER, value: tuple[Column | None, str] = (None, "count")) -> Chart:
    spec = LayoutSpec(layout="chart", by=DEPT, by2=by2, value=value, chart="stacked", month=date(2026, 11, 1))
    table = Table(columns=[DEPT, GENDER, PAY], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)
    return layouts_mod.build_chart(table, spec)


def test_stacked_is_a_chart_kind() -> None:
    assert "stacked" in CHARTS


def test_series_split_each_category_and_sum_to_its_total() -> None:
    rows = [_row("Ачаа", "Эр"), _row("Ачаа", "Эм"), _row("Ачаа", "Эр"), _row("Санхүү", "Эм")]
    chart = _build(rows)
    assert chart.kind == "stacked"
    assert [p.label for p in chart.points] == ["Ачаа", "Санхүү"]
    assert {s.label: s.values for s in chart.series} == {"Эм": [1, 1], "Эр": [2, 0]}
    totals = [sum(s.values[i] for s in chart.series) for i in range(2)]  # type: ignore[misc]
    assert totals == [p.value for p in chart.points] == [3, 1]


def test_lines_pair_each_category_with_its_series_values() -> None:
    chart = _build([_row("Ачаа", "Эр"), _row("Санхүү", "Эм")])
    assert [(p.label, cells) for p, cells in chart.lines] == [("Ачаа", [0, 1]), ("Санхүү", [1, 0])]


def test_totals_are_aggregated_from_rows_not_added_from_cells(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these tests check other things; the small-group rule has its own tests
    rows = [_row("Ачаа", "Эр", Decimal("100")), _row("Ачаа", "Эм", Decimal("300"))]
    chart = _build(rows, value=(PAY, "avg"))
    assert chart.points[0].value == Decimal("200")  # the average of both rows, not 100 + 300
    assert {s.label: s.values for s in chart.series} == {"Эм": [Decimal("300")], "Эр": [Decimal("100")]}


def test_no_second_category_falls_back_to_a_plain_bar() -> None:
    chart = _build([_row("Ачаа", "Эр")], by2=None)
    assert chart.kind == "bar"
    assert chart.series == []


def test_stacks_past_the_cap_fold_into_one() -> None:
    rows = [_row("Ачаа", f"Хүйс {n:02d}") for n in range(10)]
    chart = _build(rows)
    assert len(chart.series) == layouts_mod.STACK_CAP
    assert chart.series[-1].label == layouts_mod.FOLDED
    assert chart.series[-1].values == [4]  # 10 stacks, 6 drawn as they are, the other 4 share the last one
    assert chart.folded is True
