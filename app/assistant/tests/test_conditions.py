"""Tests for the settle step's conditions: a condition the staff table can apply becomes a rule in the query, and a
condition it cannot apply is dropped with a line that says why. A hidden column and a column that does not exist get
the same line."""

from collections.abc import Callable

import pytest
from accounts.models import User
from employees.models import CompanySettings
from reports import rules
from reports.rules import Group, Rule

from assistant.columns import offered_columns
from assistant.plan import Condition, Part
from assistant.tables import (
    _NO_VALUE,
    _PREV_DROPPED,
    _TOO_MANY,
    _UNMAPPED,
    _base_of,
    _covered,
    _echo,
    _filters_of,
    settle,
    table_answer,
)

pytestmark = pytest.mark.django_db


def _rules_of(params: tuple[tuple[str, str], ...]) -> Group | None:
    """The rule tree the settled parameters carry, or None when there is no rules parameter."""
    text = dict(params).get("rules")
    return None if text is None else rules.parse_rules(text)


def test_years_worked_condition(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), conditions=(Condition("years_worked", "gte", "5", "5-аас дээш жил ажилласан"),))
    assert _rules_of(settled.params) == Group("and", (Rule("years_worked", "gte", "5"),))
    assert settled.not_applied == ()


def test_soon_without_number_uses_the_setting(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    condition = Condition("contract_end", "next_days", "", "гэрээ дуусах дөхсөн")
    assert _rules_of(settle(user, (), conditions=(condition,)).params) == Group(
        "and", (Rule("contract_end", "next_days", "30"),)
    )
    CompanySettings.objects.update_or_create(pk=1, defaults={"soon_days": 45})
    assert _rules_of(settle(user, (), conditions=(condition,)).params) == Group(
        "and", (Rule("contract_end", "next_days", "45"),)
    )
    typed = Condition("contract_end", "next_days", "60", "гэрээ дуусах дөхсөн")
    assert _rules_of(settle(user, (), conditions=(typed,)).params) == Group(
        "and", (Rule("contract_end", "next_days", "60"),)
    )


def test_hidden_and_unknown_columns_give_the_same_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    hidden = settle(user, (), conditions=(Condition("salary", "gt", "3000000", "цалин"),))
    unknown = settle(user, (), conditions=(Condition("zzz", "gt", "3000000", "цалин"),))
    assert hidden.not_applied == unknown.not_applied == (_UNMAPPED.format(word="цалин"),)
    assert _rules_of(hidden.params) is None
    assert _rules_of(unknown.params) is None


def test_bad_op_for_kind_dropped(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), conditions=(Condition("years_worked", "contains", "5", "жил"),))
    assert settled.not_applied == (_UNMAPPED.format(word="жил"),)
    assert _rules_of(settled.params) is None


def test_bad_value_dropped(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    words = settle(user, (), conditions=(Condition("years_worked", "gte", "много", "жил"),))
    assert words.not_applied == (_NO_VALUE.format(value="много"),)
    assert _rules_of(words.params) is None
    days = settle(user, (), conditions=(Condition("contract_end", "next_days", "-3", "дөхсөн"),))
    assert days.not_applied == (_NO_VALUE.format(value="-3"),)
    assert _rules_of(days.params) is None


def test_empty_value_refused_except_empty_and_filled(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), conditions=(Condition("years_worked", "gte", "", "жил"),))
    assert settled.not_applied == (_NO_VALUE.format(value=""),)
    assert _rules_of(settled.params) is None


def test_over_the_limit(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    columns = [c for c in offered_columns(user) if "filled" in c.ops][:25]
    assert len(columns) > rules.MAX_RULES
    conditions = tuple(Condition(c.key, "filled", "", c.label) for c in columns)
    settled = settle(user, (), conditions=conditions)
    kept = tuple(Rule(c.key, "filled", "") for c in columns[: rules.MAX_RULES])
    assert _rules_of(settled.params) == Group("and", kept)
    dropped = len(columns) - rules.MAX_RULES
    assert settled.not_applied == (_TOO_MANY.format(n=dropped),)


def test_empty_contains_refused(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), conditions=(Condition("name", "contains", "", "нэр"),))
    assert settled.not_applied == (_NO_VALUE.format(value=""),)
    assert _rules_of(settled.params) is None


