"""Tests for the field and leave-form cases of the accuracy set: the cases exist and are ungated, the check reads the
plan's tool, field and dates, and assistant_eval prints a line for each case without counting it in the gate."""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from pytest import MonkeyPatch

from assistant.entries import ENTRIES, HelpEntry
from assistant.evalcheck import ActionResult, check_action
from assistant.evalset import ACTION_CASES, CASES, ActionCase
from assistant.fields import field_by_key
from assistant.management.commands import assistant_eval
from assistant.plan import Plan
from assistant.tests.helpers import action_plan_for, drop_narrowing, seed_eval_rows, too_close_pairs
from assistant.tests.test_eval import PerfectProvider
from assistant.words import FilterWords


@pytest.fixture(autouse=True)
def _unnarrowed(monkeypatch: MonkeyPatch) -> None:
    drop_narrowing(monkeypatch)


def _plan(tool: str, field: str = "", start: str = "", end: str = "") -> Plan:
    return Plan(
        tool=tool,
        entry="",
        also="",
        lead="",
        parts=(),
        unmapped=(),
        want="list",
        chart_kind="",
        chart_by="",
        field=field,
        start=start,
        end=end,
    )


def _case(question: str) -> ActionCase:
    return next(c for c in ACTION_CASES if c.question == question)


def _right_plan(case: ActionCase) -> Plan:
    return action_plan_for(case)


class ActionFake(PerfectProvider):
    """Perfect for the entry and table cases. Each action case gets its right plan, or no answer when `wrong`."""

    def __init__(self, wrong: bool = False) -> None:
        self.wrong = wrong

    def plan(
        self,
        question: str,
        entries: Sequence[HelpEntry],
        words: Sequence[FilterWords],
        phrases: Mapping[str, list[str]],
        today: date,
        previous: str = "",
        refusals: Sequence[str] = (),
        table_examples: Sequence[tuple[str, str]] = (),
        field_hints: Sequence[object] = (),
    ) -> Plan:
        case = next((c for c in ACTION_CASES if c.question == question), None)
        if case is None:
            return super().plan(
                question, entries, words, phrases, today, previous, refusals, table_examples, field_hints
            )
        return _plan("none") if self.wrong else _right_plan(case)


@pytest.fixture
def rows(db: None) -> None:
    seed_eval_rows()


def test_action_cases_cover_fields_and_leave_forms() -> None:
    fields = [c for c in ACTION_CASES if c.tool == "field"]
    leave = [c for c in ACTION_CASES if c.tool == "leave_form"]
    assert len(fields) >= 8
    assert len(leave) >= 4
    assert all(c.leave is False and c.field for c in fields)
    assert all(c.leave is True and c.field == "" for c in leave)
    for case in fields:
        assert field_by_key(case.field) is not None, case.field


def test_action_cases_do_not_copy_entry_examples() -> None:
    """An action sentence the model has already seen as an example would only measure memory."""
    examples = [x for e in ENTRIES for x in (*e.examples, *e.words)]
    assert too_close_pairs([c.question for c in ACTION_CASES], examples) == []
    assert not {c.question for c in ACTION_CASES} & {c.question for c in CASES}


def test_check_passes_the_right_tool_and_field() -> None:
    case = _case("Болдын гэрийн утасны дугаар хэд вэ")
    assert check_action(case, _plan("field", field="private_phone")) == ActionResult(True, "field private_phone")


def test_check_fails_a_wrong_field_or_tool() -> None:
    case = _case("Болдын гэрийн утасны дугаар хэд вэ")
    assert not check_action(case, _plan("field", field="work_phone")).passed
    assert not check_action(case, _plan("none")).passed
    assert not check_action(case, _plan("leave_form")).passed


def test_leave_dates_must_parse_when_given() -> None:
    case = _case("Бат ээлжийн амралт 2026-11-10-с 2026-11-12 хүртэл авах гэсэн")
    assert check_action(case, _plan("leave_form", start="2026-11-10", end="2026-11-12")).passed
    assert check_action(case, _plan("leave_form")).passed  # a date the plan leaves out is not a mistake
    assert not check_action(case, _plan("leave_form", start="2026-13-45")).passed
    assert not check_action(case, _plan("leave_form", end="ирэх сар")).passed


def test_action_cases_are_reported_but_not_gated(rows: None, monkeypatch: MonkeyPatch) -> None:
    """Wrong answers to the action cases print a FAIL line each, and the gate total is the same as with right ones."""
    totals: list[tuple[str, str]] = []
    for wrong in (False, True):
        monkeypatch.setattr(assistant_eval, "get_provider", lambda wrong=wrong: ActionFake(wrong=wrong))
        out = StringIO()
        call_command("assistant_eval", stdout=out)
        text = out.getvalue()
        assert "action | " in text
        assert "(not gated)" in text
        match = re.search(r"Overall: (\d+)/(\d+)", text)
        assert match is not None
        totals.append((match.group(1), match.group(2)))
    assert totals[0] == totals[1]
    assert totals[0][0] == totals[0][1]  # the gated cases all pass with the perfect fake


def test_action_lines_name_the_expected_tool_and_field(rows: None, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: ActionFake(wrong=True))
    out = StringIO()
    call_command("assistant_eval", stdout=out)
    text = out.getvalue()
    assert f"actions 0/{len(ACTION_CASES)} (not gated)" in text
    assert "expected field private_phone | got none (not gated)" in text
