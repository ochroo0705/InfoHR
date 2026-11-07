"""The rule tree: parsing the address text, operators per kind, AND/OR evaluation, restriction and wording."""

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from reports.rules import (
    MAX_DEPTH,
    MAX_RULES,
    MAX_TEXT,
    MAX_VALUE,
    OP_LABELS,
    OPS,
    Group,
    Rule,
    describe_rules,
    dump_rules,
    keep_rows,
    parse_rules,
    restrict,
)
from reports.rules import (
    test_rule as check_rule,
)
from reports.types import Column

TODAY = date(2026, 11, 7)
LABELS = {"age": "Нас", "dept": "Хэлтэс", "name": "Нэр", "hired": "Огноо"}
KINDS = {"name": "text", "age": "number", "hired": "date", "salary": "number", "dept": "text"}


def _rule(op: str, value: str = "", column: str = "x") -> Rule:
    return Rule(column=column, op=op, value=value)


# ---- constants and the operator lists ----


def test_limits_are_the_agreed_numbers() -> None:
    assert (MAX_DEPTH, MAX_RULES, MAX_VALUE, MAX_TEXT) == (3, 20, 100, 2000)


def test_operator_lists_per_kind() -> None:
    assert OPS["text"] == ("contains", "not_contains", "eq", "neq", "starts", "empty", "filled")
    assert OPS["number"] == ("eq", "neq", "gt", "gte", "lt", "lte", "between", "empty", "filled")
    assert OPS["date"] == ("on", "before", "after", "between", "next_days", "last_days", "empty", "filled")


def test_every_operator_has_a_mongolian_label() -> None:
    codes = {code for ops in OPS.values() for code in ops}
    assert codes <= set(OP_LABELS)
    assert OP_LABELS["contains"] == "агуулсан"
    assert OP_LABELS["gte"] == "≥"


# ---- text operators ----


@pytest.mark.parametrize(
    ("rule", "value", "expected"),
    [
        (_rule("contains", "борл"), "Борлуулалт", True),
        (_rule("contains", "xyz"), "Борлуулалт", False),
        (_rule("not_contains", "xyz"), "Борлуулалт", True),
        (_rule("not_contains", "борл"), "Борлуулалт", False),
        (_rule("eq", "hr"), "HR", True),
        (_rule("eq", "hr"), "HRX", False),
        (_rule("neq", "HR"), "hr", False),
        (_rule("neq", "HR"), "Sales", True),
        (_rule("starts", "бор"), "Борлуулалт", True),
        (_rule("starts", "луу"), "Борлуулалт", False),
        (_rule("empty"), None, True),
        (_rule("empty"), "Борлуулалт", False),
        (_rule("filled"), "x", True),
        (_rule("filled"), "", False),
    ],
)
def test_text_operators(rule: Rule, value: object, expected: bool) -> None:
    assert check_rule(rule, value, "text", TODAY) is expected


def test_blank_text_cell_matches_neq_and_not_contains_only() -> None:
    assert check_rule(_rule("neq", "a"), "", "text", TODAY) is True
    assert check_rule(_rule("not_contains", "a"), None, "text", TODAY) is True
    assert check_rule(_rule("contains", "a"), None, "text", TODAY) is False
    assert check_rule(_rule("eq", "a"), None, "text", TODAY) is False
    assert check_rule(_rule("starts", "a"), None, "text", TODAY) is False


# ---- number operators ----


@pytest.mark.parametrize(
    ("rule", "value", "expected"),
    [
        (_rule("eq", "30"), Decimal("30.00"), True),
        (_rule("neq", "30"), 31, True),
        (_rule("neq", "30"), 30, False),
        (_rule("gt", "30"), 31, True),
        (_rule("gt", "30"), 30, False),
        (_rule("gte", "30"), 30, True),
        (_rule("lt", "30"), 29, True),
        (_rule("lt", "30"), 30, False),
        (_rule("lte", "30"), 30, True),
        (_rule("between", "20..40"), 30, True),
        (_rule("between", "20..40"), 41, False),
        (_rule("empty"), None, True),
        (_rule("empty"), 0, False),
        (_rule("filled"), 0, True),
    ],
)
def test_number_operators(rule: Rule, value: object, expected: bool) -> None:
    assert check_rule(rule, value, "number", TODAY) is expected


def test_blank_number_cell_matches_neq_only() -> None:
    assert check_rule(_rule("neq", "30"), None, "number", TODAY) is True
    assert check_rule(_rule("gt", "0"), None, "number", TODAY) is False
    assert check_rule(_rule("between", "0..9"), None, "number", TODAY) is False


