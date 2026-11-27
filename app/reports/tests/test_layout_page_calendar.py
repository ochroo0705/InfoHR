"""The request-free calendar page (services.layout_page.calendar_page): the month grid and the week view, the arrows at
the year bounds, the «+N» links, the week switch, the month picker's hidden inputs and the entry notes of a yearly
repeat. The link is a stub that records its overrides, so the tests read the filters the page asks for."""

from collections.abc import Callable
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


def _row(name: str, start: object = None, dept: str = "X") -> Any:
    return SimpleNamespace(name=name, dept=dept, start=start)


def _spec(
    month: date = date(2026, 11, 1), week: date | None = None, by: Column | None = START, rep: bool = False
) -> LayoutSpec:
    return LayoutSpec(
        layout="calendar", by=by, by2=None, value=(None, "count"), chart="bar", month=month, week=week, rep=rep
    )


def _table(rows: list[Any], spec: LayoutSpec) -> Table:
    return Table(columns=[NAME, DEPT, START], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)


def _link(calls: list[dict[str, str]], base: dict[str, str] | None = None, adds: tuple[str, ...] = ()) -> Callable:
    """A stub address: records each call's overrides, then returns the base filters with them applied (an empty value
    is dropped, as an empty filter is kept out of an address) and the column filters added."""
    merged = dict(base or {})

    def link(**overrides: str) -> str:
        calls.append(overrides)
        params = {**merged, **overrides}
        query = [(k, v) for k, v in params.items() if v] + [("add", name) for name in adds]
        return "/reports/cal/?" + urlencode(query)

    return link


def _page(
    rows: list[Any],
    spec: LayoutSpec,
    today: date = TODAY,
    base: dict[str, str] | None = None,
    adds: tuple[str, ...] = (),
) -> tuple[layout_page.CalendarOut, list[dict[str, str]]]:
    calls: list[dict[str, str]] = []
    link = _link(calls, base, adds)
    return layout_page.calendar_page(_table(rows, spec), spec, (), today, link), calls


def _param(href: str, name: str) -> str:
    """The value of one query parameter of an address (the stub's output)."""
    return dict(parse_qsl(urlsplit(href).query))[name]


def test_month_arrows_disabled_at_1900_01_and_2100_12() -> None:
    first, _ = _page([], _spec(month=date(1900, 1, 1)))
    assert first.prev_href == ""  # no month before 1900-01
    assert _param(first.next_href, "lmonth") == "1900-02"
    last, _ = _page([], _spec(month=date(2100, 12, 1)))
    assert last.next_href == ""  # no month after 2100-12
    assert _param(last.prev_href, "lmonth") == "2100-11"


def test_week_arrows_disabled_when_prev_or_next_equals_start() -> None:
    first_start = date(1900, 1, 1)
    first, _ = _page([], _spec(week=first_start))
    assert first.mode == "week"
    assert first.prev_href == ""  # the week before is outside the range, so prev stays on the start
    assert _param(first.next_href, "lweek") == (first_start + timedelta(days=7)).isoformat()
    last_start = layouts_mod.week_start(date(2100, 12, 31))
    last, _ = _page([], _spec(week=last_start))
    assert last.next_href == ""  # the week after is outside the range, so next stays on the start
    assert _param(last.prev_href, "lweek") == (last_start - timedelta(days=7)).isoformat()


def test_month_cell_more_href_is_the_week_of_that_day_week_view_more_is_plain() -> None:
    # four entries on Tuesday 10 November: three drawn, one more, linked to the week of that day (Monday 9th)
    rows = [_row(f"Ажилтан {n}", start=date(2026, 11, 10)) for n in range(4)]
    month, _ = _page(rows, _spec())
    cell = next(day for week in month.weeks for day in week if day.iso == "2026-11-10")
    assert cell.more == 1
    assert "lweek=2026-11-09" in cell.more_href
    quiet = next(day for week in month.weeks for day in week if day.iso == "2026-11-11")
    assert quiet.more_href == ""

    # the week view's «+N» is plain: 13 entries on one day give more=1 and no link
    week_rows = [_row(f"Ажилтан {n}", start=date(2026, 11, 10)) for n in range(13)]
    week, _ = _page(week_rows, _spec(week=date(2026, 11, 9)))
    day = next(d for d in week.days if d.iso == "2026-11-10")
    assert day.more == 1
    assert day.more_href == ""


def test_calendar_week_switch_href_anchors_on_today_when_current_month() -> None:
    # November 2026 is the current month: the «7 хоног» link is the week of today (Saturday 7th), Monday the 2nd
    current, calls = _page([], _spec(month=date(2026, 11, 1)))
    assert {"lweek": "2026-11-02", "lmonth": ""} in calls
    assert "lweek=2026-11-02" in current.switch_href
    # another month: the week of its 1st (Tuesday 1 September 2026, Monday 31 August)
    other, calls = _page([], _spec(month=date(2026, 9, 1)))
    assert {"lweek": "2026-08-31", "lmonth": ""} in calls
    assert "lweek=2026-08-31" in other.switch_href


def test_calendar_keep_drops_lmonth_and_carries_adds() -> None:
    base = {"layout": "calendar", "lby": "start", "lmonth": "2025-02"}
    page, _ = _page([], _spec(), base=base, adds=("Хэлтэс",))
    assert page.keep == [("layout", "calendar"), ("lby", "start"), ("add", "Хэлтэс")]
    assert all(name != "lmonth" for name, _ in page.keep)


def test_calendar_entry_note_for_a_repeated_yearly_date() -> None:
    # a birthday-like start from 2020 repeats on 10 November 2026: six years since its start
    spec = _spec(rep=True)
    page, _ = _page([_row("Бат", start=date(2020, 11, 10))], spec)
    day = next(d for week in page.weeks for d in week if d.iso == "2026-11-10")
    assert [(e.title, e.note) for e in day.entries] == [("Бат", "6 жил")]


def test_month_heading_value_and_today_link() -> None:
    page, calls = _page([], _spec(month=date(2026, 11, 1)))
    assert page.heading == "2026 оны 11-р сар"
    assert page.month_value == "2026-11"
    assert page.undated == 0
    assert page.total == 0
    assert {"lmonth": ""} in calls
    assert page.days == []


def test_week_heading_and_today_link_and_month_switch() -> None:
    # the shown week is Monday 26 October to Sunday 1 November; today (7 November) is in the next week
    page, calls = _page([], _spec(week=date(2026, 10, 26)))
    assert page.heading == "2026-10-26 – 2026-11-01"
    assert page.month_value == ""
    assert page.weeks == []
    assert len(page.days) == 7
    assert {"lweek": "2026-11-02", "lmonth": ""} in calls  # today's week, not the shown one
    assert _param(page.today_href, "lweek") == "2026-11-02"
    assert _param(page.prev_href, "lweek") == "2026-10-19"
    assert _param(page.next_href, "lweek") == "2026-11-02"
    # the shown week is in October: the month link names it
    assert _param(page.switch_href, "lmonth") == "2026-10"


def test_empty_table_gives_total_zero_in_both_modes() -> None:
    month, _ = _page([], _spec())
    assert month.total == 0
    assert month.undated == 0
    week, _ = _page([], _spec(week=date(2026, 11, 2)))
    assert week.total == 0
    assert week.undated == 0
