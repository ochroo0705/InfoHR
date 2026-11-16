"""The table pane's Table / Chart toggle (ws_table in ws_views.py): the chart view for a version with a valid chart.

Same setup as test_ws_views_table.py: no Firebird, the gate seams are patched and HrHost is replaced in ws_run.
"""

import json
import re

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result

from assistant import sqlanswer, ws_run, ws_views
from assistant.models import WorkspaceTab
from assistant.ws_chart import ChartSpec, chart_spec_to_json
from assistant.ws_service import add_version, new_tab

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name")),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))
BASE_SQL = "SELECT ID, NAME FROM GOV_EMPLOYEES"
BASE_COLUMNS = ("ID", "NAME")
ROWS = [(1, "Aigerim"), (2, "Bat"), (3, None)]
WINDOW = re.compile(r"FIRST (\d+)(?: SKIP (\d+))?")
CHART_BY_NAME = chart_spec_to_json(ChartSpec("bar", "NAME", ("ID",)))  # the names on the axis, the ids as values
CHART_TEXT_VALUES = chart_spec_to_json(ChartSpec("bar", "ID", ("NAME",)))  # text values: no payload
JSON_SCRIPT = re.compile(r'<script id="ws-chart-data" type="application/json">(.*?)</script>', re.S)


class FakeHost:
    """Records every SQL it is asked to run. Applies the Firebird window when the SQL has one."""

    def __init__(self) -> None:
        self.columns: tuple[str, ...] = BASE_COLUMNS
        self.rows: list[tuple[object, ...]] = list(ROWS)
        self.total = 3
        self.sql: list[str] = []

    def catalogue_for(self, user: object) -> Catalogue:
        return CATALOGUE

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.sql.append(query.sql)
        if "COUNT(*)" in query.sql:
            return Result(columns=("N",), rows=((self.total,),), truncated=False)
        rows = list(self.rows)
        match = WINDOW.search(query.sql)
        if match:
            skip = int(match.group(2) or 0)
            rows = rows[skip : skip + int(match.group(1))]
        return Result(columns=self.columns, rows=tuple(rows[: limits.max_rows + 1]), truncated=False)

    def cancel(self, user: object) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear_gate_cache() -> None:
    cache.clear()


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    state: dict[str, object] = {"views": (EMPLOYEES,)}
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    monkeypatch.setattr(ws_views, "_catalogue_views", lambda user: state["views"])
    return state


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> FakeHost:
    fake = FakeHost()
    monkeypatch.setattr(ws_run, "HrHost", lambda: fake)
    return fake


def _tab(user, chart: str = "", sql: str = BASE_SQL) -> WorkspaceTab:
    tab = new_tab(user, "Тест хүснэгт")
    add_version(tab, "Асуулт", sql, "", chart=chart)
    return tab


def _url(tab: WorkspaceTab, query: str = "") -> str:
    base = reverse("assistant:ws_table", args=[tab.pk])
    return f"{base}?{query}" if query else base


def _pane(client: Client, url: str) -> str:
    response = client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    return response.content.decode()


def _chart_json(html: str) -> dict:
    match = JSON_SCRIPT.search(html)
    assert match is not None, "the chart payload is missing"
    return json.loads(match.group(1))


def test_no_toggle_without_chart(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert ">График</a>" not in html
    assert ">Хүснэгт</a>" not in html
    assert 'name="fcol"' in html  # the table is still there


def test_toggle_shown_with_chart(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user, chart=CHART_BY_NAME)
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert ">Хүснэгт</a>" in html
    assert ">График</a>" in html
    assert f'href="{_url(tab)}"' in html  # the chart link is the address without view (the chart is the default)
    assert f'href="{_url(tab, "view=table")}"' in html  # the table link sets view=table
    assert 'id="ws-chart-data"' in html  # the chart is the view on screen by default
    assert 'name="fcol"' not in html


def test_table_view_on_request(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user, chart=CHART_BY_NAME)
    client.force_login(user)

    html = _pane(client, _url(tab, "view=table"))

    assert 'name="fcol"' in html  # the table with its tools
    assert 'id="ws-chart-data"' not in html
    assert ">Хүснэгт</a>" in html and ">График</a>" in html  # the toggle stays
    assert re.search(r'<a href="[^"]*"[^>]*aria-current="page"[^>]*>Хүснэгт</a>', html) is not None
    assert f'href="{_url(tab)}"' in html  # the chart link is the bare address


def test_chart_view_renders_payload(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user, chart=CHART_BY_NAME)
    client.force_login(user)

    html = _pane(client, _url(tab, "view=chart"))

    payload = _chart_json(html)
    assert payload["labels"][:2] == ["Aigerim", "Bat"]
    assert payload["values"][:2] == [1, 2]
    assert payload["kind"] == "bar"
    assert 'data-echarts-src="' in html and "vendor/echarts/echarts.min.js" in html
    assert 'data-chart-data="ws-chart-data"' in html
    assert "data-chart-failed hidden" in html
    assert 'name="fcol"' not in html  # the tools are not drawn in the chart view
    assert 'aria-current="page"' in html  # the chart is the view on screen
    assert f'href="{_url(tab, "view=table")}"' in html  # the table link asks for the table view


def test_chart_view_without_valid_chart_falls_back_to_table(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab(user, chart="")
    client.force_login(user)

    html = _pane(client, _url(tab, "view=chart"))

    assert 'name="fcol"' in html
    assert 'id="ws-chart-data"' not in html
    assert ">График</a>" not in html


def test_chart_labels_escaped(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    host.rows = [(1, "<b>x</b>")]
    tab = _tab(user, chart=CHART_BY_NAME)
    client.force_login(user)

    html = _pane(client, _url(tab, "view=chart"))

    assert _chart_json(html)["labels"] == ["<b>x</b>"]  # the payload keeps the text itself
    assert "&lt;b&gt;x&lt;/b&gt;" in html  # the plain table escapes it
    assert "<b>x</b>" not in html


def test_unchartable_rows_fall_back_to_table(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user, chart=CHART_TEXT_VALUES)  # a valid spec, but the value column holds text only: no payload
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert 'name="fcol"' in html  # the table with its tools
    assert 'id="ws-chart-data"' not in html
    assert ">График</a>" not in html  # no toggle: the rows cannot be charted
    assert "Энэ үр дүнгээс график гаргах боломжгүй." not in html
