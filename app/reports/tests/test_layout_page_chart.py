"""The request-free chart (services.layout_page.chart_page) and the shared drill helper (drill_for): the rows as
finished text, the drawing's numbers (None for a hidden figure), the stacked series, the drill links (none for a
folded, blank grained or colliding key) and the empty chart."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.services import layout_page
from reports.services.layout_page import ChartOut, LinkBase
from reports.table import Table
from reports.types import Column

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
GENDER = Column(key="gender", label="Хүйс", value=lambda r: r.gender, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
LINK = LinkBase(path="/reports/x/", f=Filters(), adds=(), plain=False)
MASKED_NOTE = "3-ээс цөөн мөртэй бүлгийн мөнгөн дүнг нуусан («—»)."


def _rules(href: str) -> str:
    """The decoded rules parameter of a drill address ("" when the address has none)."""
    values = parse_qs(urlsplit(href).query).get("rules", [""])
    return values[0]


@pytest.fixture(autouse=True)
def _min_group(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 3  # the default; set here so the masked tests do not depend on the environment


def _row(dept: Any = None, gender: Any = None, pay: Any = 0, start: Any = None, name: Any = "x") -> Any:
    return SimpleNamespace(name=name, dept=dept, gender=gender, pay=pay, start=start)


def _spec(
    value: tuple[Column | None, str] = (None, "count"),
    by: Column | None = DEPT,
    by2: Column | None = None,
    chart: str = "bar",
    show: str = "",
    grain: str = "",
) -> LayoutSpec:
    return LayoutSpec(
        layout="chart",
        by=by,
        by2=by2,
        value=value,
        chart=chart,
        month=date(2026, 11, 1),
        show=show,
        grain=grain,
    )


def _table(rows: list[Any], spec: LayoutSpec) -> Table:
    columns = [c for c in (NAME, DEPT, GENDER, START, PAY) if c is not None]
    return Table(columns=columns, groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)


def _page(rows: list[Any], spec: LayoutSpec) -> ChartOut:
    table = _table(rows, spec)
    return layout_page.chart_page(table, spec, layout_page.drill_for(table, spec, LINK))


def test_chart_rows_text_money_percent_and_none_dash(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these groups have one or two rows each; the hiding has its own test below
    rows = [
        _row("Санхүү", pay=Decimal("1500000")),
        _row("Ачаа", pay=Decimal("900000")),
        _row("Ачаа", pay=Decimal("100000.5")),
    ]
    money = _page(rows, _spec(value=(PAY, "sum")))
    assert [r.label for r in money.rows] == ["Ачаа", "Санхүү"]
    assert [r.total for r in money.rows] == ["1,000,000.50₮", "1,500,000₮"]
    assert money.values == [1000000.5, 1500000.0]
    assert money.money is True
    assert money.percent is False

    counted = [_row("Санхүү"), _row("Ачаа"), _row("Ачаа")]
    percent = _page(counted, _spec(show="pct"))
    assert percent.percent is True
    assert {r.label: r.total for r in percent.rows} == {"Ачаа": "66.7%", "Санхүү": "33.3%"}


def test_chart_json_null_for_masked_money_and_text_dash() -> None:
    # one row in «Ачаа» is below the 3-row minimum: its money sum is hidden; «Санхүү» has 3 rows and shows
    rows = (
        [_row("Ачаа", pay=900000)] + [_row("Санхүү", pay=100) for _ in range(3)] + [_row(None, pay=5) for _ in range(3)]
    )
    out = _page(rows, _spec(value=(PAY, "sum")))
    by_label = {r.label: r for r in out.rows}
    assert out.labels == ["Ачаа", "Санхүү", "—"]
    assert out.values == [None, 300.0, 15.0]
    assert by_label["Ачаа"].total == "—"
    assert by_label["Санхүү"].total == "300₮"
    assert by_label["—"].total == "15₮"
    assert out.masked is True
    assert out.note == MASKED_NOTE


def test_chart_no_note_when_nothing_is_hidden() -> None:
    out = _page([_row("Ачаа"), _row("Санхүү")], _spec())
    assert out.masked is False
    assert out.note == ""


def test_chart_stacked_series_and_totals_from_all_rows() -> None:
    rows = [
        _row("Санхүү", "Эрэгтэй"),
        _row("Санхүү", "Эрэгтэй"),
        _row("Санхүү", "Эмэгтэй"),
        _row("Ачаа", "Эрэгтэй"),
    ]
    out = _page(rows, _spec(by2=GENDER, chart="stacked"))
    assert out.kind == "stacked"
    assert out.kind_label == "Давхарласан баганан"
    assert out.category_label == "Хэлтэс"
    assert set(out.series_labels) == {"Эрэгтэй", "Эмэгтэй"}
    series = {s.label: s.values for s in out.series}
    cells = {r.label: dict(zip(out.series_labels, r.cells, strict=True)) for r in out.rows}
    assert {r.label: r.total for r in out.rows} == {"Ачаа": "1", "Санхүү": "3"}
    assert series["Эрэгтэй"][out.labels.index("Санхүү")] == 2.0
    assert series["Эмэгтэй"][out.labels.index("Санхүү")] == 1.0
    assert cells["Санхүү"]["Эрэгтэй"] == "2"
    assert cells["Ачаа"]["Эмэгтэй"] == "0"
    # the totals are the row counts of each category, not the sum of its stacks read back from the text
    assert sum(float(r.total) for r in out.rows) == len(rows)


def test_chart_drill_none_for_folded_blank_grain_and_colliding_keys() -> None:
    # colliding keys: «Ачаа» and «ачаа » read the same once folded, so neither links; «Санхүү» links
    rows = [_row("Ачаа"), _row("ачаа "), _row("Санхүү")]
    out = _page(rows, _spec())
    by_label = {r.label: r.href for r in out.rows}
    assert _rules(by_label["Санхүү"]) == '{"op":"and","items":[{"c":"dept","o":"eq","v":"Санхүү"}]}'
    assert by_label["Ачаа"] == ""
    assert by_label["ачаа "] == ""

    # folded: 31 categories, the 30 drawn plus «Бусад» (no key, no link)
    many = [_row(f"D{i:02d}") for i in range(31)]
    folded = _page(many, _spec())
    assert folded.labels[-1] == "Бусад"
    assert folded.hrefs[-1] == ""
    assert _rules(folded.hrefs[0]) == '{"op":"and","items":[{"c":"dept","o":"eq","v":"D00"}]}'

    # blank grained bucket: the dated rows link by their month, the blank «—» bucket does not
    dated = [_row(start=date(2026, 3, 5)), _row(start=None)]
    grained = _page(dated, _spec(by=START, grain="month"))
    by_label = {r.label: r.href for r in grained.rows}
    assert (
        _rules(by_label["2026-03"]) == '{"op":"and","items":[{"c":"start","o":"between","v":"2026-03-01..2026-03-31"}]}'
    )
    assert by_label["—"] == ""


def test_chart_without_category_column_has_empty_hrefs_and_does_not_raise() -> None:
    # no `by` column: every row is the one blank category, and its drill is no link (drill_url gives "")
    out = _page([_row("Санхүү"), _row("Ачаа")], _spec(by=None))
    assert out.labels == ["—"]
    assert out.hrefs == [""]
    assert out.rows[0].href == ""
    assert out.rows[0].total == "2"
    assert out.category_label == "Ангилал"


def test_chart_category_html_stays_verbatim_text() -> None:
    out = _page([_row("<b>Ачаа</b>"), _row("<b>Ачаа</b>")], _spec())
    assert out.labels == ["<b>Ачаа</b>"]
    assert out.rows[0].label == "<b>Ачаа</b>"


def test_chart_empty_rows_has_no_points() -> None:
    out = _page([], _spec())
    assert out.rows == []
    assert out.labels == []
    assert out.values == []
    assert out.series == []
    assert out.hrefs == []
    assert out.masked is False
    assert out.note == ""


def test_drill_for_exposes_collision_sets_and_grained_flags() -> None:
    rows = [_row("Ачаа"), _row("ачаа "), _row(None, gender="Эрэгтэй")]
    spec = _spec(by2=GENDER)
    table = _table(rows, spec)
    drill = layout_page.drill_for(table, spec, LINK)
    assert drill.by_bad == frozenset({"Ачаа", "ачаа "})
    assert drill.by2_bad == frozenset()
    assert drill.by_grained is False
    assert drill.by2_grained is False
    assert drill.unless("Ачаа", drill.by_bad) is None
    assert drill.unless("Санхүү", drill.by_bad) == "Санхүү"
    assert drill.unless("", set(), grained=True) is None
    assert drill([(DEPT, None)]) == ""
    assert _rules(drill([(DEPT, "Санхүү")])) == '{"op":"and","items":[{"c":"dept","o":"eq","v":"Санхүү"}]}'


def test_drill_for_non_category_layout_has_no_collisions() -> None:
    rows = [_row("Ачаа"), _row("ачаа ")]
    spec = LayoutSpec(layout="table", by=DEPT, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1))
    table = _table(rows, spec)
    drill = layout_page.drill_for(table, spec, LINK)
    assert drill.by_bad == frozenset()


def test_chart_pct_values_are_drawn_as_floats_and_none_when_hidden() -> None:
    rows = [_row("Ачаа"), _row("Ачаа"), _row("Санхүү")]
    out = _page(rows, _spec(show="pct"))
    assert out.labels == ["Ачаа", "Санхүү"]
    assert out.values == [66.7, 33.3]
    assert [r.total for r in out.rows] == ["66.7%", "33.3%"]


def test_chart_masked_percent_of_money_is_dash_and_null() -> None:
    rows = [_row("Ачаа", pay=900000), _row("Санхүү", pay=100), _row("Санхүү", pay=100), _row("Санхүү", pay=100)]
    out = _page(rows, _spec(value=(PAY, "sum"), show="pct"))
    assert out.masked is True
    assert out.values == [None, None]
    assert all(r.total == "—" for r in out.rows)
    assert out.money is False
    assert out.note == MASKED_NOTE


@pytest.mark.parametrize(
    ("value", "text"),
    [(6.25, "6.3%"), (0.05, "0.1%"), (34, "34.0%"), (100.0, "100.0%"), (33.333, "33.3%")],
)
def test_chart_percent_tie_cases_round_half_up_one_decimal(value: float, text: str) -> None:
    # the template's rule (floatformat "1u"): one decimal always, a tie goes up, not to the even digit
    assert layout_page._chart_text(value, False, True) == text
