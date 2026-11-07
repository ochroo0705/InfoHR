"""The timeline: bars in row order, missing or reversed ends, the 100-row cap, the 5-year axis, bar percentages."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec, Timeline
from reports.table import Table
from reports.types import Column

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


def test_bars_follow_the_row_order() -> None:
    rows = [
        _row("Бат", start=date(2026, 11, 3), end=date(2026, 11, 5)),
        _row("Дорж", start=date(2026, 11, 1), end=date(2026, 11, 2)),
        _row("Оюу", start=date(2026, 11, 2), end=date(2026, 11, 9)),
    ]
    timeline = _build(rows)
    assert [bar.item.title for bar in timeline.bars] == ["Бат", "Дорж", "Оюу"]


def test_missing_end_is_a_one_day_marker() -> None:
    timeline = _build([_row("Бат", start=date(2026, 11, 4), end=None)])
    bar = timeline.bars[0]
    assert bar.start == date(2026, 11, 4)
    assert bar.end == date(2026, 11, 4)


def test_end_before_start_is_fixed_to_one_day_at_start() -> None:
    timeline = _build([_row("Бат", start=date(2026, 11, 10), end=date(2026, 11, 5))])
    bar = timeline.bars[0]
    assert bar.start == date(2026, 11, 10)
    assert bar.end == date(2026, 11, 10)


def test_no_end_column_makes_every_bar_a_one_day_marker() -> None:
    timeline = _build([_row("Бат", start=date(2026, 11, 4), end=date(2026, 11, 9))], _spec(by2=None))
    assert timeline.bars[0].end == timeline.bars[0].start


def test_cap_of_100_bars_and_total_counts_all_rows() -> None:
    first = date(2026, 1, 1)
    rows = [_row(f"Нэр {i}", start=first + timedelta(days=i), end=first + timedelta(days=i + 2)) for i in range(120)]
    timeline = _build(rows)
    assert len(timeline.bars) == 100
    assert timeline.total == 120
    assert timeline.bars[0].item.title == "Нэр 0"
    assert timeline.bars[-1].item.title == "Нэр 99"


def test_axis_is_clipped_to_five_years_from_the_first_start() -> None:
    rows = [_row("Бат", start=date(2000, 1, 1), end=date(2000, 2, 1)), _row("Дорж", start=date(2030, 1, 1))]
    timeline = _build(rows)
    assert timeline.clipped is True
    assert timeline.first == date(2000, 1, 1)
    assert timeline.last == date(2005, 1, 1)
    assert [bar.item.title for bar in timeline.bars] == ["Бат"]
    assert timeline.off_axis == 1
    assert timeline.shown == 1
    assert timeline.cap == 100


def test_row_starting_after_the_clipped_axis_is_not_drawn_and_counted_off_axis() -> None:
    rows = [
        _row("Бат", start=date(2000, 1, 1)),
        _row("Дорж", start=date(2030, 1, 1)),
        _row("Оюу", start=date(2001, 1, 1)),
    ]
    timeline = _build(rows)
    assert [bar.item.title for bar in timeline.bars] == ["Бат", "Оюу"]
    assert timeline.off_axis == 1
    assert timeline.total == 3


def test_axis_is_worked_out_from_the_drawn_rows_only() -> None:
    first = date(2026, 1, 1)
    rows = [_row(f"Нэр {i}", start=first + timedelta(days=i), end=first + timedelta(days=i + 2)) for i in range(100)]
    rows.append(_row("Хойно", start=date(2030, 1, 1)))
    timeline = _build(rows)
    assert timeline.clipped is False
    assert timeline.first == first
    assert timeline.last == first + timedelta(days=101)
    assert timeline.off_axis == 0
    assert timeline.shown == 100
    assert timeline.total == 101
    assert all(bar.item.title != "Хойно" for bar in timeline.bars)


def test_non_date_start_values_are_undated_and_do_not_crash() -> None:
    rows = [_row("Текст", start="2026-11-05"), _row("Үнэн", start=True), _row("Тоо", start=5)]
    timeline = _build(rows)
    assert timeline.undated == 3
    assert timeline.bars == []
    assert timeline.first is None


def test_non_date_end_values_make_a_one_day_bar() -> None:
    rows = [
        _row("Текст", start=date(2026, 11, 5), end="2026-11-09"),
        _row("Үнэн", start=date(2026, 11, 5), end=True),
        _row("Тоо", start=date(2026, 11, 5), end=5),
    ]
    timeline = _build(rows)
    assert timeline.undated == 0
    assert [(bar.start, bar.end) for bar in timeline.bars] == [(date(2026, 11, 5), date(2026, 11, 5))] * 3


def test_axis_is_not_clipped_within_five_years() -> None:
    rows = [_row("Бат", start=date(2026, 1, 1), end=date(2026, 6, 1))]
    timeline = _build(rows)
    assert timeline.clipped is False
    assert timeline.first == date(2026, 1, 1)
    assert timeline.last == date(2026, 6, 1)


def test_all_dates_blank_gives_no_bars_and_counts_undated() -> None:
    timeline = _build([_row("Бат", start=None), _row("Дорж", start="")])
    assert timeline.bars == []
    assert timeline.first is None
    assert timeline.last is None
    assert timeline.undated == 2
    assert timeline.total == 2


def test_blank_start_is_counted_and_skipped_among_dated_rows() -> None:
    rows = [_row("Бат", start=None), _row("Дорж", start=date(2026, 11, 2), end=date(2026, 11, 4))]
    timeline = _build(rows)
    assert timeline.undated == 1
    assert [bar.item.title for bar in timeline.bars] == ["Дорж"]


def test_bar_percentages_stay_within_the_axis_and_are_at_least_half_a_percent() -> None:
    rows = [
        _row("Бат", start=date(2000, 1, 1), end=date(2000, 1, 2)),
        _row("Дорж", start=date(2000, 6, 1), end=date(2000, 6, 1)),
        _row("Оюу", start=date(2030, 1, 1), end=date(2031, 1, 1)),
        _row("Номин", start=date(2004, 12, 31), end=date(2030, 1, 1)),
    ]
    timeline = _build(rows)
    assert timeline.clipped is True
    for bar in timeline.bars:
        assert 0.0 <= bar.left_pct <= 100.0
        assert bar.width_pct >= 0.5
        assert bar.left_pct + bar.width_pct <= 100.0 + 1e-9


def test_single_day_axis_gives_a_full_width_marker() -> None:
    timeline = _build([_row("Бат", start=date(2026, 11, 4), end=None)])
    bar = timeline.bars[0]
    assert bar.left_pct == 0.0
    assert bar.width_pct == 100.0
    assert bar.left_pct + bar.width_pct <= 100.0 + 1e-9


def test_datetime_values_are_accepted_as_their_date() -> None:
    timeline = _build([_row("Бат", start=datetime(2026, 11, 2, 8, 0), end=datetime(2026, 11, 4, 17, 0))])
    bar = timeline.bars[0]
    assert bar.start == date(2026, 11, 2)
    assert bar.end == date(2026, 11, 4)


def test_no_rows_gives_an_empty_timeline() -> None:
    timeline = _build([])
    assert timeline.bars == []
    assert timeline.first is None
    assert timeline.total == 0
    assert timeline.clipped is False
