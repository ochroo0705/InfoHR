"""The request-free timeline page (services.layout_page.timeline_page): the year window arrows at the bounds, «Бүгд» and
«Он» links, bar texts and plain-number percentages, the notes' counts, groups and the empty table. The link is a stub
that records its overrides, so the tests read the filters the page asks for."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.services import layout_page
from reports.table import Table
from reports.types import Column

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
END = Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")


def _row(name: str, start: object = None, end: object = None, dept: str = "X") -> Any:
    return SimpleNamespace(name=name, dept=dept, start=start, end=end)


def _spec(group: Column | None = None, year: int | None = None, all_years: bool = False) -> LayoutSpec:
    return replace(
        LayoutSpec(layout="timeline", by=START, by2=END, value=(None, "count"), chart="bar", month=date(2026, 11, 1)),
        group=group,
        year=year,
        all_years=all_years,
    )


def _table(rows: list[Any], spec: LayoutSpec) -> Table:
    return Table(columns=[NAME, DEPT, START, END], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)


def _link(calls: list[dict[str, str]]) -> Callable[..., str]:
    """A stub address: records each call's overrides and returns them as the query of the report address."""

    def link(**overrides: str) -> str:
        calls.append(overrides)
        query = [(k, v) for k, v in overrides.items() if v]
        return "/reports/tl/?" + urlencode(query)

    return link


def _page(
    rows: list[Any], spec: LayoutSpec, today: date = TODAY
) -> tuple[layout_page.TimelineOut, list[dict[str, str]]]:
    calls: list[dict[str, str]] = []
    out = layout_page.timeline_page(_table(rows, spec), spec, (), today, _link(calls))
    return out, calls


def _param(href: str, name: str) -> str:
    """The value of one query parameter of an address (the stub's output)."""
    return dict(parse_qsl(urlsplit(href).query))[name]


def test_timeline_year_window_arrows_stop_at_bounds_and_all_link_sets_lyear_all() -> None:
    rows = [_row("A", date(2026, 3, 1), date(2026, 3, 5))]
    middle, calls = _page(rows, _spec(year=2026))
    assert middle.year == 2026
    assert _param(middle.year_prev_href or "", "lyear") == "2025"
    assert _param(middle.year_next_href or "", "lyear") == "2027"
    assert _param(middle.all_href, "lyear") == "all"
    assert {"lyear": "all"} in calls
    first, _ = _page(rows, _spec(year=1900))
    assert first.year_prev_href is None  # no year before 1900
    assert first.year_next_href is not None
    last, _ = _page(rows, _spec(year=2100))
    assert last.year_next_href is None  # no year after 2100
    assert last.year_prev_href is not None
    bare, _ = _page(rows, _spec(all_years=True))
    assert bare.year is None  # «Бүгд»: no window, so no arrows
    assert bare.year_prev_href is None and bare.year_next_href is None


def test_timeline_enter_year_clamped_to_allowed_years() -> None:
    rows = [_row("A", date(2026, 3, 1), date(2026, 3, 5))]
    inside, _ = _page(rows, _spec(), today=date(2026, 11, 7))
    assert _param(inside.enter_href, "lyear") == "2026"
    high, _ = _page(rows, _spec(), today=date(2150, 1, 1))
    assert _param(high.enter_href, "lyear") == "2100"
    low, _ = _page(rows, _spec(), today=date(1800, 1, 1))
    assert _param(low.enter_href, "lyear") == "1900"


def test_timeline_bar_percentages_are_plain_numbers() -> None:
    rows = [_row("Анна", date(2026, 1, 1), date(2026, 1, 3)), _row("Бат", date(2026, 1, 4), date(2026, 1, 10))]
    out, _ = _page(rows, _spec())
    bars = out.groups[0].bars
    assert len(bars) == 2
    for bar in bars:
        assert isinstance(bar.left_pct, float)
        assert isinstance(bar.width_pct, float)
        assert "," not in str(bar.left_pct)
        assert "," not in str(bar.width_pct)
    assert bars[1].left_pct > bars[0].left_pct


def test_timeline_bar_texts_are_the_aria_label_and_the_tip() -> None:
    rows = [_row("Анна", date(2026, 3, 1), date(2026, 3, 10))]
    out, _ = _page(rows, _spec())
    bar = out.groups[0].bars[0]
    assert bar.title == "Анна"
    assert bar.label == "Анна: 2026-03-01 – 2026-03-10"
    assert bar.tip_title == "Анна"
    assert bar.tip == "2026-03-01 – 2026-03-10 · 10 өдөр"
    assert out.first == "2026-03-01" and out.last == "2026-03-10"


def test_timeline_notes_counts_over_cap_off_axis_undated_clipped() -> None:
    cap = layouts_mod.TIMELINE_CAP
    # one drawn row, one drawn row far past the 5-year axis (off the axis, clipped), one undated row
    rows = [
        _row("A", date(2026, 1, 1), date(2026, 1, 10)),
        _row("Far", date(2040, 1, 1), date(2040, 1, 5)),
        _row("None"),
    ]
    out, _ = _page(rows, _spec())
    assert out.total == 3
    assert out.undated == 1
    assert out.off_axis == 1
    assert out.clipped is True
    assert out.over_cap == 0
    assert out.cap == cap
    # 102 dated rows in one year: the first 100 are drawn and the other 2 are over the cap
    many = [_row(f"R{i}", date(2026, 1, 1) + timedelta(days=i % 30), date(2026, 1, 2)) for i in range(102)]
    capped, _ = _page(many, _spec())
    assert capped.total == 102
    assert capped.over_cap == 2
    assert capped.off_axis == 0
    assert capped.clipped is False


def test_timeline_grouped_by_column_gives_one_group_per_label_with_counts() -> None:
    rows = [
        _row("A", date(2026, 1, 1), date(2026, 1, 2), dept="Ст"),
        _row("B", date(2026, 1, 3), date(2026, 1, 4), dept="Бүх"),
        _row("C", date(2026, 1, 5), date(2026, 1, 6), dept="Ст"),
    ]
    out, _ = _page(rows, _spec(group=DEPT))
    counts = {group.label: group.count for group in out.groups}
    assert counts == {"Бүх": 1, "Ст": 2}
    staff = next(group for group in out.groups if group.label == "Ст")
    assert [bar.title for bar in staff.bars] == ["A", "C"]


def test_timeline_ungrouped_is_one_unnamed_group_with_every_bar() -> None:
    rows = [_row("A", date(2026, 1, 1), date(2026, 1, 2)), _row("B", date(2026, 1, 3), date(2026, 1, 4))]
    out, _ = _page(rows, _spec())
    assert len(out.groups) == 1
    assert out.groups[0].label == ""
    assert out.groups[0].count == 2
    assert [bar.title for bar in out.groups[0].bars] == ["A", "B"]


def test_timeline_empty_table_has_total_zero_and_does_not_raise() -> None:
    out, _ = _page([], _spec())
    assert out.total == 0
    assert out.first == "" and out.last == ""
    assert out.ticks == []
    assert out.today_pct is None
    assert out.undated == 0 and out.off_axis == 0 and out.over_cap == 0
    assert out.clipped is False
    assert len(out.groups) == 1 and out.groups[0].bars == []
    grouped, _ = _page([], _spec(group=DEPT))
    assert grouped.total == 0
    assert grouped.groups == []
