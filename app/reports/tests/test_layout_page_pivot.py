"""The request-free pivot (services.layout_page.pivot_page): the grid as finished text, the links of the column heads,
the rows, the cells (row and column rules; the row alone without a second category), a second value as a second grid
with the same links, the percent modes, the masked note, the empty table and the escaping of category text."""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.services import layout_page
from reports.services.layout_page import LinkBase, PivotGridOut, PivotOut
from reports.table import Table
from reports.types import Column

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
GENDER = Column(key="gender", label="Хүйс", value=lambda r: r.gender, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
LINK = LinkBase(path="/reports/x/", f=Filters(), adds=(), plain=False)
MASKED_NOTE = "3-ээс цөөн мөртэй бүлгийн мөнгөн дүнг нуусан («—»)."
PAY_SUM = f"Цалин ({layouts_mod.AGG_TEXT['sum']})"


def _rules(href: str) -> list[dict[str, Any]]:
    """The rule items of a drill address ([] when the address has no rules)."""
    values = parse_qs(urlsplit(href).query).get("rules", [""])
    if not values[0]:
        return []
    return json.loads(values[0])["items"]


def _row(dept: Any = None, gender: Any = None, pay: Any = 0, name: Any = "x") -> Any:
    return SimpleNamespace(name=name, dept=dept, gender=gender, pay=pay)


@pytest.fixture(autouse=True)
def _min_group(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 3  # the default; set here so the masked tests do not depend on the environment


def _spec(
    value: tuple[Column | None, str] = (None, "count"),
    by: Column | None = DEPT,
    by2: Column | None = GENDER,
    show: str = "",
    value2: tuple[Column | None, str] | None = None,
) -> LayoutSpec:
    return LayoutSpec(
        layout="pivot",
        by=by,
        by2=by2,
        value=value,
        chart="bar",
        month=date(2026, 11, 1),
        show=show,
        value2=value2,
    )


def _page(rows: list[Any], spec: LayoutSpec) -> PivotOut:
    table = Table(
        columns=[NAME, DEPT, GENDER, PAY], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec
    )
    return layout_page.pivot_page(table, spec, layout_page.drill_for(table, spec, LINK))


def _cells(grid: PivotGridOut) -> dict[str, dict[str, str]]:
    """The cell texts keyed by row label, then by column label."""
    heads = [label for label, _ in grid.col_heads]
    return {r.label: dict(zip(heads, [text for text, _ in r.cells], strict=True)) for r in grid.rows}


def _rows(grid: PivotGridOut) -> dict[str, Any]:
    return {r.label: r for r in grid.rows}


def test_pivot_grid_cells_link_to_row_and_column_rules() -> None:
    rows = [
        _row("Санхүү", "Эрэгтэй"),
        _row("Санхүү", "Эрэгтэй"),
        _row("Санхүү", "Эмэгтэй"),
        _row("Ачаа", "Эрэгтэй"),
    ]
    grid = _page(rows, _spec()).grids[0]
    assert grid.corner_label == "Хэлтэс / Хүйс"
    assert grid.empty is False
    assert grid.masked is False
    assert grid.note == ""
    assert sorted(label for label, _ in grid.col_heads) == ["Эмэгтэй", "Эрэгтэй"]
    by_row = _rows(grid)
    assert _cells(grid)["Санхүү"]["Эрэгтэй"] == "2"
    assert _cells(grid)["Ачаа"]["Эмэгтэй"] == "0"
    assert by_row["Санхүү"].total == "3"
    assert grid.grand == "4"
    assert sum(int(t) for t in grid.col_totals) == 4

    # the row links by its dept alone; the cell by its dept and gender; the column head by its gender alone
    assert _rules(by_row["Санхүү"].href) == [{"c": "dept", "o": "eq", "v": "Санхүү"}]
    head = dict(grid.col_heads)
    assert _rules(head["Эрэгтэй"]) == [{"c": "gender", "o": "eq", "v": "Эрэгтэй"}]
    cell_href = dict(zip([label for label, _ in grid.col_heads], [h for _, h in by_row["Санхүү"].cells], strict=True))
    assert _rules(cell_href["Эрэгтэй"]) == [
        {"c": "dept", "o": "eq", "v": "Санхүү"},
        {"c": "gender", "o": "eq", "v": "Эрэгтэй"},
    ]


def test_pivot_without_second_category_cell_links_to_the_row() -> None:
    rows = [_row("Санхүү"), _row("Санхүү"), _row("Ачаа")]
    grid = _page(rows, _spec(by2=None)).grids[0]
    assert grid.corner_label == "Хэлтэс"
    assert len(grid.col_heads) == 1
    assert grid.col_heads[0][1] == ""  # the one column has no rule of its own
    row = _rows(grid)["Санхүү"]
    assert row.href != ""
    assert row.cells == [("2", row.href)]
    assert row.total == "2"


def test_pivot_second_value_gives_two_grids_same_links(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these groups have one row each; the hiding has its own test below
    rows = [
        _row("Санхүү", "Эрэгтэй", pay=Decimal("1500000")),
        _row("Санхүү", "Эмэгтэй", pay=Decimal("500")),
        _row("Ачаа", "Эрэгтэй", pay=Decimal("100000.5")),
    ]
    out = _page(rows, _spec(value2=(PAY, "sum")))
    assert len(out.grids) == 2
    first, second = out.grids
    assert first.caption == layouts_mod.AGG_TEXT["count"]
    assert second.caption == PAY_SUM
    assert _cells(second)["Санхүү"]["Эрэгтэй"] == "1,500,000₮"
    assert [r.href for r in first.rows] == [r.href for r in second.rows]
    assert [[h for _, h in r.cells] for r in first.rows] == [[h for _, h in r.cells] for r in second.rows]
    assert first.col_heads == second.col_heads
    assert first.corner_label == second.corner_label


def test_pivot_percent_modes_text() -> None:
    rows = [
        _row("Санхүү", "Эрэгтэй"),
        _row("Санхүү", "Эрэгтэй"),
        _row("Санхүү", "Эмэгтэй"),
        _row("Ачаа", "Эрэгтэй"),
    ]
    pct = _page(rows, _spec(show="pct")).grids[0]
    assert _cells(pct)["Санхүү"]["Эрэгтэй"] == "50.0%"
    assert _cells(pct)["Санхүү"]["Эмэгтэй"] == "25.0%"
    assert _cells(pct)["Ачаа"]["Эрэгтэй"] == "25.0%"
    assert pct.grand == "100.0%"

    rowpct = _page(rows, _spec(show="rowpct")).grids[0]
    assert _cells(rowpct)["Санхүү"]["Эрэгтэй"] == "66.7%"
    assert _cells(rowpct)["Санхүү"]["Эмэгтэй"] == "33.3%"
    assert _cells(rowpct)["Ачаа"]["Эрэгтэй"] == "100.0%"
    assert _rows(rowpct)["Санхүү"].total == "100.0%"

    colpct = _page(rows, _spec(show="colpct")).grids[0]
    assert _cells(colpct)["Санхүү"]["Эрэгтэй"] == "66.7%"
    assert _cells(colpct)["Ачаа"]["Эрэгтэй"] == "33.3%"
    assert _cells(colpct)["Санхүү"]["Эмэгтэй"] == "100.0%"
    assert colpct.col_totals == ["100.0%", "100.0%"]


def test_pivot_masked_money_note_and_dash() -> None:
    # «Ачаа» has one row (under the 3-row minimum): its money is hidden in its cell and its total
    rows = [_row("Ачаа", "Эрэгтэй", pay=900000)] + [_row("Санхүү", "Эрэгтэй", pay=100) for _ in range(3)]
    grid = _page(rows, _spec(value=(PAY, "sum"))).grids[0]
    assert grid.masked is True
    assert grid.note == MASKED_NOTE
    assert _cells(grid)["Ачаа"]["Эрэгтэй"] == "—"
    assert _rows(grid)["Ачаа"].total == "—"
    assert _cells(grid)["Санхүү"]["Эрэгтэй"] == "300₮"


def test_pivot_colliding_keys_get_no_link() -> None:
    # «Ачаа» and «ачаа » read the same once folded, so neither row links and their cells do not either
    rows = [_row("Ачаа", "Эрэгтэй"), _row("ачаа ", "Эрэгтэй"), _row("Санхүү", "Эрэгтэй")]
    grid = _page(rows, _spec()).grids[0]
    by_row = _rows(grid)
    assert by_row["Ачаа"].href == ""
    assert by_row["ачаа "].href == ""
    assert all(href == "" for _, href in by_row["Ачаа"].cells)
    assert _rules(by_row["Санхүү"].href) == [{"c": "dept", "o": "eq", "v": "Санхүү"}]
    assert _rules(by_row["Санхүү"].cells[0][1]) == [
        {"c": "dept", "o": "eq", "v": "Санхүү"},
        {"c": "gender", "o": "eq", "v": "Эрэгтэй"},
    ]


def test_pivot_html_in_row_label_stays_text() -> None:
    grid = _page([_row("<b>Ачаа</b>", "Эрэгтэй"), _row("<b>Ачаа</b>", "Эрэгтэй")], _spec()).grids[0]
    assert [r.label for r in grid.rows] == ["<b>Ачаа</b>"]
    assert grid.rows[0].cells[0][0] == "2"


def test_pivot_empty_table_is_empty_and_does_not_raise() -> None:
    out = _page([], _spec())
    assert len(out.grids) == 1
    grid = out.grids[0]
    assert grid.empty is True
    assert grid.rows == []
    assert grid.masked is False
    assert grid.note == ""

    two = _page([], _spec(value2=(PAY, "sum")))
    assert [g.empty for g in two.grids] == [True, True]


@pytest.mark.parametrize(
    ("value", "text"),
    [(6.25, "6.3%"), (0.05, "0.1%"), (34, "34.0%"), (100.0, "100.0%"), (33.333, "33.3%")],
)
def test_pivot_percent_tie_cases_round_half_up_one_decimal(value: float, text: str) -> None:
    # the template's rule (floatformat "1u"): one decimal always, a tie goes up, not to the even digit
    assert layout_page._chart_text(value, False, True) == text
