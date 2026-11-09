"""Tests for the plan's two action tools (`field`, `leave_form`): the parsed fields, their clamps, the schema, the
filters block that lists the askable fields, and the provider and fake signatures that carry `field_hints`."""

import inspect
import json
from typing import Any

import pytest

from assistant.fields import AskableField
from assistant.plan import Plan, parse_plan
from assistant.prompt import PLAN_INSTRUCTION, PLAN_REPLY, PLAN_SCHEMA, TOOLS, words_block
from assistant.providers import ClaudeProvider, GeminiProvider, GroqProvider, Provider, ProviderError
from assistant.tests.helpers import fake_plan
from assistant.tests.test_providers import (
    PHRASES,
    PLAN_JSON,
    PLAN_QUESTION,
    TODAY,
    WORDS,
    _claude_reply,
    _groq_reply,
    _Post,
)
from assistant.words import WORDS as FILTER_WORDS

PHONE = AskableField(key="work_phone", label="Ажлын утас", synonyms=("утас",), tab="work", source="form")


def _reply(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "tool": "none",
        "entry": "",
        "also": "",
        "lead": "",
        "parts": [],
        "unmapped": [],
        "want": "list",
        "chart_kind": "",
        "chart_by": "",
        "fresh": False,
        "field": "",
        "own": False,
        "leave_type": "",
        "start": "",
        "end": "",
    }
    data.update(changes)
    return data


def test_action_tools_are_planned_tools() -> None:
    assert "field" in TOOLS
    assert "leave_form" in TOOLS


def test_field_tool_is_parsed() -> None:
    plan = parse_plan(_reply(tool="field", field="work_phone", own=True))
    assert plan.tool == "field"
    assert plan.field == "work_phone"
    assert plan.own is True


def test_field_tool_with_empty_field_becomes_none() -> None:
    assert parse_plan(_reply(tool="field", field="")).tool == "none"
    assert parse_plan(_reply(tool="field", field="work_phone")).tool == "field"


def test_leave_form_tool_is_parsed() -> None:
    plan = parse_plan(_reply(tool="leave_form", leave_type="амралт", start="2026-11-10", end="2026-11-12"))
    assert plan.tool == "leave_form"
    assert plan.leave_type == "амралт"
    assert plan.start == "2026-11-10"
    assert plan.end == "2026-11-12"


def test_new_fields_default_when_not_in_a_plan() -> None:
    plan = Plan(tool="none", entry="", also="", lead="", parts=(), unmapped=(), want="list", chart_kind="", chart_by="")
    assert (plan.field, plan.own, plan.leave_type, plan.start, plan.end) == ("", False, "", "", "")


def test_action_strings_are_clamped() -> None:
    plan = parse_plan(_reply(tool="leave_form", field="f" * 100, leave_type="л" * 100, start="2" * 30, end="3" * 30))
    assert plan.field == "f" * 60
    assert plan.leave_type == "л" * 60
    assert plan.start == "2" * 10
    assert plan.end == "3" * 10


@pytest.mark.parametrize("own", ["true", 1, "yes", None])
def test_own_needs_a_real_true(own: Any) -> None:
    assert parse_plan(_reply(tool="field", field="work_phone", own=own)).own is False


def test_action_fields_must_be_strings() -> None:
    with pytest.raises(ProviderError):
        parse_plan(_reply(tool="field", field=5))
    with pytest.raises(ProviderError):
        parse_plan(_reply(tool="leave_form", start=None))


def test_schema_lists_the_action_fields() -> None:
    names = {"field", "own", "leave_type", "start", "end"}
    assert names <= set(PLAN_SCHEMA["properties"])
    assert names <= set(PLAN_SCHEMA["required"])
    assert set(PLAN_SCHEMA["properties"]["tool"]["enum"]) == set(TOOLS)
    assert PLAN_SCHEMA["properties"]["own"] == {"type": "boolean"}


def test_reply_example_lists_the_action_fields() -> None:
    for name in ("field", "own", "leave_type", "start", "end"):
        assert f'"{name}"' in PLAN_REPLY


def test_instruction_describes_the_action_tools() -> None:
    assert "field" in PLAN_INSTRUCTION
    assert "fields" in PLAN_INSTRUCTION
    assert "leave_form" in PLAN_INSTRUCTION
    assert "амралт бич" in PLAN_INSTRUCTION
    assert "миний" in PLAN_INSTRUCTION
    assert "Never output URLs" in PLAN_INSTRUCTION


def test_words_block_lists_the_hints_as_fields() -> None:
    block = json.loads(words_block([FILTER_WORDS["department"]], PHRASES, (PHONE,)))
    assert block["fields"] == [{"key": "work_phone", "label": "Ажлын утас", "synonyms": ["утас"]}]
    assert block["group_options"][:3] == ["department", "branch", "position"]  # then the code-list columns
    assert block["filters"][0]["param"] == "department"


def test_words_block_without_hints_has_no_fields() -> None:
    block = json.loads(words_block([FILTER_WORDS["department"]], PHRASES))
    assert block["fields"] == []


@pytest.mark.parametrize("provider_class", [GroqProvider, ClaudeProvider, GeminiProvider])
def test_provider_plan_accepts_field_hints(provider_class: Any) -> None:
    params = inspect.signature(provider_class.plan).parameters
    assert "field_hints" in params
    assert params["field_hints"].default == ()


def test_protocol_plan_accepts_field_hints() -> None:
    assert "field_hints" in inspect.signature(Provider.plan).parameters


def test_groq_plan_sends_the_field_hints_in_the_system_text() -> None:
    post = _Post(_groq_reply(PLAN_JSON))
    GroqProvider(api_key="k", model="m", timeout=5, post=post).plan(
        PLAN_QUESTION, [], WORDS, PHRASES, TODAY, field_hints=(PHONE,)
    )
    system = json.loads(post.calls[0][1])["messages"][0]["content"]
    assert json.dumps({"key": "work_phone", "label": "Ажлын утас", "synonyms": ["утас"]}, ensure_ascii=False) in system


def test_claude_plan_sends_the_field_hints_in_the_system_text() -> None:
    post = _Post(_claude_reply(PLAN_JSON))
    ClaudeProvider(api_key="k", model="m", timeout=5, post=post).plan(
        PLAN_QUESTION, [], WORDS, PHRASES, TODAY, field_hints=(PHONE,)
    )
    body = json.loads(post.calls[0][1])
    assert '"key": "work_phone"' in body["system"]


def test_fake_plan_accepts_field_hints() -> None:
    class _Choosing:
        def choose(self, question: str, entries: Any, refusals: Any = ()) -> Any:
            from assistant.providers import Choice

            return Choice(entry="", also="", lead="")

    plan = fake_plan(_Choosing(), "миний утас", [], field_hints=(PHONE,))
    assert plan.tool == "none"
