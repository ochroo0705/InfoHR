"""Click-through rules: one category as a rule, and the raw category key behind every drawn chart bar, pivot cell and
board lane."""

from datetime import date
from types import SimpleNamespace
from typing import Any

from reports import drill as drill_mod
from reports import layouts as layouts_mod
from reports import rules as rules_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.rules import Group, Rule
from reports.table import Table
from reports.types import Column

DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
LEVEL = Column(key="level", label="Түвшин", value=lambda r: r.level, kind="text")
GENDER = Column(key="gender", label="Хүйс", value=lambda r: r.gender, kind="text")
NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)


def _row(name: str = "", dept: object = None, level: object = "A", gender: object = "Эр", pay: object = 0) -> Any:
    return SimpleNamespace(name=name, dept=dept, level=level, gender=gender, pay=pay)


# ---- Part A: one category as a condition ----


def test_text_condition_is_an_eq_rule() -> None:
    assert drill_mod.condition("department", "text", "Борлуулалт") == rules_mod.Rule("department", "eq", "Борлуулалт")


def test_number_condition_is_an_eq_rule() -> None:
    rule = drill_mod.condition("age", "number", "35")
    assert rule is not None
    assert rule.op == "eq"
    assert rule.value == "35"


def test_date_condition_is_an_on_rule() -> None:
    rule = drill_mod.condition("hired", "date", "2026-01-05")
    assert rule is not None
    assert rule.op == "on"
    assert rule.value == "2026-01-05"


def test_blank_and_spaces_only_keys_are_the_empty_rule() -> None:
    assert drill_mod.condition("department", "text", "") == rules_mod.Rule("department", "empty", "")
    assert drill_mod.condition("department", "text", "   ") == rules_mod.Rule("department", "empty", "")


def test_unknown_kind_gives_none() -> None:
    assert drill_mod.condition("x", "weird", "a") is None


def test_key_longer_than_the_rule_value_limit_gives_none() -> None:
    assert drill_mod.condition("department", "text", "а" * 101) is None


def test_unknown_kind_gives_none_even_for_a_blank_key() -> None:
    assert drill_mod.condition("x", "weird", "  ") is None


def test_datetime_text_the_rule_engine_cannot_read_gives_none() -> None:
    # an inactive «on» rule would keep every row, so no rule is built
    assert drill_mod.condition("d", "date", "2026-01-05T10:00:00") is None


def test_number_text_the_rule_engine_cannot_read_gives_none() -> None:
    assert drill_mod.condition("n", "number", "True") is None


def test_readable_date_and_number_keys_are_still_rules() -> None:
    assert drill_mod.condition("d", "date", "2026-01-05") == rules_mod.Rule("d", "on", "2026-01-05")
    assert drill_mod.condition("n", "number", "1.50") == rules_mod.Rule("n", "eq", "1.50")


def test_collisions_are_case_and_blank_variants_of_one_another() -> None:
    assert drill_mod.collisions(["a", "A", "b", None]) == {"a", "A"}
    assert drill_mod.collisions(["", "   ", "x"]) == {"", "   "}


def test_a_repeated_identical_key_is_one_bucket_not_a_collision() -> None:
    assert drill_mod.collisions(["a", "a", "b"]) == set()


def test_no_keys_have_no_collisions() -> None:
    assert drill_mod.collisions([]) == set()


def test_text_rule_keeps_both_case_variants_which_is_why_collisions_matter() -> None:
    # the rule is case-insensitive: "a" also keeps the "A" bucket, so the caller must not link either one
    rows = [{"department": "a"}, {"department": "A"}, {"department": "B"}]
    cols = {"department": Column(key="department", label="Хэлтэс", value=lambda r: r["department"])}
    rule = drill_mod.condition("department", "text", "a")
    kept = rules_mod.keep_rows(
        rows, rules_mod.parse_rules(drill_mod.drill_rules("", [rule])), cols, {"department": "text"}, date(2026, 11, 7)
    )
    assert kept == [{"department": "a"}, {"department": "A"}]


def test_drill_rules_without_conditions_is_empty() -> None:
    assert drill_mod.drill_rules("", []) == ""


