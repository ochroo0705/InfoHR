"""Board lane order (Task 17, Decision 7): a report's declared flow order (Report.lane_orders), lorder=count, the blank
lane last in both, a listed name with no rows, count winning over a declared order, the real leave-requests and orders
boards, and the «Эрэмбэ» select of the layout bar."""

from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import HrOrder
from employees.services import history
from employees.tests.conftest import hire_values
from leave.services import writes
from leave.tests.conftest import annual, make_employee, sick  # noqa: F401 (fixtures)
from macs.models import LeaveTypeRow

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.leave_requests import REPORT as LEAVE_REPORT
from reports.orders import REPORT as ORDERS_REPORT
from reports.registry import REPORTS
from reports.table import Table, build_table
from reports.types import Column, Report

TODAY = date(2026, 11, 7)
YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")


def _row(dept: object, name: str = "x", start: object = None) -> Any:
    return SimpleNamespace(dept=dept, name=name, start=start)


def _board(
    rows: list[Any],
    order: str = "",
    lane_order: tuple[str, ...] = (),
) -> layouts_mod.Board:
    spec = LayoutSpec(
        layout="board",
        by=DEPT,
        by2=None,
        value=(None, "count"),
        chart="bar",
        month=date(2026, 11, 1),
        order=order,
        lane_order=lane_order,
    )
    table = Table(columns=[NAME, DEPT], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)
    return layouts_mod.build_board(table, spec, (), TODAY)


def _keys(board: layouts_mod.Board) -> list[str]:
    return [lane.key for lane in board.lanes]


def test_declared_order_then_alphabetical() -> None:
    rows = [_row("Ачаа"), _row("Бэлэн"), _row("Санхүү"), _row("Тэмдэг"), _row(None)]
    board = _board(rows, lane_order=("Санхүү", "Бэлэн"))
    # the listed names first in list order, the rest alphabetical, the blank lane last
    assert _keys(board) == ["Санхүү", "Бэлэн", "Ачаа", "Тэмдэг", ""]
    assert board.lanes[-1].label == "—"


def test_count_order() -> None:
    rows = [
        *[_row("Санхүү") for _ in range(5)],
        *[_row("Ачаа") for _ in range(3)],
        *[_row("Бэлэн") for _ in range(3)],
        _row("Ханш"),
        *[_row(None) for _ in range(2)],
    ]
    board = _board(rows, order="count")
    # high to low; the tie (3 and 3) keeps the alphabetical order; the blank lane (2 rows) stays last
    assert _keys(board) == ["Санхүү", "Ачаа", "Бэлэн", "Ханш", ""]
    assert [lane.count for lane in board.lanes] == [5, 3, 3, 1, 2]


def test_blank_lane_is_last_in_both() -> None:
    rows = [*[_row(None) for _ in range(3)], *[_row("   ") for _ in range(2)], _row("Ачаа"), _row("Бэлэн")]
    # the blank key has the most rows and still comes last; the spaces-only lane comes just before it
    assert _keys(_board(rows, order="count")) == ["Ачаа", "Бэлэн", "   ", ""]
    assert _keys(_board(rows, lane_order=("Бэлэн", "Ачаа"))) == ["Бэлэн", "Ачаа", "   ", ""]


def test_report_without_lane_orders_is_unchanged() -> None:
    plain = Report(key="plain", title="Тайлан", filters=(), columns=(), default_columns=(), rows=lambda u, f: [])
    assert plain.lane_orders == {}
    rows = [_row("Санхүү"), _row("Ачаа"), _row(None), _row("бэлэн"), _row("Ачаа")]
    board = _board(rows)
    # the default order: named by casefold, then the blank lane last
    assert _keys(board) == ["Ачаа", "бэлэн", "Санхүү", ""]
    assert [lane.count for lane in board.lanes] == [2, 1, 1, 1]


def test_count_wins_over_a_declared_order() -> None:
    rows = [*[_row("Санхүү") for _ in range(5)], *[_row("Ачаа") for _ in range(3)], _row("Бэлэн")]
    board = _board(rows, order="count", lane_order=("Бэлэн", "Санхүү"))
    assert _keys(board) == ["Санхүү", "Ачаа", "Бэлэн"]


