"""Board cards show the next shown columns as label: value lines, formatted as the cards view formats them."""

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.template.loader import get_template
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

TODAY = date(2026, 11, 7)
KEY = "board-extras-test"
PAGE = f"/reports/{KEY}/"

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Огноо", value=lambda r: r.start, kind="date")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
ROOM = Column(key="room", label="Өрөө", value=lambda r: r.room, kind="text")


def _row(name: str, dept: str, start: date | None = None, pay: object = 0, room: str = "A1") -> Any:
    return SimpleNamespace(name=name, dept=dept, start=start, pay=pay, room=room)


def _table(rows: list[Any], columns: list[Column], by: Column | None = DEPT) -> Table:
    spec = LayoutSpec(layout="board", by=by, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1))
    return Table(columns=columns, groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)


def test_board_item_has_two_extras() -> None:
    assert layouts_mod.BOARD_EXTRAS == 2
    rows = [_row("Бат", "Санхүү", start=date(2026, 3, 15), pay=2500000)]
    columns = [NAME, DEPT, START, PAY, ROOM]  # title Нэр, subtitle Хэлтэс, then 3 more: only 2 are extras
    board = layouts_mod.build_board(_table(rows, columns), _table(rows, columns).spec, (), TODAY)
    item = board.lanes[0].items[0]
    assert len(item.extras) == 2
    assert [label for label, _value, _money in item.extras] == ["Огноо", "Цалин"]


def test_extras_skip_title_and_subtitle_columns() -> None:
    rows = [_row("Бат", "Санхүү", start=date(2026, 3, 15), pay=900)]
    columns = [START, NAME, DEPT, PAY]  # title is Нэр and subtitle Хэлтэс, even though they are not the first columns
    board = layouts_mod.build_board(_table(rows, columns), _table(rows, columns).spec, (), TODAY)
    item = board.lanes[0].items[0]
    assert item.title == "Бат"
    assert item.subtitle == "Санхүү"
    assert [label for label, _value, _money in item.extras] == ["Огноо", "Цалин"]


@pytest.fixture
def board_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    rows = [
        _row("Бат", "Санхүү", start=date(2026, 3, 15), pay=2500000),
        _row("Дорж", "Ачаа", start=None, pay=0),
    ]
    report = Report(
        key=KEY,
        title="Board extras",
        filters=(),
        columns=(NAME, DEPT, START, PAY),
        default_columns=("name", "dept", "start", "pay"),
        rows=lambda user, filters: rows,
        group_options=("dept",),
        layouts=("board", "cards"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


@pytest.mark.django_db
def test_board_card_renders_extras_with_money_and_date_formatting(
    client: Client, login_as: Callable[..., User], board_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(
        PAGE, {"layout": "board", "lby": "dept", "cols": ["name", "dept", "start", "pay"]}
    ).content.decode()
    assert '<span class="text-slate-500">Огноо:</span> 2026-03-15</p>' in page
    assert '<span class="text-slate-500">Цалин:</span> 2,500,000₮</p>' in page


@pytest.mark.django_db
def test_cards_output_unchanged(client: Client, login_as: Callable[..., User], board_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "cards", "cols": ["name", "dept", "start", "pay"]}).content.decode()
    assert '<p class="text-slate-700"><span class="text-slate-500">Цалин:</span> 2,500,000₮</p>' in page
    assert '<p class="text-slate-700"><span class="text-slate-500">Огноо:</span> 2026-03-15</p>' in page


@pytest.mark.django_db
def test_extras_are_not_links(client: Client, login_as: Callable[..., User], board_report: Report) -> None:
    login_as(client, "HR")
    page = client.get(
        PAGE, {"layout": "board", "lby": "dept", "cols": ["name", "dept", "start", "pay"]}
    ).content.decode()
    extras = re.findall(r'<p class="mt-1 text-xs text-slate-600">.*?</p>', page)
    assert len(extras) == 4  # two cards, two extras each
    assert any('<span class="text-slate-500">Цалин:</span> 2,500,000₮</p>' in line for line in extras)
    assert all("<a " not in line for line in extras)
    assert '<a href="' in page  # the title still links


# The cards batch for one card with a money and a date extra, exactly as the inline loop rendered it before the
# partial _extras.html existed. The last extras line is followed by "\n    \n  </div>": a final newline in the partial
# would add a line break there, so this string must match character for character.
EXPECTED_CARDS_BATCH = "\n".join(
    [
        "",
        "",
        '<article class="relative flex gap-3 rounded-xl border border-slate-200 bg-surface p-4 text-sm ">',
        "  ",
        '  <div class="flex min-w-0 flex-1 flex-col gap-1">',
        '    <h2 class="line-clamp-2 font-semibold text-slate-900">Бат</h2>',
        '    <p class="line-clamp-2 text-slate-500">Санхүү</p>',
        "    ",
        '    <p class="text-slate-700"><span class="text-slate-500">Цалин:</span> 2,500,000₮</p>',
        "    ",
        '    <p class="text-slate-700"><span class="text-slate-500">Огноо:</span> 2026-03-15</p>',
        "    ",
        "  </div>",
        "</article>",
        "",
        "",
        "",
    ]
)


def test_cards_batch_output_is_pinned_character_for_character() -> None:
    items = [
        layouts_mod.Item(
            title="Бат",
            subtitle="Санхүү",
            href="",
            mark="",
            extras=(("Цалин", Decimal("2500000"), True), ("Огноо", date(2026, 3, 15), False)),
        )
    ]
    rendered = get_template("reports/layouts/_cards_batch.html").render(
        {"cards_items": items, "cards_next_query": None}
    )
    assert rendered == EXPECTED_CARDS_BATCH


def test_extras_partial_has_no_trailing_newline() -> None:
    path = Path(get_template("reports/layouts/_extras.html").origin.name)
    data = path.read_bytes()
    assert not data.endswith(b"\n"), (
        "_extras.html must not end with a newline: the cards batch includes it, and a final newline adds a line "
        "break after the last extras line of every card"
    )