def test_drill_rules_with_no_existing_tree_is_one_and_group() -> None:
    text = drill_mod.drill_rules("", [Rule("department", "eq", "A")])
    assert rules_mod.parse_rules(text) == Group(op="and", items=(Rule("department", "eq", "A"),))


def test_drill_rules_appends_to_an_existing_and_group() -> None:
    existing = rules_mod.dump_rules(Group(op="and", items=(Rule("level", "eq", "B"),)))
    text = drill_mod.drill_rules(existing, [Rule("department", "eq", "A")])
    assert rules_mod.parse_rules(text) == Group(
        op="and", items=(Rule("level", "eq", "B"), Rule("department", "eq", "A"))
    )


def test_drill_rules_wraps_an_existing_or_group() -> None:
    or_group = Group(op="or", items=(Rule("level", "eq", "A"), Rule("level", "eq", "B")))
    text = drill_mod.drill_rules(rules_mod.dump_rules(or_group), [Rule("department", "eq", "A")])
    assert rules_mod.parse_rules(text) == Group(op="and", items=(or_group, Rule("department", "eq", "A")))


def test_drill_rules_refuses_when_the_rule_limit_would_be_passed() -> None:
    full = Group(op="and", items=tuple(Rule("level", "eq", str(i)) for i in range(rules_mod.MAX_RULES)))
    assert drill_mod.drill_rules(rules_mod.dump_rules(full), [Rule("department", "eq", "A")]) == ""


def test_drill_rules_refuses_when_the_depth_would_be_passed() -> None:
    # three nested OR groups already reach MAX_DEPTH; the AND wrapper would need one level more
    deepest = Group(op="or", items=(Rule("level", "eq", "A"), Rule("level", "eq", "B")))
    nested = Group(op="or", items=(Group(op="or", items=(deepest,)),))
    assert rules_mod.MAX_DEPTH == 3
    assert drill_mod.drill_rules(rules_mod.dump_rules(nested), [Rule("department", "eq", "A")]) == ""


def test_drill_rules_really_filter_the_rows() -> None:
    rows = [{"department": "A"}, {"department": "B"}, {"department": "A"}]
    cols = {"department": Column(key="department", label="Хэлтэс", value=lambda r: r["department"])}
    kinds = {"department": "text"}
    text = drill_mod.drill_rules("", [drill_mod.condition("department", "text", "A")])
    kept = rules_mod.keep_rows(rows, rules_mod.parse_rules(text), cols, kinds, date(2026, 11, 7))
    assert kept == [{"department": "A"}, {"department": "A"}]

    blank_text = drill_mod.drill_rules("", [drill_mod.condition("department", "text", "")])
    blank_rows = [{"department": None}, {"department": ""}, {"department": "A"}]
    kept_blank = rules_mod.keep_rows(blank_rows, rules_mod.parse_rules(blank_text), cols, kinds, date(2026, 11, 7))
    assert kept_blank == [{"department": None}, {"department": ""}]


# ---- Part B: the raw category keys ----


def _spec(layout: str, chart: str = "bar", by: Column | None = DEPT, by2: Column | None = None) -> LayoutSpec:
    return LayoutSpec(layout=layout, by=by, by2=by2, value=(None, "count"), chart=chart, month=date(2026, 11, 1))


def _chart(rows: list[Any], spec: LayoutSpec) -> Any:
    table = Table(
        columns=[NAME, DEPT, LEVEL, GENDER, PAY], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec
    )
    return layouts_mod.build_chart(table, spec)


def test_chart_keys_follow_the_label_order() -> None:
    rows = [_row(dept="Санхүү"), _row(dept="ачаа"), _row(dept="Ачаа")]
    chart = _chart(rows, _spec("chart"))
    assert [p.label for p in chart.points] == ["ачаа", "Ачаа", "Санхүү"]
    assert chart.keys == ["ачаа", "Ачаа", "Санхүү"]


def test_blank_chart_category_has_the_empty_key_and_the_dash_label() -> None:
    rows = [_row(dept=None), _row(dept="A")]
    chart = _chart(rows, _spec("chart"))
    assert chart.points[-1].label == layouts_mod.EMPTY_GROUP
    assert chart.keys == ["A", ""]


