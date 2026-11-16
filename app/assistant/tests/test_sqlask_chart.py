"""Tests for the chart part of the SQL question call: its schema, prompt rules and the chart it returns."""

from datetime import date
from typing import Any, cast

from assistant.providers import Provider
from assistant.sqlask import SQL_INSTRUCTION, SQL_SCHEMA, _refine_user, ask_refine_sql_reply, ask_sql_reply

CATALOGUE = "GOV_CHILDREN: one row per child. Columns: EMP_ID (employee id), CHILD_NAME, BIRTH_DATE."
QUESTION = "Хэлтэс бүрт хэдэн ажилтан байна? График зур."
TODAY = date(2026, 11, 16)


class FakeProvider:
    """Records each complete_json call and returns the reply it was given."""

    name = "fake"
    model = "fake-model"

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str, Any]] = []

    def complete_json(self, system: str, user: str, schema: Any = None) -> Any:
        self.calls.append((system, user, schema))
        return self.reply


def _fake(reply: Any) -> Provider:
    return cast(Provider, FakeProvider(reply))


def test_reply_carries_chart() -> None:
    provider = _fake({"sql": "SELECT 1", "chart": {"type": "bar", "x": "A", "y": ["B"]}})
    reply = ask_sql_reply(provider, CATALOGUE, QUESTION, TODAY)
    assert reply.chart == {"type": "bar", "x": "A", "y": ["B"]}


def test_reply_without_chart_is_empty() -> None:
    assert ask_sql_reply(_fake({"sql": "SELECT 1"}), CATALOGUE, QUESTION, TODAY).chart == {}
    assert ask_sql_reply(_fake({"sql": "SELECT 1", "chart": "bar"}), CATALOGUE, QUESTION, TODAY).chart == {}


def test_refine_reply_carries_chart() -> None:
    provider = _fake({"sql": "SELECT 1", "chart": {"type": "line", "x": "A", "y": ["B"]}})
    reply = ask_refine_sql_reply(provider, CATALOGUE, "SELECT 1", ["A", "B"], [], "график", TODAY)
    assert reply.chart == {"type": "line", "x": "A", "y": ["B"]}


def test_refine_user_has_chart_block() -> None:
    text = _refine_user("SELECT 1", ["A"], [], "x", date(2026, 11, 16), "", chart='{"type": "line"}')
    assert '<chart>\n{"type": "line"}\n</chart>' in text


def test_schema_lists_chart_types() -> None:
    description = SQL_SCHEMA["properties"]["chart"]["properties"]["type"]["description"]
    assert "stacked_bar" in description
    assert "none" in description


def test_prompt_has_chart_rules() -> None:
    assert 'Fill "chart" only when the user asks for a chart' in SQL_INSTRUCTION
