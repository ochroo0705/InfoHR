"""Items and the board: the card of one row, the lanes by a category column, the caps and the colour of a card."""

from datetime import date
from types import SimpleNamespace
from typing import Any

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.marks import COLOURS, Mark
from reports.table import EMPTY_GROUP, Table
from reports.types import Column

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True)


def _row(name: str | None, dept: object, start: object = None, pay: object = 0) -> Any:
    return SimpleNamespace(name=name, dept=dept, start=start, pay=pay)


def _table(rows: list[Any], columns: list[Column] | None = None, by: Column | None = DEPT) -> Table:
    spec = LayoutSpec(layout="board", by=by, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1))
    return Table(
        columns=columns if columns is not None else [NAME, DEPT, START, PAY],
        groups=[],
        count=len(rows),
        filters=Filters(),
        rows=rows,
        spec=spec,
    )


def test_lanes_follow_label_order_with_blank_last_and_counts() -> None:
    rows = [
        _row("Бат", "Санхүү"),
        _row("Дорж", "Ачаа"),
        _row("Сараа", None),
        _row("Оюу", "Ачаа"),
        _row("Номин", "Бэлэн"),
        _row("Төмөр", ""),
    ]
    board = layouts_mod.build_board(_table(rows), _table(rows).spec, (), TODAY)
    assert [lane.label for lane in board.lanes] == ["Ачаа", "Бэлэн", "Санхүү", EMPTY_GROUP]
    assert [lane.count for lane in board.lanes] == [2, 1, 1, 2]
    assert board.lanes[3].label == "—"
    assert board.total == 6
    assert board.shown == 6


def test_cards_keep_the_table_row_order_inside_a_lane() -> None:
    rows = [_row("Б", "X"), _row("А", "X"), _row("В", "X")]
    board = layouts_mod.build_board(_table(rows), _table(rows).spec, (), TODAY)
    assert [item.title for item in board.lanes[0].items] == ["Б", "А", "В"]


def test_cap_of_200_cards_counts_all_rows() -> None:
    rows = [_row(f"Нэр {i}", "X") for i in range(250)]
    board = layouts_mod.build_board(_table(rows), _table(rows).spec, (), TODAY)
    assert board.cap == 200
    assert board.total == 250
    assert board.shown == 200
    assert sum(len(lane.items) for lane in board.lanes) == 200
    assert board.lanes[0].count == 250  # the lane count is the filtered count, not the drawn one


def test_title_is_the_first_text_column_and_subtitle_the_next() -> None:
    rows = [_row("Бат", "Санхүү", start=date(2026, 1, 5), pay=900)]
    columns = [START, PAY, NAME, DEPT]
    board = layouts_mod.build_board(_table(rows, columns), _table(rows, columns).spec, (), TODAY)
    item = board.lanes[0].items[0]
    assert item.title == "Бат"
    assert item.subtitle == "Санхүү"


def test_title_falls_back_to_first_column_when_no_text_column_is_shown() -> None:
    rows = [_row("Бат", "Санхүү", start=date(2026, 1, 5), pay=900)]
    columns = [START, PAY]
    item = layouts_mod.make_items(_table(rows, columns), rows, (), TODAY)[0]
    assert item.title == "2026-01-05"
    assert item.subtitle == ""


def test_card_mark_is_the_first_passing_rule_on_any_shown_column() -> None:
    rows = [_row("Бат", "Санхүү"), _row("Дорж", "Ачаа")]
    marks = (Mark(column="name", rule_op="eq", value="Бат", colour="red"),)
    items = layouts_mod.make_items(_table(rows), rows, marks, TODAY)
    assert items[0].mark == COLOURS["red"]
    assert items[1].mark == ""


def test_card_mark_on_a_non_title_column_applies() -> None:
    rows = [_row("Бат", "Санхүү"), _row("Дорж", "Ачаа")]
    marks = (Mark(column="dept", rule_op="eq", value="Ачаа", colour="green"),)
    items = layouts_mod.make_items(_table(rows), rows, marks, TODAY)
    assert items[0].mark == ""
    assert items[1].mark == COLOURS["green"]


def test_extras_are_the_remaining_shown_columns_as_label_value_money_triples() -> None:
    rows = [_row("Бат", "Санхүү", start=date(2026, 1, 5), pay=900)]
    item = layouts_mod.make_items(_table(rows), rows, (), TODAY, extras=2)[0]
    assert item.extras == (("Эхлэх", date(2026, 1, 5), False), ("Цалин", 900, False))


def test_all_blank_category_is_one_lane_with_the_dash() -> None:
    rows = [_row("Бат", None), _row("Дорж", "")]
    board = layouts_mod.build_board(_table(rows), _table(rows).spec, (), TODAY)
    assert len(board.lanes) == 1
    assert board.lanes[0].label == "—"
    assert board.lanes[0].count == 2


def test_zero_rows_give_no_lanes() -> None:
    board = layouts_mod.build_board(_table([]), _table([]).spec, (), TODAY)
    assert board.lanes == []
    assert board.total == 0
    assert board.shown == 0


def test_lane_label_matches_the_table_empty_group_constant() -> None:
    assert layouts_mod.EMPTY_GROUP == EMPTY_GROUP


def test_first_passing_mark_in_marks_order_wins_across_columns() -> None:
    rows = [_row("Бат", "Ачаа")]
    marks = (
        Mark(column="dept", rule_op="eq", value="Ачаа", colour="green"),
        Mark(column="name", rule_op="eq", value="Бат", colour="red"),
    )
    assert layouts_mod.make_items(_table(rows), rows, marks, TODAY)[0].mark == COLOURS["green"]
    flipped = (marks[1], marks[0])
    assert layouts_mod.make_items(_table(rows), rows, flipped, TODAY)[0].mark == COLOURS["red"]


