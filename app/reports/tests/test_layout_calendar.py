"""The calendar: entries on their days, the «+N» cap, undated rows, Monday-first weeks, month arrows and entry spans."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import Calendar, Day, LayoutSpec
from reports.table import Table
from reports.types import Column

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


def _day(cal: Calendar, day: date) -> Day:
    for week in cal.weeks:
        for cell in week:
            if cell.day == day:
                return cell
    raise AssertionError(f"{day} is not in the grid")


def _titles(cal: Calendar, day: date) -> list[str]:
    return [item.title for item in _day(cal, day).items]


def test_item_appears_on_its_start_day() -> None:
    rows = [_row("Бат", start=date(2026, 11, 7))]
    cal = _build(rows, _spec())
    assert _titles(cal, date(2026, 11, 7)) == ["Бат"]
    assert _day(cal, date(2026, 11, 7)).more == 0
    assert _titles(cal, date(2026, 11, 8)) == []


def test_four_items_on_one_day_show_three_and_more_is_one() -> None:
    rows = [_row(f"Нэр {i}", start=date(2026, 11, 10)) for i in range(4)]
    cal = _build(rows, _spec())
    day = _day(cal, date(2026, 11, 10))
    assert len(day.items) == 3
    assert day.more == 1
    assert [item.title for item in day.items] == ["Нэр 0", "Нэр 1", "Нэр 2"]


def test_blank_dates_are_counted_as_undated_and_placed_nowhere() -> None:
    rows = [_row("Бат", start=None), _row("Дорж", start=""), _row("Оюу", start=date(2026, 11, 2))]
    cal = _build(rows, _spec())
    assert cal.undated == 2
    assert _titles(cal, date(2026, 11, 2)) == ["Оюу"]
    assert all(not day.items for week in cal.weeks for day in week if day.day != date(2026, 11, 2))


def test_february_2026_has_five_monday_first_weeks_of_seven_days() -> None:
    cal = _build([], _spec(month=date(2026, 2, 1)))
    assert cal.month == date(2026, 2, 1)
    assert len(cal.weeks) == 5
    assert all(len(week) == 7 for week in cal.weeks)
    assert cal.weeks[0][0].day == date(2026, 1, 26)
    assert cal.weeks[0][0].day.weekday() == 0
    assert cal.weeks[-1][-1].day == date(2026, 3, 1)
    in_month = [day.day for week in cal.weeks for day in week if day.in_month]
    assert len(in_month) == 28
    assert in_month[0] == date(2026, 2, 1)
    assert in_month[-1] == date(2026, 2, 28)


def test_in_month_flags_only_the_days_of_the_month() -> None:
    cal = _build([], _spec(month=date(2026, 11, 1)))
    flags = {day.day: day.in_month for week in cal.weeks for day in week}
    assert flags[date(2026, 11, 1)] is True
    assert flags[date(2026, 11, 30)] is True
    assert flags[date(2026, 10, 31)] is False
    assert flags[date(2026, 12, 1)] is False


def test_prev_and_next_cross_the_year_boundary() -> None:
    cal = _build([], _spec(month=date(2026, 1, 1)))
    assert cal.prev == "2025-12"
    assert cal.next == "2026-02"
    december = _build([], _spec(month=date(2026, 12, 1)))
    assert december.next == "2027-01"
    assert december.prev == "2026-11"


def test_multi_day_entry_appears_on_each_day_it_spans() -> None:
    rows = [_row("Бат", start=date(2026, 11, 5), end=date(2026, 11, 8))]
    cal = _build(rows, _spec(by2=END))
    shown = [day.day for week in cal.weeks for day in week if any(i.title == "Бат" for i in day.items)]
    assert shown == [date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 8)]


def test_multi_day_entry_without_end_column_is_on_its_start_day_only() -> None:
    rows = [_row("Бат", start=date(2026, 11, 5), end=date(2026, 11, 8))]
    cal = _build(rows, _spec(by2=None))
    assert _titles(cal, date(2026, 11, 5)) == ["Бат"]
    assert _titles(cal, date(2026, 11, 6)) == []


def test_end_before_start_is_a_single_day_entry() -> None:
    rows = [_row("Бат", start=date(2026, 11, 9), end=date(2026, 11, 4))]
    cal = _build(rows, _spec(by2=END))
    assert _titles(cal, date(2026, 11, 9)) == ["Бат"]
    assert _titles(cal, date(2026, 11, 4)) == []


def test_entry_days_are_capped_at_62_days() -> None:
    start = date(2026, 11, 1)
    days = layouts_mod.entry_days(start, start + timedelta(days=399))
    assert len(days) == 62
    assert days[0] == start
    assert days[-1] == start + timedelta(days=61)


def test_long_entry_on_the_grid_does_not_break_and_shows_on_its_grid_days() -> None:
    rows = [_row("Бат", start=date(2026, 9, 1), end=date(2027, 10, 1))]
    cal = _build(rows, _spec(by2=END, month=date(2026, 11, 1)))
    shown = [day.day for week in cal.weeks for day in week if any(i.title == "Бат" for i in day.items)]
    # the entry is capped at 62 days from 1 Sep, which is 1 Nov: the grid shows its days from the grid start to 1 Nov
    assert shown[0] == date(2026, 10, 26)
    assert shown[-1] == date(2026, 11, 1)
    assert len(shown) == 7


def test_datetime_values_are_accepted_on_their_date() -> None:
    rows = [_row("Бат", start=datetime(2026, 11, 7, 9, 30), end=datetime(2026, 11, 8, 17, 0))]
    cal = _build(rows, _spec(by2=END))
    assert _titles(cal, date(2026, 11, 7)) == ["Бат"]
    assert _titles(cal, date(2026, 11, 8)) == ["Бат"]
    assert cal.undated == 0


def test_no_rows_gives_an_empty_grid_with_no_undated() -> None:
    cal = _build([], _spec())
    assert cal.undated == 0
    assert all(not day.items and day.more == 0 for week in cal.weeks for day in week)


def test_no_date_column_counts_every_row_as_undated() -> None:
    rows = [_row("Бат", start=date(2026, 11, 7)), _row("Дорж", start=date(2026, 11, 8))]
    cal = _build(rows, _spec(by=None))
    assert cal.undated == 2
    assert all(not day.items for week in cal.weeks for day in week)


def test_month_outside_the_bounds_is_kept_inside_them() -> None:
    cal = _build([], _spec(month=date(2100, 12, 1)))
    assert cal.month.year == 2100
    assert len(cal.weeks) in (4, 5, 6)
    cal = _build([], _spec(month=date(1900, 1, 1)))
    assert cal.month == date(1900, 1, 1)
    assert cal.prev == "1900-01"


def test_next_arrow_at_2100_stays_at_2100_12() -> None:
    cal = _build([], _spec(month=date(2100, 12, 1)))
    assert cal.next == "2100-12"
    assert cal.prev == "2100-11"


def test_prev_arrow_at_1900_stays_at_1900_01() -> None:
    cal = _build([], _spec(month=date(1900, 1, 1)))
    assert cal.prev == "1900-01"
    assert cal.next == "1900-02"


def test_non_date_values_are_undated_and_do_not_crash() -> None:
    rows = [
        _row("Текст", start="2026-11-07"),
        _row("Үнэн", start=True),
        _row("Тоо", start=5),
        _row("Огноо", start=date(2026, 11, 9)),
    ]
    cal = _build(rows, _spec())
    assert cal.undated == 3
    assert _titles(cal, date(2026, 11, 9)) == ["Огноо"]
    assert all(not day.items for week in cal.weeks for day in week if day.day != date(2026, 11, 9))


def test_non_date_end_values_make_a_one_day_entry() -> None:
    rows = [
        _row("Текст", start=date(2026, 11, 7), end="2026-11-09"),
        _row("Үнэн", start=date(2026, 11, 7), end=True),
        _row("Тоо", start=date(2026, 11, 7), end=5),
    ]
    cal = _build(rows, _spec(by2=END))
    assert cal.undated == 0
    assert _titles(cal, date(2026, 11, 7)) == ["Текст", "Үнэн", "Тоо"]
    assert _titles(cal, date(2026, 11, 8)) == []
