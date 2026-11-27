"""The request-free entry point (services.layout_page.layout_page): one LayoutPage per layout with exactly one
payload set, None for the table, hostile layout parameters that never raise and never show a column the viewer may
not see, and the empty table with zero totals."""

import dataclasses
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.http import QueryDict
from django.utils import timezone

from reports import drill
from reports import layouts as layouts_mod
from reports.filters import MAX_YEAR, MIN_MONTH_YEAR, Filters, parse_filters
from reports.kinds import column_kind
from reports.page_rules import address
from reports.services import layout_page as layout_service
from reports.services.page_head import NEW_LAYOUT_BLANKS
from reports.table import Table, build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

PATH = "/reports/layout-page-test/"
NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
# a column the test viewer may not see: no layout parameter may name it, and its key and label must never come back
SECRET = Column(
    key="secret",
    label="Нууц цалин",
    value=lambda r: r.secret,
    kind="number",
    numeric=True,
    needs="accounts.view_secret",
)
LAYOUTS = ("board", "cards", "calendar", "timeline", "chart", "pivot")
PAYLOADS = ("board", "cards", "calendar", "timeline", "chart", "pivot")
HIDDEN = ("secret", "Нууц цалин")
HOSTILE_PROBES: list[dict[str, str]] = [
    {"lby": "secret"},
    {"lby": "secret", "lby2": "secret", "lval": "secret:sum", "lval2": "secret:sum"},
    {"lmonth": "9999-99"},
    {"lweek": "junk"},
    {"lyear": "0"},
    {"lval": "pay:sum", "lval2": "pay:sum"},
    {"lchart": "pie"},
    {"lby": "x" * 5000, "lby2": "y" * 5000},
    {"lgrain": "junk", "lshow": "junk", "lsort": "junk", "lorder": "junk"},
]


def _rows() -> list[Any]:
    return [
        SimpleNamespace(
            name="Бат", dept="Санхүү", start=date(2026, 11, 3), pay=Decimal("1500000"), secret=Decimal("9")
        ),
        SimpleNamespace(name="Дорж", dept="Санхүү", start=date(2026, 11, 10), pay=Decimal("500"), secret=Decimal("8")),
        SimpleNamespace(
            name="Сараа", dept="Ачаа", start=date(2026, 11, 17), pay=Decimal("900000"), secret=Decimal("7")
        ),
    ]


def _report(rows: list[Any]) -> Report:
    return Report(
        key="layout-page-test",
        title="Тест тайлан",
        filters=(),
        columns=(NAME, DEPT, START, PAY, SECRET),
        default_columns=("name", "dept"),
        rows=lambda user, filters: list(rows),
        layouts=LAYOUTS,
        group_options=("dept",),
        layout_date="start",
    )


def _page(
    user: User,
    rows: list[Any],
    query: dict[str, str],
    adds: list[str] | None = None,
    plain: bool = False,
) -> layout_service.LayoutPage | None:
    return _built(user, rows, query, adds, plain)[1]


def _built(
    user: User,
    rows: list[Any],
    query: dict[str, str],
    adds: list[str] | None = None,
    plain: bool = False,
) -> tuple[Table, layout_service.LayoutPage | None]:
    """The table and the layout page for these query parameters, with the picker chips and the plain flag given."""
    params = QueryDict(urlencode(query))
    report = _report(rows)
    table = build_table(report, user, parse_filters(params))
    return table, layout_service.layout_page(params, PATH, user, report, table, adds or [], plain)


@pytest.fixture
def viewer(django_user_model: type[User]) -> User:
    """A signed-in user with no permissions: the secret column is not theirs."""
    return django_user_model.objects.create_user(username="layout-page-viewer", password=None)


