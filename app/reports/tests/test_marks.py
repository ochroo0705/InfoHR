"""Conditional colours: the address text, the dump, and the first matching mark for a cell."""

import json
from datetime import date
from decimal import Decimal

import pytest

from reports.marks import COLOURS, MAX_MARKS, Mark, dump_marks, mark_for, parse_marks

TODAY = date(2026, 11, 7)


# ---- constants ----


def test_colours_are_the_agreed_classes() -> None:
    assert COLOURS == {
        "red": "bg-red-50 text-red-700",
        "amber": "bg-amber-50 text-amber-800",
        "green": "bg-green-50 text-green-700",
        "blue": "bg-blue-50 text-blue-700",
        "grey": "bg-slate-100 text-slate-600",
    }


def test_at_most_five_marks() -> None:
    assert MAX_MARKS == 5


# ---- parsing ----


def test_parse_good_text() -> None:
    text = '[{"c":"salary","o":"gte","v":"800","k":"red"}]'
    assert parse_marks(text) == (Mark("salary", "gte", "800", "red"),)


@pytest.mark.parametrize("text", ["", None, "[]"])
def test_parse_empty_gives_nothing(text: str) -> None:
    assert parse_marks(text) == ()


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "{}",
        '"x"',
        "[1,2]",
        '[{"c":"a"}]',  # no operator, no colour
        '[{"c":"a","o":"gte","v":"1","k":"purple"}]',  # unknown colour
        '[{"c":"a","o":"zzz","v":"1","k":"red"}]',  # unknown operator
        '[{"c":"a","o":["gte"],"v":"1","k":"red"}]',  # operator is a list, not text
        '[{"c":"a","o":"gte","v":"1","k":["red"]}]',  # colour is a list, not text
        '[{"c":5,"o":"gte","v":"1","k":"red"}]',  # column is not text
    ],
)
def test_parse_garbage_items_are_dropped(text: str) -> None:
    assert parse_marks(text) == ()


def test_parse_keeps_the_good_items_next_to_garbage() -> None:
    text = '[{"c":"a"},{"c":"b","o":"eq","v":"1","k":"green"},7,{"c":"c","o":"eq","v":"2","k":"nope"}]'
    assert parse_marks(text) == (Mark("b", "eq", "1", "green"),)


def test_parse_number_value_becomes_text() -> None:
    assert parse_marks('[{"c":"a","o":"gte","v":800,"k":"red"}]') == (Mark("a", "gte", "800", "red"),)
    assert parse_marks('[{"c":"a","o":"lt","v":2.5,"k":"red"}]') == (Mark("a", "lt", "2.5", "red"),)


@pytest.mark.parametrize("value", [True, [1], {"x": 1}, None])
def test_parse_other_value_types_drop_the_mark(value: object) -> None:
    text = json.dumps([{"c": "a", "o": "gte", "v": value, "k": "red"}])
    assert parse_marks(text) == ()


def test_parse_missing_value_is_empty_text() -> None:
    assert parse_marks('[{"c":"a","o":"filled","k":"blue"}]') == (Mark("a", "filled", "", "blue"),)


def test_parse_caps_the_value_at_the_rule_limit() -> None:
    text = json.dumps([{"c": "a", "o": "eq", "v": "x" * 150, "k": "red"}])
    assert parse_marks(text) == (Mark("a", "eq", "x" * 100, "red"),)


def test_parse_at_most_five_marks() -> None:
    items = [{"c": f"col{i}", "o": "eq", "v": "1", "k": "red"} for i in range(7)]
    marks = parse_marks(json.dumps(items))
    assert len(marks) == 5
    assert marks[0].column == "col0"
    assert marks[4].column == "col4"


def test_parse_over_two_thousand_characters_is_refused() -> None:
    valid = '[{"c":"salary","o":"gte","v":"800","k":"red"}]'
    assert parse_marks(valid) == (Mark("salary", "gte", "800", "red"),)  # the same list is fine on its own
    padded = valid + " " * 2000  # still valid JSON (trailing spaces), so only the length check refuses it
    assert len(padded) > 2000
    assert parse_marks(padded) == ()


