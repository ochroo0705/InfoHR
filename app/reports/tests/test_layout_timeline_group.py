"""The timeline grouped by a category column (lgroup): groups in label order with the blank last, bars sorted by start
inside a group, counts over every filtered row, the cap over all groups, a hidden column ignored, and the page."""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec, Timeline
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
END = Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")
SECRET = Column(key="secret", label="Нууц", value=lambda r: r.dept, kind="text", needs="macs.view_salary")


def _row(name: str, start: object = None, end: object = None, dept: str = "X") -> Any:
    return SimpleNamespace(name=name, dept=dept, start=start, end=end)


def _spec(group: Column | None = DEPT, year: int | None = None) -> LayoutSpec:
    return LayoutSpec(
        layout="timeline",
        by=START,
        by2=END,
        value=(None, "count"),
        chart="bar",
        month=date(2026, 11, 1),
        group=group,
        year=year,
    )


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


# ---- the groups ----


def test_groups_in_label_order_blank_last() -> None:
    rows = [
        _row("Бат", date(2026, 11, 1), date(2026, 11, 2), dept="gamma"),
        _row("Оюу", date(2026, 11, 1), date(2026, 11, 2), dept="Beta"),
        _row("Дорж", date(2026, 11, 1), date(2026, 11, 2), dept=""),
        _row("Сар", date(2026, 11, 1), date(2026, 11, 2), dept="   "),
        _row("Нар", date(2026, 11, 1), date(2026, 11, 2), dept="alpha"),
    ]
    timeline = _build(rows)
    assert [g.label for g in timeline.groups] == ["alpha", "Beta", "gamma", "—"]
    assert timeline.groups[-1].count == 2  # the blank and the spaces-only row share the «—» group


def test_bars_sorted_by_start_in_a_group() -> None:
    rows = [
        _row("Бат", date(2026, 11, 5), date(2026, 11, 5), dept="A"),
        _row("Оюу", date(2026, 11, 1), date(2026, 11, 9), dept="A"),
        _row("Дорж", date(2026, 11, 1), date(2026, 11, 2), dept="A"),
        _row("Сар", date(2026, 11, 3), date(2026, 11, 3), dept="B"),
    ]
    timeline = _build(rows)
    group_a = timeline.groups[0]
    assert group_a.label == "A"
    assert [bar.item.title for bar in group_a.bars] == ["Дорж", "Оюу", "Бат"]
    assert [bar.item.title for bar in timeline.bars] == ["Дорж", "Оюу", "Бат", "Сар"]


def test_cap_applies_across_groups() -> None:
    first = date(2026, 1, 1)
    depts = ["A", "B", "C"]
    rows = [
        _row(f"Нэр {i}", first + timedelta(days=i), first + timedelta(days=i + 2), dept=depts[i % 3])
        for i in range(120)
    ]
    timeline = _build(rows)
    assert timeline.shown == 100
    assert len(timeline.bars) == 100
    assert [len(g.bars) for g in timeline.groups] == [34, 33, 33]  # the first 100 dated rows, in table order
    assert [g.count for g in timeline.groups] == [40, 40, 40]  # counts cover every row
    assert sum(g.count for g in timeline.groups) == 120
    assert timeline.over_cap == 20


def test_no_group_keeps_row_order_and_flat_bars() -> None:
    rows = [
        _row("Бат", date(2026, 11, 3), date(2026, 11, 5), dept="B"),
        _row("Дорж", date(2026, 11, 1), date(2026, 11, 2), dept="A"),
        _row("Оюу", date(2026, 11, 2), date(2026, 11, 9), dept="A"),
    ]
    timeline = _build(rows, replace(_spec(), group=None))
    assert timeline.groups == []
    assert [bar.item.title for bar in timeline.bars] == ["Бат", "Дорж", "Оюу"]


def test_group_count_includes_undated_and_off_axis_rows() -> None:
    rows = [
        _row("Бат", date(2026, 3, 1), date(2026, 3, 2), dept="A"),
        _row("Оюу", None, None, dept="A"),
        _row("Дорж", date(2025, 6, 1), date(2025, 6, 2), dept="A"),
        _row("Сар", date(2026, 5, 1), date(2026, 5, 2), dept="B"),
    ]
    timeline = _build(rows, _spec(year=2026))
    group_a, group_b = timeline.groups
    assert (group_a.label, group_a.count, len(group_a.bars)) == ("A", 3, 1)
    assert (group_b.label, group_b.count, len(group_b.bars)) == ("B", 1, 1)
    assert timeline.undated == 1
    assert timeline.off_axis == 1