def test_whitespace_contains_refused(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), conditions=(Condition("name", "contains", "   ", "нэр"),))
    assert settled.not_applied == (_NO_VALUE.format(value="   "),)
    assert _rules_of(settled.params) is None


def test_filled_needs_no_value(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), conditions=(Condition("work_phone", "filled", "", "утас"),))
    assert _rules_of(settled.params) == Group("and", (Rule("work_phone", "filled", ""),))
    assert settled.not_applied == ()


def test_filters_of_drops_hidden_rule(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = rules.dump_rules(Group("and", (Rule("salary", "gt", "3000000"),)))
    assert _filters_of(user, (("rules", text),)).rules == ""


def test_filters_of_keeps_visible_rule(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = rules.dump_rules(Group("and", (Rule("years_worked", "gte", "5"),)))
    assert _filters_of(user, (("rules", text),)).rules == text


def test_empty_filled_need_no_value(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), conditions=(Condition("work_phone", "empty", "", "телефон хоосон"),))
    assert _rules_of(settled.params) == Group("and", (Rule("work_phone", "empty", ""),))
    assert settled.not_applied == ()


def test_rules_pair_comes_after_the_parts(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(
        user,
        (Part("emptype", "permanent", "үндсэн"),),
        conditions=(Condition("years_worked", "gte", "5", "жил"),),
    )
    assert settled.params[-1][0] == "rules"


def test_refinement_adds_to_earlier_conditions(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    base = {"rules": rules.dump_rules(Group("and", (Rule("years_worked", "gte", "5"),)))}
    settled = settle(user, (), base=base, conditions=(Condition("work_phone", "empty", "", "телефон хоосон"),))
    assert _rules_of(settled.params) == Group(
        "and", (Rule("years_worked", "gte", "5"), Rule("work_phone", "empty", ""))
    )


def test_same_column_replaces(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    base = {"rules": rules.dump_rules(Group("and", (Rule("years_worked", "gte", "5"),)))}
    settled = settle(user, (), base=base, conditions=(Condition("years_worked", "gte", "10", "жил"),))
    assert _rules_of(settled.params) == Group("and", (Rule("years_worked", "gte", "10"),))


def test_carried_rule_on_hidden_column_is_dropped(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    crafted = '{"op":"and","items":[{"c":"salary","o":"gt","v":"1"}]}'
    settled = settle(user, (), base={"rules": crafted})
    assert not any(key == "rules" for key, _ in settled.params)


def test_nested_or_group_not_carried(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    or_group = '{"op":"or","items":[{"c":"years_worked","o":"gte","v":"5"}]}'
    nested = '{"op":"and","items":[{"op":"and","items":[{"c":"years_worked","o":"gte","v":"5"}]}]}'
    assert not any(key == "rules" for key, _ in settle(user, (), base={"rules": or_group}).params)
    assert not any(key == "rules" for key, _ in settle(user, (), base={"rules": nested}).params)


def test_no_new_conditions_still_carries(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = rules.dump_rules(Group("and", (Rule("years_worked", "gte", "5"),)))
    settled = settle(user, (), base={"rules": text}, conditions=())
    assert settled.params[-1] == ("rules", text)


def test_fresh_question_clears_earlier_conditions(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    answer = table_answer(user, (), base_query="")
    assert "rules=" not in answer.query


def test_carried_non_numeric_value_dropped(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = '{"op":"and","items":[{"c":"years_worked","o":"gte","v":"много"}]}'
    settled = settle(user, (), base={"rules": text})
    assert _rules_of(settled.params) is None
    assert settled.not_applied == (_NO_VALUE.format(value="много"),)


def test_carried_op_not_allowed_for_column_dropped(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = '{"op":"and","items":[{"c":"contract_end","o":"gte","v":"2026-01-01"}]}'
    settled = settle(user, (), base={"rules": text})
    assert _rules_of(settled.params) is None
    assert settled.not_applied == (_NO_VALUE.format(value="2026-01-01"),)


def test_carried_empty_value_dropped(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = '{"op":"and","items":[{"c":"years_worked","o":"gte","v":""}]}'
    settled = settle(user, (), base={"rules": text})
    assert _rules_of(settled.params) is None
    assert settled.not_applied == (_NO_VALUE.format(value=""),)


def test_valid_carried_rule_has_no_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = rules.dump_rules(Group("and", (Rule("years_worked", "gte", "5"),)))
    settled = settle(user, (), base={"rules": text})
    assert _rules_of(settled.params) == Group("and", (Rule("years_worked", "gte", "5"),))
    assert settled.not_applied == ()


def test_new_rule_replaces_every_carried_rule_on_its_column(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    base = {
        "rules": rules.dump_rules(Group("and", (Rule("years_worked", "gte", "5"), Rule("years_worked", "lte", "10"))))
    }
    settled = settle(user, (), base=base, conditions=(Condition("years_worked", "gte", "3", "жил"),))
    assert _rules_of(settled.params) == Group("and", (Rule("years_worked", "gte", "3"),))


def test_replaced_rule_keeps_its_position(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    base = {
        "rules": rules.dump_rules(Group("and", (Rule("years_worked", "gte", "5"), Rule("work_phone", "filled", ""))))
    }
    settled = settle(user, (), base=base, conditions=(Condition("years_worked", "gte", "3", "жил"),))
    assert _rules_of(settled.params) == Group(
        "and", (Rule("years_worked", "gte", "3"), Rule("work_phone", "filled", ""))
    )


def test_two_new_rules_on_one_column_are_both_kept(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    conditions = (Condition("years_worked", "gte", "3", "жил"), Condition("years_worked", "lte", "10", "жил"))
    settled = settle(user, (), conditions=conditions)
    assert _rules_of(settled.params) == Group(
        "and", (Rule("years_worked", "gte", "3"), Rule("years_worked", "lte", "10"))
    )


def test_and_group_with_nested_hidden_group_not_carried(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = (
        '{"op":"and","items":[{"c":"years_worked","o":"gte","v":"5"},'
        '{"op":"or","items":[{"c":"salary","o":"gt","v":"1"}]}]}'
    )
    settled = settle(user, (), base={"rules": text})
    assert not any(key == "rules" for key, _ in settled.params)


def test_base_keeps_a_3500_character_address() -> None:
    base = _base_of("q=" + "a" * 3400 + "&last=final")
    assert base.get("last") == "final"


def test_base_malformed_address_gives_nothing() -> None:
    assert _base_of("&".join(["k="] * 1100)) == {}


def test_long_value_refused_and_other_condition_still_applies(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    long_value = "x" * 101
    conditions = (Condition("name", "contains", long_value, "нэр"), Condition("years_worked", "gte", "5", "жил"))
    settled = settle(user, (), conditions=conditions)
    assert _rules_of(settled.params) == Group("and", (Rule("years_worked", "gte", "5"),))
    assert settled.not_applied == (_NO_VALUE.format(value=_echo(long_value)),)


def test_carried_long_value_dropped_with_a_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = '{"op":"and","items":[{"c":"name","o":"contains","v":"' + "x" * 101 + '"}]}'
    settled = settle(user, (), base={"rules": text})
    assert _rules_of(settled.params) is None
    assert settled.not_applied == (_PREV_DROPPED,)


def test_last_days_blank_value_refused(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), conditions=(Condition("contract_end", "last_days", "", "өнгөрсөн"),))
    assert _rules_of(settled.params) is None
    assert settled.not_applied == (_NO_VALUE.format(value=""),)


def test_rules_text_over_the_limit_drops_the_newest(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    conditions = tuple(Condition("name", "contains", "а" * 90, "нэр") for _ in range(18))
    settled = settle(user, (), conditions=conditions)
    text = dict(settled.params)["rules"]
    assert len(text) <= rules.MAX_TEXT
    kept = rules.parse_rules(text)
    assert kept is not None
    assert len(kept.items) == 15
    assert settled.not_applied == (_TOO_MANY.format(n=3),)


def test_carried_or_group_gives_the_dropped_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    or_group = '{"op":"or","items":[{"c":"years_worked","o":"gte","v":"5"}]}'
    settled = settle(user, (), base={"rules": or_group})
    assert _rules_of(settled.params) is None
    assert settled.not_applied == (_PREV_DROPPED,)


def test_carried_and_group_with_nested_group_gives_the_dropped_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = (
        '{"op":"and","items":[{"c":"years_worked","o":"gte","v":"5"},'
        '{"op":"and","items":[{"c":"years_worked","o":"lte","v":"9"}]}]}'
    )
    settled = settle(user, (), base={"rules": text})
    assert _rules_of(settled.params) is None
    assert settled.not_applied == (_PREV_DROPPED,)


def test_carried_garbage_gives_the_dropped_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), base={"rules": "not json"})
    assert _rules_of(settled.params) is None
    assert settled.not_applied == (_PREV_DROPPED,)


def test_carried_only_hidden_rules_gives_no_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    text = '{"op":"and","items":[{"c":"salary","o":"gt","v":"1"}]}'
    settled = settle(user, (), base={"rules": text})
    assert _rules_of(settled.params) is None
    assert settled.not_applied == ()


def test_no_earlier_rules_gives_no_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), base={})
    assert settled.not_applied == ()


def test_used_phrase_removes_unmapped_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    condition = Condition("years_worked", "gte", "5", "5-аас дээш жил ажилласан хүмүүс")
    settled = settle(user, (), unmapped=("5-аас дээш жил ажилласан",), conditions=(condition,))
    assert _rules_of(settled.params) == Group("and", (Rule("years_worked", "gte", "5"),))
    assert settled.not_applied == ()


def test_unrelated_unmapped_kept(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    condition = Condition("years_worked", "gte", "5", "5-аас дээш жил ажилласан хүмүүс")
    settled = settle(user, (), unmapped=("5-аас дээш жил ажилласан", "график"), conditions=(condition,))
    assert settled.not_applied == (_UNMAPPED.format(word="график"),)


def test_phrase_of_dropped_condition_does_not_hide_the_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), unmapped=("цалин",), conditions=(Condition("salary", "gt", "3000000", "цалин"),))
    assert settled.not_applied == (_UNMAPPED.format(word="цалин"),)


def test_part_phrase_counts(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    part = Part("hired_from", "2020-01-01", "2020 оноос хойш")
    settled = settle(user, (part,), unmapped=("2020 оноос",))
    assert settled.not_applied == ()


def test_rejected_part_phrase_does_not_hide_the_line(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    part = Part("hired_from", "not-a-date", "2020 оноос хойш")
    settled = settle(user, (part,), unmapped=("2020 оноос",))
    assert settled.not_applied == (_NO_VALUE.format(value="not-a-date"), _UNMAPPED.format(word="2020 оноос"))


def test_empty_phrase_covers_nothing(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    settled = settle(user, (), unmapped=("график",), conditions=(Condition("years_worked", "gte", "5", ""),))
    assert settled.not_applied == (_UNMAPPED.format(word="график"),)


def test_covered_ignores_case() -> None:
    assert _covered("ГРАФИК", ["график"])


def test_covered_one_way_only() -> None:
    assert _covered("жил", ["5-аас дээш жил ажилласан хүмүүс"])
    assert not _covered("5-аас дээш жил ажилласан хүмүүс", ["жил"])
    assert not _covered("5-аас дээш жил", ["жил"])


def test_covered_folds_case_endings() -> None:
    assert _covered("жилийн", ["жил"])
    assert _covered("ГРАФИК", ["график"])


def test_covered_empty_never_covers() -> None:
    assert not _covered("", ["график"])
    assert not _covered("   ", ["график"])
    assert not _covered("график", [""])
    assert not _covered("график", ["  "])