def _strings(node: Any) -> Iterator[str]:
    """Every string in a dataclasses.asdict result, keys included."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list | tuple):
        for item in node:
            yield from _strings(item)


@pytest.mark.parametrize("layout", LAYOUTS)
def test_each_layout_sets_exactly_one_payload(viewer: User, layout: str) -> None:
    page = _page(viewer, _rows(), {"layout": layout})
    assert page is not None
    assert page.kind == layout
    assert page.count == 3
    set_names = [name for name in PAYLOADS if getattr(page, name) is not None]
    assert set_names == [layout]


def test_table_layout_returns_none(viewer: User) -> None:
    assert _page(viewer, _rows(), {}) is None
    assert _page(viewer, _rows(), {"layout": "table"}) is None


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("probe", HOSTILE_PROBES, ids=[str(n) for n in range(len(HOSTILE_PROBES))])
def test_hostile_layout_params_never_raise(viewer: User, layout: str, probe: dict[str, str]) -> None:
    page = _page(viewer, _rows(), {"layout": layout, **probe})
    assert page is not None
    text = list(_strings(dataclasses.asdict(page)))
    for hidden in HIDDEN:
        assert not any(hidden in s for s in text), (layout, probe.keys(), hidden)


def test_empty_table_gives_empty_payloads_with_zero_totals(viewer: User) -> None:
    board = _page(viewer, [], {"layout": "board"})
    assert board is not None and board.board is not None
    assert board.count == 0 and board.board.total == 0 and board.board.lanes == []

    cards = _page(viewer, [], {"layout": "cards"})
    assert cards is not None and cards.cards is not None
    assert cards.cards.items == [] and cards.cards.total == 0 and cards.cards.next_offset is None

    calendar = _page(viewer, [], {"layout": "calendar"})
    assert calendar is not None and calendar.calendar is not None
    assert calendar.calendar.total == 0 and calendar.calendar.undated == 0

    timeline = _page(viewer, [], {"layout": "timeline"})
    assert timeline is not None and timeline.timeline is not None
    assert timeline.timeline.total == 0 and timeline.timeline.undated == 0

    chart = _page(viewer, [], {"layout": "chart"})
    assert chart is not None and chart.chart is not None
    assert chart.chart.rows == [] and chart.chart.values == [] and chart.chart.hrefs == []

    pivot = _page(viewer, [], {"layout": "pivot"})
    assert pivot is not None and pivot.pivot is not None
    grid = pivot.pivot.grids[0]
    assert grid.empty is True and grid.rows == [] and grid.grand == "0"


# The hrefs below are the report's real addresses: each expected string is built by page_rules.address with the same
# filters the view replaces, so a change in the address form or in a link's rule shows here.
ADDS = ["nationality"]  # a picker chip of a column filter the viewer may use


def _link(f: Filters, adds: list[str], plain: bool, **over: Any) -> str:
    return address(PATH, replace(f, **over), adds, plain=plain)


@pytest.mark.parametrize("plain", [False, True])
def test_calendar_month_links_are_the_real_addresses(viewer: User, plain: bool) -> None:
    table, page = _built(viewer, _rows(), {"layout": "calendar", "lmonth": "2025-03"}, ADDS, plain)
    assert page is not None and page.calendar is not None
    cal = page.calendar
    f = table.filters
    assert cal.prev_href == _link(f, ADDS, plain, lmonth="2025-02")
    assert cal.next_href == _link(f, ADDS, plain, lmonth="2025-04")
    assert cal.today_href == _link(f, ADDS, plain, lmonth="")
    # the switch goes to the week of the month's 1st (the month shown is not the current one)
    assert cal.switch_href == _link(
        f, ADDS, plain, lweek=layouts_mod.week_start(date(2025, 3, 1)).isoformat(), lmonth=""
    )
    assert cal.month_value == "2025-03"


@pytest.mark.parametrize("plain", [False, True])
def test_timeline_year_links_are_the_real_addresses(viewer: User, plain: bool) -> None:
    table, page = _built(viewer, _rows(), {"layout": "timeline", "lyear": "2025"}, ADDS, plain)
    assert page is not None and page.timeline is not None
    tl = page.timeline
    f = table.filters
    assert tl.year == 2025
    assert tl.year_prev_href == _link(f, ADDS, plain, lyear="2024")
    assert tl.year_next_href == _link(f, ADDS, plain, lyear="2026")
    assert tl.all_href == _link(f, ADDS, plain, lyear="all")
    enter_year = min(max(timezone.localdate().year, MIN_MONTH_YEAR), MAX_YEAR)
    assert tl.enter_href == _link(f, ADDS, plain, lyear=str(enter_year))


@pytest.mark.parametrize("plain", [False, True])
def test_chart_and_pivot_drill_hrefs_are_the_real_addresses(viewer: User, plain: bool) -> None:
    for query in ({"layout": "chart"}, {"layout": "pivot"}):
        table, page = _built(viewer, _rows(), query, ADDS, plain)
        assert page is not None
        f = table.filters
        kind = column_kind(DEPT, table.rows)
        rules = drill.drill_rules(f.rules, [drill.condition("dept", kind, "Санхүү")])
        expected = address(
            PATH,
            replace(f, rules=rules, layout="", lby="", lby2="", lval="", lchart="", lmonth="", **NEW_LAYOUT_BLANKS),
            ADDS,
            plain=plain,
        )
        if page.chart is not None:
            labels = page.chart.labels
            assert page.chart.hrefs[labels.index("Санхүү")] == expected
        else:
            assert page.pivot is not None
            row = next(r for r in page.pivot.grids[0].rows if r.label == "Санхүү")
            assert row.href == expected