def test_parse_never_raises_on_odd_types() -> None:
    assert parse_marks(123) == ()  # type: ignore[arg-type]
    assert parse_marks(["x"]) == ()  # type: ignore[arg-type]


# ---- dumping ----


def test_dump_empty_is_empty_text() -> None:
    assert dump_marks(()) == ""


def test_dump_writes_compact_json_with_short_keys() -> None:
    marks = (Mark("salary", "gte", "800", "red"),)
    assert dump_marks(marks) == '[{"c":"salary","o":"gte","v":"800","k":"red"}]'


def test_dump_then_parse_gives_the_same_marks() -> None:
    marks = (Mark("salary", "gte", "800", "red"), Mark("hired", "next_days", "7", "amber"))
    assert parse_marks(dump_marks(marks)) == marks


# ---- the colour of one cell ----


def test_mark_for_returns_the_classes_of_a_matching_mark() -> None:
    marks = (Mark("salary", "gte", "800", "red"),)
    assert mark_for(marks, "salary", 900, "number", TODAY) == COLOURS["red"]


def test_mark_for_takes_the_first_matching_mark_in_order() -> None:
    marks = (Mark("salary", "gte", "800", "red"), Mark("salary", "gte", "500", "green"))
    assert mark_for(marks, "salary", 900, "number", TODAY) == COLOURS["red"]
    assert mark_for(marks, "salary", 600, "number", TODAY) == COLOURS["green"]


def test_mark_for_no_match_is_empty_text() -> None:
    marks = (Mark("salary", "gte", "800", "red"),)
    assert mark_for(marks, "salary", 100, "number", TODAY) == ""


def test_mark_for_no_marks_is_empty_text() -> None:
    assert mark_for((), "salary", 900, "number", TODAY) == ""


def test_mark_for_ignores_marks_on_other_columns() -> None:
    marks = (Mark("age", "gte", "0", "blue"),)
    assert mark_for(marks, "salary", 900, "number", TODAY) == ""


def test_mark_for_operator_not_valid_for_the_kind_gives_no_mark() -> None:
    marks = (Mark("name", "gt", "1", "red"),)
    assert mark_for(marks, "name", "Болд", "text", TODAY) == ""


def test_mark_for_text_operator_on_a_number_column_gives_no_mark() -> None:
    marks = (Mark("salary", "contains", "9", "red"),)
    assert mark_for(marks, "salary", 900, "number", TODAY) == ""


def test_mark_for_blank_cell_with_empty_operator() -> None:
    marks = (Mark("dept", "empty", "", "grey"),)
    assert mark_for(marks, "dept", None, "text", TODAY) == COLOURS["grey"]


def test_mark_for_date_operator_uses_today() -> None:
    marks = (Mark("hired", "next_days", "7", "amber"),)
    assert mark_for(marks, "hired", TODAY, "date", TODAY) == COLOURS["amber"]
    assert mark_for(marks, "hired", date(2026, 12, 1), "date", TODAY) == ""


def test_mark_for_decimal_cell_on_a_number_mark() -> None:
    marks = (Mark("salary", "lt", "1000", "blue"),)
    assert mark_for(marks, "salary", Decimal("999.50"), "number", TODAY) == COLOURS["blue"]


# ---- a lone surrogate in a value or column drops only that mark ----


def test_parse_drops_a_mark_with_a_lone_surrogate_value() -> None:
    text = '[{"c":"a","o":"contains","v":"\\ud800","k":"red"},{"c":"b","o":"eq","v":"1","k":"green"}]'
    assert parse_marks(text) == (Mark("b", "eq", "1", "green"),)


def test_parse_drops_a_mark_with_a_lone_surrogate_column() -> None:
    text = '[{"c":"\\udc00","o":"eq","v":"1","k":"red"}]'
    assert parse_marks(text) == ()


def test_blank_cell_in_an_all_blank_column_gets_no_comparison_colour() -> None:
    marks = (Mark("hired", "next_days", "30", "amber"), Mark("hired", "empty", "", "grey"))
    assert mark_for(marks, "hired", None, "text", TODAY) == COLOURS["grey"]
    assert mark_for((Mark("hired", "next_days", "30", "amber"),), "hired", None, "text", TODAY) == ""