def test_group_with_no_drawn_bar_is_still_listed() -> None:
    rows = [
        _row("Оюу", None, None, dept="A"),
        _row("Сар", date(2026, 5, 1), date(2026, 5, 2), dept="B"),
    ]
    timeline = _build(rows)
    assert [(g.label, g.count, len(g.bars)) for g in timeline.groups] == [("A", 1, 0), ("B", 1, 1)]
    assert [bar.item.title for bar in timeline.bars] == ["Сар"]


def test_groups_listed_when_no_bar_is_drawn() -> None:
    rows = [_row("Оюу", None, None, dept="A"), _row("Бат", None, None, dept="B")]
    timeline = _build(rows)
    assert [(g.label, g.count, g.bars) for g in timeline.groups] == [("A", 1, []), ("B", 1, [])]
    assert timeline.bars == []


# ---- the permission rule: a hidden column is never used ----


class _Viewer:
    def __init__(self, perms: set[str]) -> None:
        self.perms = perms

    def has_perm(self, perm: str) -> bool:
        return perm in self.perms


def _report() -> Report:
    return Report(
        key="timeline-group-unit",
        title="Цагийн тайлан",
        filters=(),
        columns=(NAME, DEPT, START, END, SECRET),
        default_columns=("name", "dept"),
        rows=lambda user, filters: [],
        group_options=("dept", "secret"),
        layouts=("timeline",),
    )


def test_hidden_group_column_is_ignored() -> None:
    report = _report()
    filters = Filters(layout="timeline", lby="start", lby2="end", lgroup="secret")

    hidden = _Viewer(set())
    spec = layouts_mod.resolve(report, hidden, filters, [])
    assert spec.group is None
    assert layouts_mod.layout_choices(report, hidden, "timeline", "start").group == [("dept", "Хэлтэс")]

    allowed = _Viewer({"macs.view_salary"})
    spec = layouts_mod.resolve(report, allowed, filters, [])
    assert spec.group is not None
    assert spec.group.key == "secret"
    keys = [key for key, _ in layouts_mod.layout_choices(report, allowed, "timeline", "start").group]
    assert keys == ["dept", "secret"]


# ---- the page ----

KEY = "timeline-group-test"
PAGE = f"/reports/{KEY}/"


@pytest.fixture
def use_rows(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], None]:
    """Register a report over these rows, with the department as its group column."""

    def _use(rows: list[Any]) -> None:
        report = Report(
            key=KEY,
            title="Цагийн тайлан",
            filters=(),
            columns=(NAME, DEPT, START, END),
            default_columns=("name", "dept"),
            rows=lambda user, filters: rows,
            group_options=("dept",),
            layouts=("board", "timeline"),
        )
        monkeypatch.setitem(REPORTS, KEY, report)

    return _use


def _page_rows() -> list[Any]:
    return [
        _row("Бат", date(2026, 11, 1), date(2026, 11, 3), dept="Санхүү"),
        _row("Оюу", date(2026, 11, 2), date(2026, 11, 4), dept="Санхүү"),
        _row("Дорж", date(2026, 11, 1), date(2026, 11, 2), dept="Худалдаа"),
    ]


def test_group_select_is_offered_for_the_timeline(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows(_page_rows())
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    select = re.search(r'<select name="lgroup".*?</select>', page, re.S)
    assert select is not None
    assert "Бүлэглэх" in page
    assert '<option value="" selected>—</option>' in select.group(0)
    assert '<option value="dept">Хэлтэс</option>' in select.group(0)


def test_group_select_is_not_offered_for_the_board(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows(_page_rows())
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board", "lby": "dept"}).content.decode()
    assert 'name="lgroup"' not in page


def test_group_headings_render_label_and_count(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows(_page_rows())
    login_as(client, "HR")
    address = {"layout": "timeline", "lby": "start", "lby2": "end", "lgroup": "dept", "lyear": "all"}
    page = client.get(PAGE, address).content.decode()
    assert '<div class="w-48 shrink-0 truncate">Санхүү · 2</div>' in page
    assert '<div class="w-48 shrink-0 truncate">Худалдаа · 1</div>' in page
    assert page.index("Санхүү · 2") < page.index("Худалдаа · 1")


def test_ungrouped_timeline_has_no_heading_rows(
    client: Client, login_as: Callable[..., User], use_rows: Callable[[list[Any]], None]
) -> None:
    use_rows(_page_rows())
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert "Санхүү · 2" not in page
    assert 'text-slate-900"><div class="w-48 shrink-0 truncate">' not in page
