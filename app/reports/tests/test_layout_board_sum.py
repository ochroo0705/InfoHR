"""Board lane sums: the «Утга» value adds each lane's figure over every row of the lane; the cap limits cards only."""

import re
from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters, parse_filters
from reports.layouts import LayoutSpec
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

TODAY = date(2026, 11, 7)
KEY = "board-sum-test"
PAGE = f"/reports/{KEY}/"

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
NUM = Column(key="num", label="Тоо хэмжээ", value=lambda r: r.num, kind="number", numeric=True)
SECRET_PAY = Column(
    key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True, needs="macs.view_salary"
)
ALL_PERMS = SimpleNamespace(has_perm=lambda perm: True)
NO_PERMS = SimpleNamespace(has_perm=lambda perm: False)


def _row(name: str, dept: object, pay: object = 0, num: object = 0) -> Any:
    return SimpleNamespace(name=name, dept=dept, pay=pay, num=num)


def _spec(value: tuple[Column | None, str], by: Column | None = DEPT) -> LayoutSpec:
    return LayoutSpec(layout="board", by=by, by2=None, value=value, chart="bar", month=date(2026, 11, 1))


def _table(rows: list[Any], columns: list[Column], spec: LayoutSpec) -> Table:
    return Table(columns=columns, groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)


def _report(columns: tuple[Column, ...]) -> Report:
    return Report(
        key=KEY,
        title="Board sum",
        filters=(),
        columns=columns,
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=("dept",),
        layouts=("board",),
    )


def test_lane_sum_covers_rows_past_the_cap() -> None:
    assert layouts_mod.BOARD_CAP == 200
    rows = [_row(f"Нэр {i}", "X", pay=i) for i in range(1, 251)]  # 250 rows in one lane, pay 1..250
    spec = _spec((PAY, "sum"))
    columns = [NAME, DEPT, PAY]
    board = layouts_mod.build_board(_table(rows, columns, spec), spec, (), TODAY)
    lane = board.lanes[0]
    assert lane.count == 250
    assert len(lane.items) == 200  # the cards drawn stop at the cap
    assert board.shown == 200
    assert lane.figure == sum(range(1, 251)) == 31375  # the sum counts all 250 rows, not the 200 drawn
    assert lane.money is True


def test_small_lane_money_is_masked() -> None:
    rows = [
        _row("Бат", "Хоёр", pay=500),
        _row("Дорж", "Хоёр", pay=700),  # a lane of 2 rows: under privacy.min_group() (3)
        _row("Оюу", "Гурав", pay=100),
        _row("Номин", "Гурав", pay=200),
        _row("Сараа", "Гурав", pay=300),  # a lane of 3 rows
    ]
    spec = _spec((PAY, "sum"))
    board = layouts_mod.build_board(_table(rows, [NAME, DEPT, PAY], spec), spec, (), TODAY)
    by_label = {lane.label: lane for lane in board.lanes}
    assert by_label["Хоёр"].count == 2
    assert by_label["Хоёр"].figure is None
    assert by_label["Хоёр"].money is True
    assert by_label["Гурав"].count == 3
    assert by_label["Гурав"].figure == 600


def test_count_value_adds_nothing() -> None:
    rows = [_row("Бат", "Ачаа", pay=500), _row("Дорж", "Ачаа", pay=700), _row("Оюу", "Бэлэн", pay=100)]
    spec = _spec((None, "count"))
    board = layouts_mod.build_board(_table(rows, [NAME, DEPT, PAY], spec), spec, (), TODAY)
    assert [lane.figure for lane in board.lanes] == [None, None]
    assert [lane.money for lane in board.lanes] == [False, False]
    assert layouts_mod.value_caption(spec.value) == ""


def test_lval_with_hidden_column_falls_back_to_count() -> None:
    report = _report((NAME, DEPT, SECRET_PAY))
    filters = parse_filters(QueryDict("layout=board&lby=dept&lval=pay:sum"))
    spec = layouts_mod.resolve(report, NO_PERMS, filters, [])
    assert spec.value == (None, "count")  # the hidden column is never used
    assert layouts_mod.clean_params(report, NO_PERMS, filters)["lval"] == ""
    rows = [_row("Бат", "Ачаа", pay=500), _row("Дорж", "Ачаа", pay=700), _row("Оюу", "Ачаа", pay=100)]
    board = layouts_mod.build_board(_table(rows, [NAME, DEPT], spec), spec, (), TODAY)
    assert board.lanes[0].figure is None
    assert board.lanes[0].count == 3


