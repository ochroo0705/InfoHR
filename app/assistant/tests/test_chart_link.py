"""A chart answer opens the staff report's own chart layout instead of drawing in the panel: a short description and an
«График нээх →» button whose link is the report address (layout=chart, the grouping, the chart type, the filters)."""

import html
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
from accounts.models import User
from django.test import Client
from django.urls import NoReverseMatch, reverse

from assistant import views
from assistant.entries import HelpEntry
from assistant.plan import Part, Plan
from assistant.providers import Choice
from assistant.tests.helpers import hire_one
from assistant.words import FilterWords

pytestmark = pytest.mark.django_db

ASK_URL = reverse("assistant:ask")
LINK_RE = re.compile(r'<a href="([^"]*)" data-chart-link')


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


def _plan(kind: str = "bar", by: str = "department", want: str = "chart", parts: Sequence[Part] = ()) -> Plan:
    return Plan(
        tool="staff_table",
        entry="",
        also="",
        lead="",
        parts=tuple(parts),
        unmapped=(),
        want=want,
        chart_kind=kind,
        chart_by=by,
    )


def _ask(client: Client, monkeypatch: pytest.MonkeyPatch, plan: Plan, **post: str) -> str:
    monkeypatch.setattr(views, "get_provider", lambda: ChartProvider(plan))
    return client.post(ASK_URL, {"q": "хэлтсээр нь график", **post}).content.decode()


def _link(body: str) -> tuple[str, dict[str, list[str]]]:
    match = LINK_RE.search(body)
    assert match is not None, "the chart button is missing"
    parts = urlsplit(html.unescape(match.group(1)))
    return parts.path, parse_qs(parts.query)


def test_chart_answer_opens_the_report_chart_layout(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    hire_one(role_user("hr"))
    client.force_login(role_user("hr"))

    body = _ask(client, monkeypatch, _plan(parts=[Part("emptype", "5")]))

    path, query = _link(body)
    assert path == reverse("reports:report", args=["staff-list"])
    assert query["layout"] == ["chart"]
    assert query["lby"] == ["department"]
    assert query["emptype"] == ["5"]  # the filters of the answer travel with it
    assert "lchart" not in query  # a bar chart is the report's default
    assert "График нээх →" in body
    assert "data-palette-item" in body.split("data-chart-link")[1].split(">")[0]  # reachable by the palette's keys


def test_pie_request_becomes_the_donut_chart(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    hire_one(role_user("hr"))
    client.force_login(role_user("hr"))

    body = _ask(client, monkeypatch, _plan(kind="pie"))

    assert _link(body)[1]["lchart"] == ["donut"]


def test_description_names_the_grouping_and_the_people(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = role_user("hr")
    hire_one(actor)
    hire_one(actor)
    client.force_login(role_user("hr"))

    body = _ask(client, monkeypatch, _plan())

    assert "График нээхэд бэлэн: 2 хүн" in body
    assert "Хэлтэс" in body  # the grouping column's label


@pytest.mark.parametrize("want", ["list", "count"])
def test_no_chart_button_for_a_list_or_a_count(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, want: str
) -> None:
    hire_one(role_user("hr"))
    client.force_login(role_user("hr"))

    body = _ask(client, monkeypatch, _plan(want=want))

    assert "data-chart-link" not in body
    assert "Хүснэгт нээх →" in body


def test_grouping_outside_the_options_gives_no_chart_button(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    hire_one(role_user("hr"))
    client.force_login(role_user("hr"))

    body = _ask(client, monkeypatch, _plan(by="bogus"))

    assert "data-chart-link" not in body
    assert "Хүснэгт нээх →" in body  # the answer still lists
    assert "График хийх боломжгүй: “bogus”." in body


def test_the_chart_link_opens_the_report_in_chart_layout(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    hire_one(role_user("hr"))
    client.force_login(role_user("hr"))
    body = _ask(client, monkeypatch, _plan())
    path, query = _link(body)

    response = client.get(path, {key: values[0] for key, values in query.items()})

    assert response.status_code == 200
    assert "Хэлтэс" in response.content.decode()


def test_the_panel_chart_routes_are_gone() -> None:
    for name in ("chart", "chart_xlsx"):
        with pytest.raises(NoReverseMatch):
            reverse(f"assistant:{name}")