def test_mark_on_a_column_not_shown_is_skipped_for_the_next_rule() -> None:
    rows = [_row("Бат", "Ачаа", pay=900)]
    marks = (
        Mark(column="pay", rule_op="eq", value="900", colour="red"),
        Mark(column="dept", rule_op="eq", value="Ачаа", colour="blue"),
    )
    table = _table(rows, [NAME, DEPT])
    assert layouts_mod.make_items(table, rows, marks, TODAY)[0].mark == COLOURS["blue"]


def test_title_skips_a_text_column_blank_in_every_row() -> None:
    rows = [_row("", "Санхүү"), _row("   ", "Ачаа")]
    items = layouts_mod.make_items(_table(rows, [NAME, DEPT]), rows, (), TODAY)
    assert items[0].title == "Санхүү"
    assert items[0].subtitle == ""


def test_whitespace_title_shows_dash_and_whitespace_subtitle_is_empty() -> None:
    rows = [_row("  ", "   "), _row("Бат", "Ачаа")]
    items = layouts_mod.make_items(_table(rows, [NAME, DEPT]), rows, (), TODAY)
    assert items[0].title == EMPTY_GROUP
    assert items[0].subtitle == ""
    assert items[1].title == "Бат"
    assert items[1].subtitle == "Ачаа"


def test_subtitle_is_empty_when_only_one_text_column_is_shown() -> None:
    rows = [_row("Бат", "Санхүү", start=date(2026, 1, 5), pay=900)]
    items = layouts_mod.make_items(_table(rows, [NAME, START, PAY]), rows, (), TODAY)
    assert items[0].title == "Бат"
    assert items[0].subtitle == ""


def test_hostile_values_never_raise_and_show_text() -> None:
    long_text = "а" * 5000
    rows = [
        _row(None, None),
        _row(long_text, long_text),
        _row("Бат", True, start=date(2026, 1, 5)),
        _row("Дорж", date(2026, 3, 1)),
    ]
    columns = [NAME, DEPT, START]
    board = layouts_mod.build_board(_table(rows, columns), _table(rows, columns).spec, (), TODAY)
    labels = [lane.label for lane in board.lanes]
    assert EMPTY_GROUP in labels
    assert "True" in labels
    assert "2026-03-01" in labels
    assert board.lanes[-1].label == EMPTY_GROUP
    assert board.shown == 4
    titles = [item.title for lane in board.lanes for item in lane.items]
    assert long_text in titles
    assert EMPTY_GROUP in titles


def test_hidden_column_value_is_never_called() -> None:
    def boom(_row: Any) -> object:
        raise AssertionError("hidden column read")

    hidden = Column(key="secret", label="Нууц", value=boom, kind="text")
    rows = [_row("Бат", "Ачаа")]
    marks = (Mark(column="secret", rule_op="eq", value="x", colour="red"),)
    table = _table(rows, [NAME, DEPT])
    table.rows = rows
    board = layouts_mod.build_board(table, table.spec, marks, TODAY)
    assert board.shown == 1
    assert hidden.key not in {c.key for c in table.columns}


def test_card_order_across_lanes_follows_table_order_within_each_lane() -> None:
    rows = [_row("A1", "X"), _row("B1", "Y"), _row("A2", "X"), _row("B2", "Y"), _row("A3", "X")]
    board = layouts_mod.build_board(_table(rows), _table(rows).spec, (), TODAY)
    assert [lane.label for lane in board.lanes] == ["X", "Y"]
    assert [item.title for item in board.lanes[0].items] == ["A1", "A2", "A3"]
    assert [item.title for item in board.lanes[1].items] == ["B1", "B2"]


def test_cap_of_200_across_lanes_leaves_a_lane_with_count_and_no_cards() -> None:
    rows = [_row(f"A{i}", "Ачаа") for i in range(150)]
    rows += [_row(f"B{i}", "Бэлэн") for i in range(100)]
    rows += [_row(f"C{i}", "Санхүү") for i in range(10)]
    board = layouts_mod.build_board(_table(rows), _table(rows).spec, (), TODAY)
    by_label = {lane.label: lane for lane in board.lanes}
    assert board.total == 260
    assert board.shown == 200
    assert len(by_label["Ачаа"].items) == 150
    assert len(by_label["Бэлэн"].items) == 50
    assert by_label["Санхүү"].count == 10
    assert by_label["Санхүү"].items == []
    assert sum(len(lane.items) for lane in board.lanes) == 200


def test_whitespace_only_category_is_labelled_blank_and_kept_apart_from_the_empty_one() -> None:
    rows = [_row("А", "X"), _row("Б", "   "), _row("В", "")]
    board = layouts_mod.build_board(_table(rows), _table(rows).spec, (), TODAY)
    assert [lane.label for lane in board.lanes] == ["X", EMPTY_GROUP, EMPTY_GROUP]
    assert [lane.count for lane in board.lanes] == [1, 1, 1]


def test_money_column_extra_is_flagged_as_money() -> None:
    money_pay = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
    rows = [_row("А", "X", pay=900)]
    item = layouts_mod.make_items(_table(rows, [NAME, money_pay]), rows, (), TODAY, extras=1)[0]
    assert item.extras == (("Цалин", 900, True),)