def test_between_with_reversed_pair_swaps_the_bounds() -> None:
    assert check_rule(_rule("between", "40..20"), 30, "number", TODAY) is True
    assert check_rule(_rule("between", "40..20"), 41, "number", TODAY) is False


def test_unreadable_number_cell_is_none() -> None:
    assert check_rule(_rule("gt", "5"), "abc", "number", TODAY) is None


def test_unreadable_rule_value_is_none() -> None:
    assert check_rule(_rule("gt", "много"), 7, "number", TODAY) is None


# ---- date operators ----


@pytest.mark.parametrize(
    ("rule", "value", "expected"),
    [
        (_rule("on", "2026-11-07"), date(2026, 11, 7), True),
        (_rule("on", "2026-11-07"), date(2026, 11, 8), False),
        (_rule("before", "2026-11-07"), date(2026, 11, 6), True),
        (_rule("before", "2026-11-07"), date(2026, 11, 7), False),
        (_rule("after", "2026-11-07"), date(2026, 11, 8), True),
        (_rule("after", "2026-11-07"), date(2026, 11, 7), False),
        (_rule("between", "2026-11-01..2026-11-10"), date(2026, 11, 5), True),
        (_rule("between", "2026-11-10..2026-11-01"), date(2026, 11, 5), True),
        (_rule("between", "2026-11-01..2026-11-10"), date(2026, 12, 1), False),
        (_rule("empty"), None, True),
        (_rule("filled"), date(2026, 11, 7), True),
    ],
)
def test_date_operators(rule: Rule, value: object, expected: bool) -> None:
    assert check_rule(rule, value, "date", TODAY) is expected


def test_next_days_includes_today_and_today_plus_n() -> None:
    rule = _rule("next_days", "7")
    assert check_rule(rule, TODAY, "date", TODAY) is True
    assert check_rule(rule, TODAY + timedelta(days=7), "date", TODAY) is True
    assert check_rule(rule, TODAY + timedelta(days=8), "date", TODAY) is False
    assert check_rule(rule, TODAY - timedelta(days=1), "date", TODAY) is False


def test_last_days_includes_today_minus_n_and_today() -> None:
    rule = _rule("last_days", "7")
    assert check_rule(rule, TODAY, "date", TODAY) is True
    assert check_rule(rule, TODAY - timedelta(days=7), "date", TODAY) is True
    assert check_rule(rule, TODAY - timedelta(days=8), "date", TODAY) is False
    assert check_rule(rule, TODAY + timedelta(days=1), "date", TODAY) is False


def test_datetime_cell_counts_as_its_date() -> None:
    assert check_rule(_rule("on", "2026-11-07"), datetime(2026, 11, 7, 9, 30), "date", TODAY) is True


def test_unreadable_date_cell_is_none() -> None:
    assert check_rule(_rule("before", "2026-11-07"), "not a date", "date", TODAY) is None


def test_bad_day_count_is_none() -> None:
    assert check_rule(_rule("next_days", "много"), TODAY, "date", TODAY) is None
    assert check_rule(_rule("last_days", "-3"), TODAY, "date", TODAY) is None


def test_operator_not_offered_for_the_kind_is_none() -> None:
    assert check_rule(_rule("gt", "1"), "x", "text", TODAY) is None
    assert check_rule(_rule("next_days", "1"), 5, "number", TODAY) is None
    assert check_rule(_rule("eq", "1"), "x", "unknown-kind", TODAY) is None


# ---- rows, AND / OR, nesting ----

PEOPLE = [
    SimpleNamespace(name="Болд", age=35, hired=date(2026, 11, 5), salary=900, dept="Борлуулалт"),
    SimpleNamespace(name="Сараа", age=25, hired=None, salary=500, dept="HR"),
    SimpleNamespace(name="Дорж", age=None, hired=date(2026, 1, 1), salary=700, dept=None),
]


def _getter(key: str) -> Callable[[Any], object]:
    return lambda r: getattr(r, key)


def _columns() -> dict[str, Column]:
    return {key: Column(key=key, label=key, value=_getter(key)) for key in KINDS}


def _keep(group: Group | None) -> list[str]:
    rows = keep_rows(PEOPLE, group, _columns(), KINDS, TODAY)
    return [row.name for row in rows]


def test_no_group_keeps_every_row() -> None:
    assert _keep(None) == ["Болд", "Сараа", "Дорж"]


def test_and_group_needs_every_rule() -> None:
    group = Group("and", (_rule("gte", "30", "age"), _rule("starts", "бол", "name")))
    assert _keep(group) == ["Болд"]


