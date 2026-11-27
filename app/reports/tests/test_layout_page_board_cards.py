"""The request-free board and cards pages (services.layout_page): lane labels, counts and figures, the card cap, the
card extras as finished text, the cards' batches and the photo initial."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from config import batching

from reports import layouts as layouts_mod
from reports import views
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.services import layout_page
from reports.table import EMPTY_GROUP, Table
from reports.types import Column

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
EMAIL = Column(key="email", label="И-мэйл", value=lambda r: r.email, kind="text", action="mailto")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True)
SALARY = Column(key="salary", label="Цалин", value=lambda r: r.salary, kind="number", money=True)
NO_PHOTO = SimpleNamespace(photo=None)


def _row(name: Any, dept: Any = None, **fields: Any) -> Any:
    values: dict[str, Any] = {"email": None, "start": None, "pay": 0, "salary": None, **fields}
    return SimpleNamespace(name=name, dept=dept, **values)


def _spec(value: tuple[Column | None, str] = (None, "count"), by: Column | None = DEPT) -> LayoutSpec:
    return LayoutSpec(layout="board", by=by, by2=None, value=value, chart="bar", month=date(2026, 11, 1))


def _table(rows: list[Any], columns: list[Column] | None = None, spec: LayoutSpec | None = None) -> Table:
    return Table(
        columns=columns if columns is not None else [NAME, DEPT, EMAIL, START, PAY, SALARY],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec if spec is not None else _spec(),
    )


def _drill(pairs: list[tuple[Column | None, str | None]]) -> str:
    """A stub address: a link for a category key, «» for a pair with no key or no column (as drill_url does)."""
    column, key = pairs[0]
    if column is None or key is None:
        return ""
    return f"/reports/x/?{column.key}={key}"


def test_board_lane_labels_counts_and_figure_text() -> None:
    rows = [
        _row("Бат", "Санхүү", pay=10),
        _row("Дорж", "Ачаа", pay=5),
        _row("Оюу", "Ачаа", pay=7),
        _row("Төмөр", "", pay=1),
    ]
    spec = _spec(value=(PAY, "sum"))
    board = layout_page.board_page(_table(rows, spec=spec), spec, (), TODAY, _drill)
    assert [lane.label for lane in board.lanes] == ["Ачаа", "Санхүү", EMPTY_GROUP]
    assert [lane.count for lane in board.lanes] == [2, 1, 1]
    assert [lane.figure for lane in board.lanes] == ["12", "10", "1"]
    assert board.lanes[0].href == "/reports/x/?dept=Ачаа"
    assert board.lanes[2].href == "/reports/x/?dept="  # the blank lane links to its blank rule
    assert board.value_label == "Цалин (Нийлбэр)"
    assert (board.total, board.shown, board.cap) == (4, 4, layouts_mod.BOARD_CAP)
    assert [card.title for card in board.lanes[0].cards] == ["Дорж", "Оюу"]


def test_board_count_value_has_no_figure_or_caption() -> None:
    rows = [_row("Бат", "Санхүү"), _row("Дорж", "Санхүү")]
    board = layout_page.board_page(_table(rows), _spec(), (), TODAY, _drill)
    assert board.lanes[0].figure == ""
    assert board.value_label == ""


def test_board_money_figure_is_mnt_text() -> None:
    rows = [_row(f"Р{i}", "Ачаа", salary=Decimal("1000000")) for i in range(3)]
    spec = _spec(value=(SALARY, "sum"))
    board = layout_page.board_page(_table(rows, spec=spec), spec, (), TODAY, _drill)
    assert board.lanes[0].figure == "3,000,000₮"


def test_board_card_cap_keeps_lane_counts_of_every_row() -> None:
    rows = [_row(f"Р{i}", "Ачаа") for i in range(layouts_mod.BOARD_CAP + 5)] + [_row("X", "Бэлэн")]
    board = layout_page.board_page(_table(rows), _spec(), (), TODAY, _drill)
    lanes = {lane.label: lane for lane in board.lanes}
    assert lanes["Ачаа"].count == layouts_mod.BOARD_CAP + 5
    assert len(lanes["Ачаа"].cards) == layouts_mod.BOARD_CAP
    assert lanes["Бэлэн"].count == 1
    assert lanes["Бэлэн"].cards == []
    assert (board.total, board.shown, board.cap) == (layouts_mod.BOARD_CAP + 6, layouts_mod.BOARD_CAP, 200)


def test_board_lane_without_drill_has_no_href() -> None:
    """Two keys that read the same once case-folded («A» and «a») are colliding: neither lane gets a link."""
    rows = [_row("Бат", "a"), _row("Дорж", "A"), _row("Оюу", "Бэлэн")]
    board = layout_page.board_page(_table(rows), _spec(), (), TODAY, _drill)
    hrefs = {lane.label: lane.href for lane in board.lanes}
    assert hrefs["a"] == ""
    assert hrefs["A"] == ""
    assert hrefs["Бэлэн"] == "/reports/x/?dept=Бэлэн"


def test_card_extras_money_is_mnt_text_and_contact_links_keep_href() -> None:
    rows = [_row("Бат", "Санхүү", email="bat@macs.mn", start=date(2026, 11, 7), salary=Decimal("2500000"))]
    report = SimpleNamespace(photo=None)
    cards = layout_page.cards_page(_table(rows, columns=[NAME, DEPT, EMAIL, START, SALARY]), report, (), TODAY, 0)
    card = cards.items[0]
    assert card.title == "Бат"
    assert card.subtitle == "Санхүү"
    assert [(e.label, e.text, e.href) for e in card.extras] == [
        ("И-мэйл", "bat@macs.mn", "mailto:bat@macs.mn"),
        ("Эхлэх", "2026-11-07", ""),
        ("Цалин", "2,500,000₮", ""),
    ]


def test_card_extras_count_matches_the_view() -> None:
    assert layout_page.CARD_EXTRAS == views.CARD_EXTRAS


def test_cards_first_batch_and_next_offset_then_last_batch_has_none() -> None:
    size = batching.LIST_BATCH
    rows = [_row(f"Р{i:03d}", "X") for i in range(2 * size + 10)]
    report = SimpleNamespace(photo=None)
    table = _table(rows)
    first = layout_page.cards_page(table, report, (), TODAY, 0)
    assert (len(first.items), first.next_offset, first.total) == (size, size, 2 * size + 10)
    second = layout_page.cards_page(table, report, (), TODAY, size)
    assert (len(second.items), second.next_offset) == (size, 2 * size)
    last = layout_page.cards_page(table, report, (), TODAY, 2 * size)
    assert [card.title for card in last.items][0] == f"Р{2 * size:03d}"
    assert (len(last.items), last.next_offset) == (10, None)


@pytest.mark.parametrize("offset", [-5, 10**20])
def test_cards_offset_junk_starts_at_zero(offset: int) -> None:
    rows = [_row(f"Р{i:03d}", "X") for i in range(70)]
    report = SimpleNamespace(photo=None)
    junk = layout_page.cards_page(_table(rows), report, (), TODAY, offset)
    first = layout_page.cards_page(_table(rows), report, (), TODAY, 0)
    assert [card.title for card in junk.items] == [card.title for card in first.items]
    assert junk.next_offset == first.next_offset


def test_card_title_html_stays_text() -> None:
    rows = [_row("<b>x</b>", "Санхүү")]
    report = SimpleNamespace(photo=None)
    card = layout_page.cards_page(_table(rows), report, (), TODAY, 0).items[0]
    assert card.title == "<b>x</b>"


def test_card_photo_initial_when_there_is_no_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """A person's card with no photo: no thumbnail URL and the first letter of the given name for the soft tile. The
    digest attach is replaced, so the test reads no database."""
    monkeypatch.setattr(layout_page, "attach_photo_digests", lambda employees: None)
    employee = SimpleNamespace(given_name="Бат", _photo_md5="")  # "" = known to have no photo (thumbnail_url)
    report = SimpleNamespace(photo=lambda row: row.employee)
    rows = [SimpleNamespace(name="Бат", dept="Санхүү", email=None, start=None, pay=0, salary=None, employee=employee)]
    card = layout_page.cards_page(_table(rows), report, (), TODAY, 0).items[0]
    assert card.title == "Бат"  # a person's card is titled with the name
    assert (card.photo_url, card.photo_initial) == ("", "Б")


def test_card_without_photo_slot_has_no_photo_fields() -> None:
    rows = [_row("Бат", "Санхүү")]
    card = layout_page.cards_page(_table(rows), SimpleNamespace(photo=None), (), TODAY, 0).items[0]
    assert (card.photo_url, card.photo_initial) == ("", "")


def test_card_photo_url_and_srcset_when_there_is_an_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """A person's card with an image: the 72 px src and the 2x and 3x srcset of the template, and no initial. The
    thumbnail helper is stubbed (the real one needs the database and storage), so only the branch logic is checked."""
    monkeypatch.setattr(layout_page, "attach_photo_digests", lambda employees: None)

    def fake_thumb(employee: Any, side: int) -> str:
        return f"/thumbs/{employee.pk}_{side}.jpg" if employee.has_photo else ""

    monkeypatch.setattr(layout_page, "thumb", fake_thumb)
    employee = SimpleNamespace(pk=7, given_name="Бат", has_photo=True)
    report = SimpleNamespace(photo=lambda row: row.employee)
    rows = [SimpleNamespace(name="Бат", dept="Санхүү", email=None, start=None, pay=0, salary=None, employee=employee)]
    card = layout_page.cards_page(_table(rows), report, (), TODAY, 0).items[0]
    assert card.photo_url == "/thumbs/7_72.jpg"
    assert card.photo_srcset == "/thumbs/7_144.jpg 2x, /thumbs/7_216.jpg 3x"
    assert card.photo_initial == ""


def test_board_money_lane_under_the_privacy_group_shows_a_dash() -> None:
    """A money lane with fewer rows than privacy.min_group() (3) hides its figure: it prints «—», never the sum."""
    rows = [_row("Бат", "Санхүү", salary=Decimal("1000000")), _row("Дорж", "Санхүү", salary=Decimal("500000"))]
    rows += [_row("Оюу", "Ачаа", salary=Decimal("700000")) for _ in range(3)]
    spec = _spec(value=(SALARY, "sum"))
    board = layout_page.board_page(_table(rows, spec=spec), spec, (), TODAY, _drill)
    lanes = {lane.label: lane for lane in board.lanes}
    assert lanes["Санхүү"].figure == "—"
    assert lanes["Ачаа"].figure == "2,100,000₮"