def test_listed_name_without_rows_makes_no_lane() -> None:
    rows = [_row("Ачаа"), _row("Бэлэн"), _row("Санхүү")]
    board = _board(rows, lane_order=("Хүнд", "Бэлэн", "Ачаа"))
    assert _keys(board) == ["Бэлэн", "Ачаа", "Санхүү"]
    assert "Хүнд" not in [lane.label for lane in board.lanes]


def test_leave_requests_board_starts_with_pending(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)  # «Бүртгэсэн»
    mistake = writes.record_assign(emp, sick, date(2026, 5, 4), date(2026, 5, 6), 3, "", actor)
    writes.cancel_assign(mistake, writes.snapshot(mistake), "Алдаа", mistake=True, by=actor)  # «Буруу бүртгэсэн»
    filters = Filters(date_from=YEAR_START, date_to=YEAR_END, layout="board", lby="state")
    table = build_table(LEAVE_REPORT, hr_user, filters)
    board = layouts_mod.build_board(table, table.spec, [], TODAY)
    # alphabetically «Буруу» comes first (у before ү); the declared flow puts the recorded (active) state first
    assert [lane.label for lane in board.lanes] == ["Бүртгэсэн", "Буруу бүртгэсэн"]


def test_orders_board_lane_order(hr_user: User, hired: Any, actor: User, job_values: dict[str, Any]) -> None:
    HrOrder.objects.filter(employee=hired, is_hire=True).update(number="12", date=date(2026, 1, 5), state="pending")
    other = history.hire(
        {**hire_values("УБ99112255"), "family_name": "Дорж", "given_name": "Бат"},
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=actor,
    )
    HrOrder.objects.filter(employee=other, is_hire=True).update(number="13", date=date(2026, 1, 6), state="signed")
    filters = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31), layout="board", lby="state")
    table = build_table(ORDERS_REPORT, hr_user, filters)
    board = layouts_mod.build_board(table, table.spec, [], TODAY)
    # alphabetically «Гарын» comes before «Дугаар»; the declared flow puts the draft (no number yet) first
    assert [lane.label for lane in board.lanes] == ["Дугаар оруулаагүй", "Гарын үсэгтэй"]


# ---- the page: the «Эрэмбэ» select of the layout bar -------------------------------------------------------------

PAGE_KEY = "board-lane-order-test"
PAGE = f"/reports/{PAGE_KEY}/"
PAGE_ROWS = [
    SimpleNamespace(dept="Ачаа", name="Бат", start=date(2026, 1, 5)),
    SimpleNamespace(dept="Санхүү", name="Дорж", start=date(2026, 2, 3)),
    SimpleNamespace(dept="Санхүү", name="Оюу", start=date(2026, 2, 9)),
]


@pytest.fixture
def order_report(monkeypatch: pytest.MonkeyPatch) -> None:
    report = Report(
        key=PAGE_KEY,
        title="Тайлан",
        filters=(),
        columns=(DEPT, NAME, START),
        default_columns=("dept",),
        rows=lambda user, filters: PAGE_ROWS,
        group_options=("dept",),
        layouts=("board", "calendar"),
        layout_date="start",
        lane_orders={"dept": ("Санхүү", "Ачаа")},
    )
    monkeypatch.setitem(REPORTS, PAGE_KEY, report)


@pytest.mark.django_db
def test_layout_bar_shows_the_order_select_for_the_board_only(
    client: Client, login_as: Callable[..., User], order_report: None
) -> None:
    login_as(client, "HR")
    plain = client.get(PAGE, {"layout": "board", "lby": "dept"})
    assert plain.context["spec"].layout == "board"
    content = plain.content.decode()
    assert '<select name="lorder"' in content
    assert "Эрэмбэ" in content
    assert '<option value="" selected>Анхны дараалал</option>' in content
    assert '<option value="count">Тоогоор</option>' in content

    counted = client.get(PAGE, {"layout": "board", "lby": "dept", "lorder": "count"})
    content = counted.content.decode()
    assert '<option value="count" selected>Тоогоор</option>' in content
    assert '<option value="">Анхны дараалал</option>' in content

    calendar = client.get(PAGE, {"layout": "calendar"})
    assert calendar.context["spec"].layout == "calendar"
    assert '<select name="lorder"' not in calendar.content.decode()

    table = client.get(PAGE, {})
    assert table.context["spec"].layout == "table"
    assert '<select name="lorder"' not in table.content.decode()