def test_or_group_needs_one_rule() -> None:
    group = Group("or", (_rule("lt", "30", "age"), _rule("eq", "болд", "name")))
    assert _keep(group) == ["Болд", "Сараа"]


def test_blank_cell_passes_neq_and_fails_gt() -> None:
    assert _keep(Group("and", (_rule("neq", "30", "age"),))) == ["Болд", "Сараа", "Дорж"]
    assert _keep(Group("and", (_rule("gt", "0", "age"),))) == ["Болд", "Сараа"]


def test_date_on_skips_blank_dates() -> None:
    assert _keep(Group("and", (_rule("on", "2026-11-05", "hired"),))) == ["Болд"]


def test_nested_and_or_evaluation() -> None:
    inner = Group("or", (_rule("eq", "сараа", "name"), _rule("gte", "800", "salary")))
    group = Group("and", (_rule("gte", "30", "age"), inner))
    assert _keep(group) == ["Болд"]


def test_rule_on_a_column_not_loaded_is_ignored() -> None:
    assert _keep(Group("and", (_rule("eq", "1", "missing"),))) == ["Болд", "Сараа", "Дорж"]


def test_group_of_only_ignored_rules_keeps_every_row() -> None:
    group = Group("or", (_rule("gt", "много", "age"),))
    assert _keep(group) == ["Болд", "Сараа", "Дорж"]


# ---- parsing the address text ----


def test_empty_and_invalid_text_give_none() -> None:
    assert parse_rules("") is None
    assert parse_rules("not json") is None
    assert parse_rules("[]") is None
    assert parse_rules('{"op":"xor"}') is None
    assert parse_rules('{"op":"and","items":[]}') is None
    assert parse_rules('{"op":"and","items":[5]}') is None
    assert parse_rules('{"op":"and","items":"x"}') is None


def test_valid_text_becomes_a_group() -> None:
    text = '{"op":"and","items":[{"c":"age","o":"gte","v":"30"}]}'
    assert parse_rules(text) == Group("and", (Rule("age", "gte", "30"),))


def test_unknown_operator_is_dropped() -> None:
    text = '{"op":"and","items":[{"c":"age","o":"zzz","v":"1"},{"c":"age","o":"eq","v":"1"}]}'
    assert parse_rules(text) == Group("and", (Rule("age", "eq", "1"),))


def test_group_left_empty_after_dropping_is_pruned() -> None:
    text = '{"op":"and","items":[{"op":"or","items":[{"c":"a","o":"zzz"}]},{"c":"b","o":"eq","v":"1"}]}'
    assert parse_rules(text) == Group("and", (Rule("b", "eq", "1"),))


def test_unknown_group_operator_drops_that_group() -> None:
    text = '{"op":"and","items":[{"op":"xor","items":[{"c":"a","o":"eq","v":"1"}]},{"c":"b","o":"eq","v":"2"}]}'
    assert parse_rules(text) == Group("and", (Rule("b", "eq", "2"),))


def _nested(depth: int) -> str:
    """A chain of `depth` AND groups, with one rule inside the deepest."""
    node: dict[str, object] = {"c": "age", "o": "eq", "v": "1"}
    for _ in range(depth):
        node = {"op": "and", "items": [node]}
    return json.dumps(node)


def test_depth_three_is_allowed_and_depth_four_is_not() -> None:
    expected = Group("and", (Group("and", (Group("and", (Rule("age", "eq", "1"),)),)),))
    assert parse_rules(_nested(3)) == expected
    assert parse_rules(_nested(4)) is None


def _many_rules(count: int) -> str:
    items = [{"c": "age", "o": "eq", "v": str(i)} for i in range(count)]
    return json.dumps({"op": "and", "items": items})


def test_twenty_rules_allowed_twenty_one_not() -> None:
    assert parse_rules(_many_rules(20)) is not None
    assert parse_rules(_many_rules(21)) is None


def test_value_of_100_chars_allowed_101_not() -> None:
    ok = json.dumps({"op": "and", "items": [{"c": "name", "o": "eq", "v": "a" * 100}]})
    too_long = json.dumps({"op": "and", "items": [{"c": "name", "o": "eq", "v": "a" * 101}]})
    assert parse_rules(ok) is not None
    assert parse_rules(too_long) is None


def test_text_over_2000_chars_is_refused() -> None:
    valid = '{"op":"and","items":[{"c":"age","o":"eq","v":"1"}]}'
    assert parse_rules(valid + " " * 2000) is None