def test_avg_and_max_per_lane() -> None:
    rows = [
        _row("Бат", "Ачаа", num=1),
        _row("Дорж", "Ачаа", num=2),
        _row("Оюу", "Ачаа", num=6),
        _row("Номин", "Бэлэн", num=4),
    ]
    avg_spec = _spec((NUM, "avg"))
    avg_board = layouts_mod.build_board(_table(rows, [NAME, DEPT, NUM], avg_spec), avg_spec, (), TODAY)
    assert [lane.figure for lane in avg_board.lanes] == [3, 4]
    assert [lane.money for lane in avg_board.lanes] == [False, False]
    max_spec = _spec((NUM, "max"))
    max_board = layouts_mod.build_board(_table(rows, [NAME, DEPT, NUM], max_spec), max_spec, (), TODAY)
    assert [lane.figure for lane in max_board.lanes] == [6, 4]


def test_used_params_writes_lval_for_board_not_table() -> None:
    report = _report((NAME, DEPT, PAY))
    filters = parse_filters(QueryDict("layout=board&lby=dept&lval=pay:sum"))
    board_spec = layouts_mod.resolve(report, ALL_PERMS, filters, [])
    assert layouts_mod.used_params(filters, board_spec).lval == "pay:sum"
    table_filters = parse_filters(QueryDict("layout=table&lby=dept&lval=pay:sum"))
    table_spec = layouts_mod.resolve(report, ALL_PERMS, table_filters, [])
    assert table_spec.layout == "table"
    assert layouts_mod.used_params(table_filters, table_spec).lval == ""


def _page_report(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        _row("Бат", "Ачаа", pay=500),
        _row("Дорж", "Ачаа", pay=500),
        _row("Оюу", "Ачаа", pay=500),
        _row("Номин", "Санхүү", pay=500),
        _row("Сараа", "Санхүү", pay=500),
    ]
    report = Report(
        key=KEY,
        title="Board sum",
        filters=(),
        columns=(NAME, DEPT, PAY),
        default_columns=("name", "dept", "pay"),
        rows=lambda user, filters: rows,
        group_options=("dept",),
        layouts=("board",),
    )
    monkeypatch.setitem(REPORTS, KEY, report)


def _headings(page: str) -> list[str]:
    """The text of each lane heading, with its tags and the page's spacing removed."""
    found = re.findall(r'<h2 class="mb-2 px-1 text-sm font-semibold text-slate-900">(.*?)</h2>', page, flags=re.S)
    return [" ".join(re.sub(r"<[^>]+>", "", h).split()) for h in found]


@pytest.mark.django_db
def test_page_shows_money_sum_and_masked_dash_in_lane_heading(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _page_report(monkeypatch)
    login_as(client, "HR")
    page = client.get(
        PAGE, {"layout": "board", "lby": "dept", "lval": "pay:sum", "cols": ["name", "dept", "pay"]}
    ).content.decode()
    assert _headings(page) == ["Ачаа · 3 · 1,500₮", "Санхүү · 2 · —"]
    assert "Утга: Цалин (Нийлбэр)" in page
    assert 'name="lval"' in page  # the «Утга» select is in the layout bar for the board


@pytest.mark.django_db
def test_page_count_heading_is_label_and_count_only(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _page_report(monkeypatch)
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board", "lby": "dept", "cols": ["name", "dept", "pay"]}).content.decode()
    assert _headings(page) == ["Ачаа · 3", "Санхүү · 2"]
    assert "Утга:" not in page


def test_board_count_of_a_column_writes_no_lval() -> None:
    """A board whose value is the count of a column (pay:count) adds nothing up: lval is not written. A sum is."""
    counted = layouts_mod.used_params(Filters(layout="board"), _spec((PAY, "count")))
    assert counted.lval == ""
    summed = layouts_mod.used_params(Filters(layout="board"), _spec((PAY, "sum")))
    assert summed.lval == "pay:sum"