def test_folded_chart_last_key_is_none_and_last_label_is_folded() -> None:
    rows = [_row(dept=f"D{i:02d}") for i in range(layouts_mod.CHART_CAP + 4)]
    chart = _chart(rows, _spec("chart"))
    assert len(chart.keys) == layouts_mod.CHART_CAP
    assert chart.keys[-1] is None
    assert chart.keys[:-1] == [f"D{i:02d}" for i in range(layouts_mod.CHART_CAP - 1)]
    assert chart.points[-1].label == layouts_mod.FOLDED


def test_stacked_chart_has_one_series_key_per_series() -> None:
    # the blank gender shows as «—» but its key stays "", so the key and the label must differ here
    rows = [_row(dept="A", gender="Эр"), _row(dept="A", gender=""), _row(dept="B", gender="Эм")]
    chart = _chart(rows, _spec("chart", chart="stacked", by2=GENDER))
    assert [s.label for s in chart.series] == ["Эм", "Эр", layouts_mod.EMPTY_GROUP]
    assert chart.series_keys == ["Эм", "Эр", ""]
    assert len(chart.series_keys) == len(chart.series)
    assert chart.keys == ["A", "B"]


def test_plain_chart_has_no_series_keys() -> None:
    chart = _chart([_row(dept="A")], _spec("chart", chart="stacked"))
    assert chart.series_keys == []


def test_folded_stack_last_series_key_is_none() -> None:
    rows = [_row(dept="A", gender=f"G{i:02d}") for i in range(layouts_mod.STACK_CAP + 2)]
    chart = _chart(rows, _spec("chart", chart="stacked", by2=GENDER))
    assert len(chart.series_keys) == layouts_mod.STACK_CAP
    assert chart.series_keys[-1] is None


def _pivot(rows: list[Any], by2: Column | None) -> Any:
    spec = _spec("pivot", by2=by2)
    table = Table(
        columns=[NAME, DEPT, LEVEL, GENDER, PAY], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec
    )
    return layouts_mod.build_pivot(table, spec)


def test_pivot_keys_line_up_with_the_labels() -> None:
    rows = [_row(dept="B", level="X"), _row(dept="A", level="Y"), _row(dept=None, level="X")]
    pivot = _pivot(rows, by2=LEVEL)
    assert pivot.row_keys == ["A", "B", ""]
    assert [layouts_mod._label(k) for k in pivot.row_keys] == pivot.row_labels
    assert pivot.col_keys == ["X", "Y"]
    assert [layouts_mod._label(k) for k in pivot.col_keys] == pivot.col_labels


def test_pivot_without_by2_has_one_none_column_key() -> None:
    pivot = _pivot([_row(dept="A"), _row(dept="B")], by2=None)
    assert pivot.col_keys == [None]
    assert pivot.col_labels == [layouts_mod.TOTAL_COLUMN]


def test_folded_pivot_rows_end_with_none() -> None:
    rows = [_row(dept=f"D{i:02d}") for i in range(layouts_mod.PIVOT_ROW_CAP + 3)]
    pivot = _pivot(rows, by2=None)
    assert len(pivot.row_keys) == layouts_mod.PIVOT_ROW_CAP
    assert pivot.row_keys[-1] is None


def _board(rows: list[Any]) -> Any:
    spec = _spec("board")
    table = Table(columns=[NAME, DEPT, PAY], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)
    return layouts_mod.build_board(table, spec, [], date(2026, 11, 7))


def test_board_lane_keys_are_the_raw_text() -> None:
    rows = [_row(name="Бат", dept="Санхүү"), _row(name="Дорж", dept="Ачаа"), _row(name="Оюу", dept=None)]
    board = _board(rows)
    assert [lane.key for lane in board.lanes] == ["Ачаа", "Санхүү", ""]
    assert [lane.label for lane in board.lanes] == ["Ачаа", "Санхүү", layouts_mod.EMPTY_GROUP]


def test_board_blank_lane_key_is_empty_text() -> None:
    board = _board([_row(name="Бат", dept="   ")])
    assert board.lanes[0].key == "   "
    assert board.lanes[0].label == layouts_mod.EMPTY_GROUP