def test_text_of_exactly_2000_chars_is_accepted_and_2001_refused() -> None:
    base = '{"op":"and","items":[{"c":"name","o":"eq","v":"' + "a" * 100 + '"}]}'
    exact = base + " " * (2000 - len(base))
    assert len(exact) == 2000
    assert parse_rules(exact) is not None
    assert parse_rules(exact + " ") is None


# ---- odd value types and huge or bad numbers ----


def test_integer_and_float_values_become_text() -> None:
    assert parse_rules('{"op":"and","items":[{"c":"age","o":"gte","v":30}]}') == Group(
        "and", (Rule("age", "gte", "30"),)
    )
    assert parse_rules('{"op":"and","items":[{"c":"age","o":"lt","v":2.5}]}') == Group(
        "and", (Rule("age", "lt", "2.5"),)
    )


def test_bool_or_list_value_drops_only_that_rule() -> None:
    text = (
        '{"op":"and","items":['
        '{"c":"age","o":"gte","v":true},'
        '{"c":"age","o":"gte","v":[1]},'
        '{"c":"age","o":"gte","v":{"x":1}},'
        '{"c":"age","o":"gte","v":null},'
        '{"c":"age","o":"eq","v":"1"}]}'
    )
    assert parse_rules(text) == Group("and", (Rule("age", "eq", "1"),))


def test_wrong_value_type_is_fine_for_an_operator_with_no_value() -> None:
    text = '{"op":"and","items":[{"c":"name","o":"empty","v":true},{"c":"age","o":"eq","v":"1"}]}'
    assert parse_rules(text) == Group("and", (Rule("name", "empty", ""), Rule("age", "eq", "1")))


def test_huge_day_count_is_inactive_not_an_error() -> None:
    for op in ("next_days", "last_days"):
        for count in ("36501", "3000000", "999999999", "9" * 100):
            assert check_rule(_rule(op, count), TODAY, "date", TODAY) is None


def test_day_count_at_the_cap_is_active() -> None:
    assert check_rule(_rule("next_days", "36500"), TODAY, "date", TODAY) is True
    assert check_rule(_rule("last_days", "36500"), TODAY, "date", TODAY) is True


def test_huge_day_count_in_a_tree_keeps_every_row_without_raising() -> None:
    group = Group("and", (_rule("next_days", "3000000", "hired"),))
    assert _keep(group) == ["Болд", "Сараа", "Дорж"]


def test_negative_day_count_is_inactive() -> None:
    assert check_rule(_rule("next_days", "-3"), TODAY, "date", TODAY) is None
    assert check_rule(_rule("last_days", "-3"), TODAY, "date", TODAY) is None


def test_underscore_and_space_numbers_are_unreadable() -> None:
    assert check_rule(_rule("eq", "1_000"), 1000, "number", TODAY) is None
    assert check_rule(_rule("eq", "1000"), "1_000", "number", TODAY) is None
    assert check_rule(_rule("eq", " 30"), 30, "number", TODAY) is None
    assert check_rule(_rule("next_days", "1_0"), TODAY, "date", TODAY) is None
    assert check_rule(_rule("next_days", " 7"), TODAY, "date", TODAY) is None


def test_between_with_one_unreadable_side_is_inactive() -> None:
    assert check_rule(_rule("between", "20..abc"), 25, "number", TODAY) is None
    assert check_rule(_rule("between", "abc..40"), 25, "number", TODAY) is None


def test_between_with_an_open_side() -> None:
    assert check_rule(_rule("between", "20.."), 25, "number", TODAY) is True
    assert check_rule(_rule("between", "20.."), 19, "number", TODAY) is False
    assert check_rule(_rule("between", "..40"), 41, "number", TODAY) is False
    assert check_rule(_rule("between", "..40"), 40, "number", TODAY) is True
    assert check_rule(_rule("between", ".."), 25, "number", TODAY) is None


def test_bad_date_format_is_inactive() -> None:
    assert check_rule(_rule("on", "2026-13-45"), date(2026, 11, 7), "date", TODAY) is None
    assert check_rule(_rule("between", "2026-13-45..2026-12-01"), date(2026, 11, 7), "date", TODAY) is None


def test_dump_none_is_empty_text() -> None:
    assert dump_rules(None) == ""


def test_dump_writes_compact_json_with_short_keys() -> None:
    group = Group("and", (Rule("age", "gte", "30"),))
    assert dump_rules(group) == '{"op":"and","items":[{"c":"age","o":"gte","v":"30"}]}'


