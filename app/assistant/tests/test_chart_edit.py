"""Tests for editing the open chart through the assistant.

The open chart's kind and grouping reach the plan, a chart question asked with a chart open updates that chart in place
(data-chart-auto), a bad chart value is ignored, and the chart fragment carries the state the panel sends back."""

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse

from assistant import views
from assistant.entries import HelpEntry
from assistant.plan import Plan
from assistant.prompt import plan_input
from assistant.providers import Choice
from assistant.tests.helpers import hire_one
from assistant.words import FilterWords

pytestmark = pytest.mark.django_db

ASK_URL = reverse("assistant:ask")
CHART_URL = reverse("assistant:chart")
TODAY = date(2026, 11, 6)


class Recorder:
    """A fake provider that returns a canned plan and records what it was given."""

    name = "fake"
    model = "fake-model"

    def __init__(self, plan: Plan) -> None:
        self.canned = plan
        self.seen: dict[str, Any] = {}

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        raise AssertionError("not used")

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
        open_chart: tuple[str, str] | None = None,
    ) -> Plan:
        self.seen = {"previous": previous, "open_chart": open_chart}
        return self.canned


def _plan(by: str = "", kind: str = "pie") -> Plan:
    return Plan(
        tool="staff_table",
        entry="",
        also="",
        lead="",
        parts=(),
        unmapped=(),
        want="chart",
        chart_kind=kind,
        chart_by=by,
    )


def _ask(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, plan: Plan, **post: str
) -> tuple[str, Recorder]:
    hire_one(role_user("hr"))
    provider = Recorder(plan)
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    return client.post(ASK_URL, {"q": "дугуй болго", **post}).content.decode(), provider


def test_open_chart_reaches_the_plan_and_updates_in_place(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    body, provider = _ask(client, role_user, monkeypatch, _plan(by="department"), chart="bar|department", prev="")
    assert provider.seen["open_chart"] == ("bar", "department")
    assert "data-chart-auto" in body
    assert "График шинэчлэгдлээ." in body


def test_chart_without_grouping_keeps_the_open_charts_grouping(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    body, _ = _ask(client, role_user, monkeypatch, _plan(by=""), chart="bar|department")
    assert "by=department" in body.replace("&amp;", "&")
    assert "data-chart-auto" in body


def test_no_open_chart_means_no_auto_update(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    body, provider = _ask(client, role_user, monkeypatch, _plan(by="department"))
    assert provider.seen["open_chart"] is None
    assert "data-chart-auto" not in body
    assert "График харах →" in body


@pytest.mark.parametrize("bad", ["", "line|department", "bar|salary", "bar", "bar|department|x", "|"])
def test_bad_chart_value_is_ignored(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    body, provider = _ask(client, role_user, monkeypatch, _plan(by="department"), chart=bad)
    assert provider.seen["open_chart"] is None
    assert "data-chart-auto" not in body


def test_plan_input_names_the_open_chart_only_when_given() -> None:
    assert '"open_chart"' not in plan_input("q", TODAY, "")
    assert '"open_chart": {"kind": "pie", "by": "branch"}' in plan_input("q", TODAY, "", ("pie", "branch"))


def test_chart_fragment_carries_its_state(client: Client, role_user: Callable[[str], User]) -> None:
    hire_one(role_user("hr"))
    client.force_login(role_user("hr"))
    body = client.get(CHART_URL, {"kind": "pie", "by": "department", "query": ""}).content.decode()
    assert re.search(r'<div data-chart-state data-query="" data-kind="pie" data-by="department" hidden>', body)
