"""The timeline axis: month, quarter and year ticks by the axis length, and the today line."""

from collections.abc import Callable
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec, Timeline
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
END = Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")


def _row(name: str, start: object = None, end: object = None) -> Any:
    return SimpleNamespace(name=name, dept="X", start=start, end=end)


def _spec() -> LayoutSpec:
    return LayoutSpec(layout="timeline", by=START, by2=END, value=(None, "count"), chart="bar", month=date(2026, 11, 1))


def _build(rows: list[Any], today: date = TODAY) -> Timeline:
    spec = _spec()
    table = Table(
        columns=[NAME, DEPT, START, END],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec,
    )
    return layouts_mod.build_timeline(table, spec, (), today)


def test_month_ticks_for_a_short_axis() -> None:
    # 2026-01-10 .. 2026-04-20 is 101 days: the 1st of January is before the axis, so it is not drawn
    timeline = _build([_row("Бат", start=date(2026, 1, 10), end=date(2026, 4, 20))])
    assert [t.label for t in timeline.ticks] == ["2026-02", "2026-03", "2026-04"]
    assert [t.left_pct for t in timeline.ticks] == pytest.approx(
        [21.782178217821784, 49.504950495049506, 80.19801980198021]
    )


def test_quarter_ticks_for_a_long_axis() -> None:
    # 2025-03-15 .. 2027-03-14 is 730 days: quarter starts only
    timeline = _build([_row("Бат", start=date(2025, 3, 15), end=date(2027, 3, 14))])
    assert [t.label for t in timeline.ticks] == [
        "2025 Q2",
        "2025 Q3",
        "2025 Q4",
        "2026 Q1",
        "2026 Q2",
        "2026 Q3",
        "2026 Q4",
        "2027 Q1",
    ]
    by_label = {t.label: t.left_pct for t in timeline.ticks}
    assert by_label["2025 Q2"] == pytest.approx(2.328767123287671)
    assert by_label["2026 Q1"] == pytest.approx(40.0)
    assert by_label["2027 Q1"] == pytest.approx(90.0)


def test_year_ticks_beyond_1500_days() -> None:
    # 2021-06-01 .. 2025-12-31 is 1675 days (the axis is not clipped: 5 years max): January 1st of each year inside it
    timeline = _build([_row("Бат", start=date(2021, 6, 1), end=date(2025, 12, 31))])
    assert timeline.clipped is False
    assert [t.label for t in timeline.ticks] == ["2022", "2023", "2024", "2025"]
    by_label = {t.label: t.left_pct for t in timeline.ticks}
    assert by_label["2022"] == pytest.approx(12.776119402985076)
    assert by_label["2025"] == pytest.approx(78.2089552238806)


def test_today_line_inside_the_axis() -> None:
    timeline = _build([_row("Бат", start=date(2026, 1, 10), end=date(2026, 4, 20))], today=date(2026, 3, 1))
    assert timeline.today_pct == pytest.approx(49.504950495049506)


def test_no_today_line_outside_the_axis() -> None:
    timeline = _build([_row("Бат", start=date(2026, 1, 10), end=date(2026, 4, 20))], today=TODAY)
    assert timeline.today_pct is None


def test_empty_timeline_has_no_ticks() -> None:
    timeline = _build([])
    assert timeline.ticks == []
    assert timeline.today_pct is None


# ---- the page ----

KEY = "timeline-axis-test"
PAGE = f"/reports/{KEY}/"


@pytest.fixture
def use_rows(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], None]:
    """Register a timeline report over these rows: name, dept, start and end (dates)."""

    def _use(rows: list[Any]) -> None:
        report = Report(
            key=KEY,
            title="Цагийн тэнхлэг",
            filters=(),
            columns=(
                Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
                Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
                Column(key="start", label="Эхэлсэн", value=lambda r: r.start, kind="date"),
                Column(key="end", label="Дууссан", value=lambda r: r.end, kind="date"),
            ),
            default_columns=("name", "dept"),
            rows=lambda user, filters: rows,
            layouts=("table", "timeline"),
        )
        monkeypatch.setitem(REPORTS, KEY, report)

    return _use


@pytest.mark.django_db
def test_page_draws_the_today_line_once_per_bar_and_once_in_the_tick_row(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    today = timezone.localdate()
    rows = [
        _row(f"Ажилтан {n:02d}", start=today - timedelta(days=10 + n), end=today + timedelta(days=10 + n))
        for n in range(3)
    ]  # three bars, all on an axis that holds today
    use_rows(rows)
    login_as(client, "HR")
    # lyear=all: the rows are around today and may cross a year end, which the default window would clip
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert page.count("data-bar") == 3
    assert page.count("data-today") == 4  # one per bar, one in the tick row


@pytest.mark.django_db
def test_page_shows_the_tick_labels_and_no_today_line_when_today_is_off_the_axis(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows([_row("Ажилтан 01", start=date(2020, 1, 10), end=date(2020, 4, 20))])
    login_as(client, "HR")
    # lyear=all: the old 5-year axis from the first start (the default is this year's window, see
    # test_layout_timeline_default_year.py)
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert "2020-02" in page
    assert "2020-03" in page
    assert "2020-04" in page
    assert "data-today" not in page