def test_dump_then_parse_gives_the_same_tree() -> None:
    group = Group(
        "and",
        (
            Rule("name", "contains", "Борлуулалт"),
            Group("or", (Rule("age", "lt", "30"), Rule("hired", "empty", ""))),
        ),
    )
    assert parse_rules(dump_rules(group)) == group


# ---- restriction to allowed columns ----


def test_restrict_drops_other_columns_and_prunes_emptied_groups() -> None:
    group = Group(
        "and",
        (
            Rule("name", "eq", "Болд"),
            Group("or", (Rule("salary", "gte", "800"), Rule("salary", "lt", "100"))),
        ),
    )
    assert restrict(group, {"name"}) == Group("and", (Rule("name", "eq", "Болд"),))


def test_restrict_with_nothing_allowed_is_none() -> None:
    assert restrict(Group("and", (Rule("salary", "gte", "1"),)), {"name"}) is None
    assert restrict(None, {"name"}) is None


# ---- wording ----


def test_describe_two_rules_joined_by_ba() -> None:
    group = Group("and", (Rule("age", "gte", "30"), Rule("dept", "contains", "борлуулалт")))
    assert describe_rules(group, LABELS) == "Нас ≥ 30 ба Хэлтэс агуулсан борлуулалт"


def test_describe_nested_or_group_in_brackets() -> None:
    group = Group(
        "and",
        (
            Rule("name", "eq", "Болд"),
            Group("or", (Rule("age", "lt", "30"), Rule("dept", "empty", ""))),
        ),
    )
    assert describe_rules(group, LABELS) == "Нэр тэнцүү Болд ба (Нас < 30 эсвэл Хэлтэс хоосон)"


def test_describe_next_days_puts_the_number_in_the_label() -> None:
    assert describe_rules(Group("and", (Rule("hired", "next_days", "7"),)), LABELS) == "Огноо ирэх 7 хоногт"


def test_describe_none_is_empty_text() -> None:
    assert describe_rules(None, LABELS) == ""


# ---- lone surrogates from JSON escapes cannot be written as UTF-8: the whole tree is refused ----


def test_lone_surrogate_in_a_rule_value_refuses_the_tree() -> None:
    text = '{"op":"and","items":[{"c":"a","o":"contains","v":"\\ud800"}]}'
    assert parse_rules(text) is None


def test_lone_surrogate_in_a_column_key_refuses_the_tree() -> None:
    text = '{"op":"and","items":[{"c":"\\udc00","o":"eq","v":"1"}]}'
    assert parse_rules(text) is None


def test_lone_surrogate_in_a_nested_group_refuses_the_whole_tree() -> None:
    text = '{"op":"and","items":[{"c":"age","o":"eq","v":"1"},{"op":"or","items":[{"c":"a","o":"eq","v":"\\ud800"}]}]}'
    assert parse_rules(text) is None


def test_valid_unicode_escape_is_still_accepted() -> None:
    text = '{"op":"and","items":[{"c":"name","o":"contains","v":"\\u0411"}]}'
    assert parse_rules(text) == Group("and", (Rule("name", "contains", "Б"),))


# ---- a blank cell is judged by the operator alone, whatever the column's kind ----


def test_blank_cell_on_a_text_kind_is_false_for_a_date_operator() -> None:
    assert check_rule(Rule("contract_end", "next_days", "60"), None, "text", TODAY) is False
    assert check_rule(Rule("contract_end", "next_days", "60"), "", "text", TODAY) is False


def test_blank_cell_on_a_text_kind_is_true_for_empty() -> None:
    assert check_rule(Rule("contract_end", "empty", ""), None, "text", TODAY) is True


def test_blank_cell_on_a_text_kind_is_false_for_a_number_operator() -> None:
    assert check_rule(Rule("age", "gte", "55"), None, "text", TODAY) is False


def test_blank_cell_is_true_for_neq_and_not_contains_whatever_the_kind() -> None:
    assert check_rule(Rule("age", "neq", "55"), None, "date", TODAY) is True
    assert check_rule(Rule("name", "not_contains", "Бат"), "  ", "text", TODAY) is True


def test_whitespace_only_text_cell_counts_as_blank() -> None:
    assert check_rule(Rule("age", "gte", "55"), "   ", "number", TODAY) is False


def test_non_blank_date_operator_on_a_text_kind_is_still_none() -> None:
    assert check_rule(Rule("contract_end", "next_days", "60"), "2026-11-10", "text", TODAY) is None


def test_unknown_operator_is_none_even_for_a_blank_cell() -> None:
    assert check_rule(Rule("age", "bogus", "55"), None, "text", TODAY) is None
