"""Tests for the assistant's chart pop-up: the chart view's pop-up markup (the data as JSON, the same numbers as a text
list, no outside script), the login and 400 rules, the empty-chart text, the gate, and the «График харах →» link that
only a chart answer with chart data gets."""

import html
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from macs.models import Department

from assistant import views
from assistant.entries import HelpEntry
from assistant.plan import Part, Plan
from assistant.providers import Choice
from assistant.tests.helpers import hire_one
from assistant.words import FilterWords

pytestmark = pytest.mark.django_db

CHART_URL = reverse("assistant:chart")
ASK_URL = reverse("assistant:ask")
JSON_RE = re.compile(r'<script id="assistant-chart-data" type="application/json">(.*?)</script>', re.S)


class ChartProvider:
    """A fake provider whose plan() is a canned Plan."""

    name = "fake"
    model = "fake-model"

    def __init__(self, plan: Plan) -> None:
        self.table = plan

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        raise AssertionError("the table path must not call choose")

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
        return self.table


def _chart_plan(parts: Sequence[Part] = (), want: str = "chart") -> Plan:
    return Plan(
        tool="staff_table",
        entry="",
        also="",
        lead="",
        parts=tuple(parts),
        unmapped=(),
        want=want,
        chart_kind="bar",
        chart_by="department",
    )


def _chart(client: Client, **params: str) -> str:
    return client.get(CHART_URL, params).content.decode()


def _payload(body: str) -> dict[str, object]:
    match = JSON_RE.search(body)
    assert match is not None, "the chart data script is missing"
    payload: dict[str, object] = json.loads(match.group(1))
    return payload


def test_chart_modal_has_json_and_text_list(client: Client, role_user: Callable[[str], User]) -> None:
    actor = role_user("hr")
    hire_one(actor)
    hire_one(actor)
    client.force_login(role_user("hr"))

    body = _chart(client, query="", kind="bar", by="department")

    payload = _payload(body)
    assert payload == {"kind": "bar", "labels": ["Санхүү"], "counts": [2], "total": 2}
    assert "Хэлтэс: нийт 2 хүн" in body  # the title: the column label and the total
    assert "Санхүү: 2 (100%)" in body  # the plain text list says the same numbers
    assert "group=department" in body  # the staff table link groups by the same column


def test_chart_requires_login(client: Client) -> None:
    response = client.get(CHART_URL, {"query": "", "kind": "bar", "by": "department"})
    assert response.status_code == 302
    assert "/login" in response["Location"]


def test_chart_bad_by_is_400(client: Client, role_user: Callable[[str], User]) -> None:
    client.force_login(role_user("hr"))
    assert client.get(CHART_URL, {"query": "", "kind": "bar", "by": "name"}).status_code == 400  # a column, not a group
    assert client.get(CHART_URL, {"query": "", "kind": "bar", "by": "bogus"}).status_code == 400
    assert client.get(CHART_URL, {"query": "", "kind": "line", "by": "department"}).status_code == 400


def test_chart_modal_has_no_external_script(client: Client, role_user: Callable[[str], User]) -> None:
    actor = role_user("hr")
    hire_one(actor)
    client.force_login(role_user("hr"))

    body = _chart(client, query="", kind="pie", by="department")

    sources = re.findall(r'src="([^"]*)"', body)
    assert all(src.startswith("/static/") for src in sources), sources
    assert "http://" not in body and "https://" not in body


@pytest.mark.parametrize(("want", "shown"), [("list", False), ("count", False), ("chart", True)])
def test_chart_link_only_for_chart_requests(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, want: str, shown: bool
) -> None:
    actor = role_user("hr")
    hire_one(actor)
    monkeypatch.setattr(views, "get_provider", lambda: ChartProvider(_chart_plan(want=want)))
    client.force_login(role_user("hr"))

    body = client.post(ASK_URL, {"q": "хэлтсээр нь график"}).content.decode()

    assert ("График харах →" in body) is shown
    if shown:
        assert f"{CHART_URL}?" in body
        assert urlencode({"kind": "bar"}) in body
        assert urlencode({"by": "department"}) in body
        assert "data-palette-modal" in body  # opens the pop-up over the page, the panel stays open


def test_empty_chart_message(client: Client, role_user: Callable[[str], User]) -> None:
    dept = Department.objects.create(name="Маркетинг")
    client.force_login(role_user("hr"))

    body = _chart(client, query=f"department={dept.pk}", kind="bar", by="department")

    assert "Хэн ч олдсонгүй." in body
    assert "data-assistant-chart" not in body  # no chart is drawn for nobody
    assert _payload(body)["total"] == 0


def test_chart_applies_the_gate(client: Client, role_user: Callable[[str], User]) -> None:
    # hr may not see salary, so a salary bound in the address is dropped and the chart counts the same people.
    actor = role_user("hr")
    hire_one(actor)
    client.force_login(role_user("hr"))

    plain = _payload(_chart(client, query="", kind="bar", by="department"))
    gated = _payload(_chart(client, query="salary_from=9000000", kind="bar", by="department"))

    assert gated == plain
    assert plain["total"] == 1


def _chart_link(query: str, kind: str, by: str) -> str:
    """The chart link as the fragment writes it into the page (its & escaped)."""
    return html.escape(f"{CHART_URL}?{urlencode({'query': query, 'kind': kind, 'by': by})}")


def test_chart_plan_reaches_the_fragment(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = role_user("hr")
    hire_one(actor)
    monkeypatch.setattr(views, "get_provider", lambda: ChartProvider(_chart_plan(parts=[Part("emptype", "5")])))
    client.force_login(role_user("hr"))

    body = client.post(ASK_URL, {"q": "гэрээт ажилтнуудыг хэлтсээр нь график"}).content.decode()

    assert _chart_link("emptype=5", "bar", "department") in body
    assert "График харах →" in body


def test_chart_by_outside_group_options_gives_no_link(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = role_user("hr")
    hire_one(actor)
    plan = Plan(
        tool="staff_table",
        entry="",
        also="",
        lead="",
        parts=(),
        unmapped=(),
        want="chart",
        chart_kind="bar",
        chart_by="bogus",
    )
    monkeypatch.setattr(views, "get_provider", lambda: ChartProvider(plan))
    client.force_login(role_user("hr"))

    body = client.post(ASK_URL, {"q": "хэлтсээр нь график"}).content.decode()

    assert "Хүснэгт нээх →" in body  # the answer still lists
    assert "График харах →" not in body
    assert "График хийх боломжгүй: “bogus”." in body


def test_chart_follows_previous_filters(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = role_user("hr")
    hire_one(actor)
    monkeypatch.setattr(views, "get_provider", lambda: ChartProvider(_chart_plan(parts=())))
    client.force_login(role_user("hr"))

    body = client.post(ASK_URL, {"q": "хэлтсээр нь графикаар үзүүл", "prev": "emptype=5"}).content.decode()

    assert _chart_link("emptype=5", "bar", "department") in body


def test_chart_without_a_grouping_says_so() -> None:
    from assistant.tables import _NO_CHART_BY, _chart_lines

    assert _chart_lines("chart", "") == (_NO_CHART_BY,)
    assert _chart_lines("chart", "department") == ()
    assert _chart_lines("list", "") == ()
