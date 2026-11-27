"""GET /api/v1/reports/{key} for the layouts other than the table: the layout_page answer React reads (its bar, its one
payload, and the page-level lines the table answer carries).

The rules come from reports.services.layout_page and table_page; these tests pin the API's shape, that exactly one
payload is set per layout, that the table is absent, that a column the viewer may not see never reaches the answer,
that a hidden money figure is text «—» with a null value, that links use the report's path and the cleaned query, and
that a redirect carries no layout page.
"""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.http import QueryDict
from django.test import Client
from reports.filters import parse_filters
from reports.models import SavedView
from reports.registry import REPORTS
from reports.services import layout_page as layout_service
from reports.table import build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "api-layout-test"
URL = f"/api/v1/reports/{KEY}"
PATH = f"/reports/{KEY}/"
LAYOUTS = ("board", "cards", "calendar", "timeline", "chart", "pivot")
PAYLOADS = ("board", "cards", "calendar", "timeline", "chart", "pivot")
NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
# a column no user holds (the permission does not exist): its key and label must never reach any answer
SECRET_KEY = "secret"  # noqa: S105 (a column key, not a password)
SECRET_LABEL = "Нууц цалин"  # noqa: S105 (a column label, not a password)
SECRET_VALUE = 424242
SECRET = Column(
    key=SECRET_KEY,
    label=SECRET_LABEL,
    value=lambda r: r.secret,
    kind="number",
    numeric=True,
    needs="accounts.view_secret",
)


def _rows() -> list[Any]:
    return [
        SimpleNamespace(
            name="Бат", dept="Санхүү", start=date(2026, 11, 3), pay=Decimal("1500000"), secret=SECRET_VALUE
        ),
        SimpleNamespace(name="Дорж", dept="Санхүү", start=date(2026, 11, 10), pay=Decimal("500"), secret=SECRET_VALUE),
        SimpleNamespace(
            name="Сараа", dept="Ачаа", start=date(2026, 11, 17), pay=Decimal("900000"), secret=SECRET_VALUE
        ),
    ]


def _register(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Тестийн найрлага",
        filters=(),
        columns=(NAME, DEPT, START, PAY, SECRET),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _rows(),
        saved_views=True,
        layouts=LAYOUTS,
        group_options=("dept",),
        layout_date="start",
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _user(role: str) -> User:
    name = f"layout_api_{role.lower()}"
    user = User.objects.filter(username=name).first()
    if user is None:
        user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


def _client(role: str) -> Client:
    client = Client()
    client.force_login(_user(role))
    return client


def _get(client: Client, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.get(URL, params or {})
    assert response.status_code == 200, response.content.decode()
    body: dict[str, Any] = response.json()
    return body


def _hrefs(node: Any) -> list[str]:
    """Every link target in an answer: the string values under a key that names a link (href, or a url such as
    clear_rules_url). The empty ones (no link) are left in; the test drops them."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and ("href" in key or "url" in key):
                found.append(value)
            else:
                found.extend(_hrefs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_hrefs(item))
    return found


@pytest.mark.parametrize("layout", LAYOUTS)
def test_every_layout_answer_carries_its_payload_and_no_table(monkeypatch: pytest.MonkeyPatch, layout: str) -> None:
    _register(monkeypatch)
    body = _get(_client("HR"), {"layout": layout})
    assert body["layout"] == layout
    assert body["table"] is None
    assert body["head"] is not None
    assert body["bar"] is not None
    page = body["layout_page"]
    assert page is not None
    assert page["kind"] == layout
    assert page["bar"]["layout"] == layout
    assert page["count"] == len(_rows())
    set_names = [name for name in PAYLOADS if page[name] is not None]
    assert set_names == [layout]


def test_table_layout_has_no_layout_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    body = _get(_client("HR"))
    assert body["layout"] == "table"
    assert body["layout_page"] is None
    assert body["table"] is not None


def test_layout_answers_are_no_store(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    for layout in LAYOUTS:
        response = _client("HR").get(URL, {"layout": layout})
        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"


def test_hidden_column_in_lby_is_not_drawn_or_named(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    response = _client("HR").get(URL, {"layout": "chart", "lby": SECRET_KEY, "lval": f"{SECRET_KEY}:sum"})
    assert response.status_code == 200
    raw = response.content.decode()
    assert SECRET_KEY not in raw
    assert SECRET_LABEL not in raw
    assert str(SECRET_VALUE) not in raw


def test_masked_money_is_dash_text_and_null_value(monkeypatch: pytest.MonkeyPatch, settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 3  # the default; pinned so the test does not depend on the environment
    _register(monkeypatch)
    body = _get(_client("HR"), {"layout": "chart", "lby": "dept", "lval": "pay:sum"})
    chart = body["layout_page"]["chart"]
    assert chart["masked"] is True
    assert chart["note"] != ""
    assert chart["values"] == [None] * len(chart["values"])
    assert [row["total"] for row in chart["rows"]] == ["—"] * len(chart["rows"])
    assert all(value is None for series in chart["series"] for value in series["values"])


def test_addresses_in_links_use_the_report_path_and_cleaned_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    body = _get(_client("HR"), {"layout": "chart", "lby": "dept", "junk": "1"})
    page = body["layout_page"]
    assert "junk" not in page["query"]
    assert page["clear_rules_url"].startswith(PATH)
    hrefs = [href for href in _hrefs(page) if href]
    assert hrefs, "the chart should link its categories"
    assert all(href.startswith(PATH) for href in hrefs)
    assert all("junk" not in href for href in hrefs)


def test_redirect_answer_has_no_layout_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    client = _client("HR")
    author = _user("HR")
    SavedView.objects.create(
        report=KEY, name="Үндсэн", query="layout=chart&lby=dept", author=author, visibility="shared", is_default=True
    )
    body = _get(client)
    assert body["redirect"].startswith(f"{PATH}?")
    assert body["layout_page"] is None
    assert body["table"] is None
    assert body["head"] is None


# --- the values of each payload, against the service's own dataclasses ---------------------------------------------
# A dropped, renamed or mistyped field fails here: the answer must equal the service's dataclass field for field.


def _service(report: Report, query: dict[str, str]) -> layout_service.LayoutPage:
    """The service's layout page for these query parameters, built the way the API builds it (plain: saved views)."""
    user = _user("HR")
    params = QueryDict(urlencode(query))
    table = build_table(report, user, parse_filters(params))
    page = layout_service.layout_page(params, PATH, user, report, table, [], True)
    assert page is not None
    return page


def _plain(node: Any) -> Any:
    """A service dataclass as the JSON the API answers: its fields by name, tuples as lists."""
    return json.loads(json.dumps(dataclasses.asdict(node)))


def _expected_pivot(pivot: layout_service.PivotOut) -> dict[str, Any]:
    """The pivot as the API answers it: column heads and cells as {label, href} and {text, href} objects."""
    grids = []
    for grid in pivot.grids:
        plain = _plain(grid)
        plain["col_heads"] = [{"label": label, "href": href} for label, href in grid.col_heads]
        plain["rows"] = [
            {**_plain(row), "cells": [{"text": text, "href": href} for text, href in row.cells]} for row in grid.rows
        ]
        grids.append(plain)
    return {"grids": grids}


def test_board_values_match_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _register(monkeypatch)
    query = {"layout": "board", "lby": "dept"}
    board = _get(_client("HR"), query)["layout_page"]["board"]
    expected = _service(report, query).board
    assert expected is not None
    assert expected.lanes, "the board needs lanes to check"
    assert board == _plain(expected)
    lane, expected_lane = board["lanes"][0], expected.lanes[0]
    assert lane["label"] == expected_lane.label
    assert lane["count"] == expected_lane.count
    assert lane["href"] == expected_lane.href
    assert lane["cards"][0]["title"] == expected_lane.cards[0].title
    assert lane["cards"][0]["href"] == expected_lane.cards[0].href
    assert board["total"] == len(_rows())


def test_cards_values_match_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _register(monkeypatch)
    query = {"layout": "cards"}
    cards = _get(_client("HR"), query)["layout_page"]["cards"]
    expected = _service(report, query).cards
    assert expected is not None
    assert expected.items, "the cards need items to check"
    assert cards == _plain(expected)
    assert cards["items"][0]["title"] == expected.items[0].title
    assert cards["items"][0]["href"] == expected.items[0].href
    assert cards["total"] == len(_rows())
    assert cards["next_offset"] is None


def test_calendar_values_match_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _register(monkeypatch)
    query = {"layout": "calendar", "lmonth": "2026-11"}
    calendar = _get(_client("HR"), query)["layout_page"]["calendar"]
    expected = _service(report, query).calendar
    assert expected is not None
    assert calendar == _plain(expected)
    assert calendar["heading"] == expected.heading
    for field in ("prev_href", "next_href", "today_href", "switch_href"):
        assert calendar[field] == getattr(expected, field)
    day = next(d for week in calendar["weeks"] for d in week if d["entries"])
    expected_day = next(d for week in expected.weeks for d in week if d.entries)
    assert day["iso"] == expected_day.iso
    assert day["entries"][0]["title"] == expected_day.entries[0].title
    assert day["entries"][0]["href"] == expected_day.entries[0].href


def test_timeline_values_match_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _register(monkeypatch)
    query = {"layout": "timeline", "lyear": "2026"}
    timeline = _get(_client("HR"), query)["layout_page"]["timeline"]
    expected = _service(report, query).timeline
    assert expected is not None
    assert timeline == _plain(expected)
    group, expected_group = timeline["groups"][0], expected.groups[0]
    assert group["label"] == expected_group.label
    assert group["count"] == expected_group.count
    assert expected_group.bars, "the timeline needs bars to check"
    bar, expected_bar = group["bars"][0], expected_group.bars[0]
    assert bar["title"] == expected_bar.title
    assert bar["left_pct"] == expected_bar.left_pct
    assert bar["width_pct"] == expected_bar.width_pct
    assert isinstance(bar["left_pct"], float)
    assert isinstance(bar["width_pct"], float)
    assert timeline["ticks"][0]["label"] == expected.ticks[0].label
    assert timeline["ticks"][0]["left_pct"] == expected.ticks[0].left_pct
    assert timeline["year"] == 2026


def test_pivot_values_match_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _register(monkeypatch)
    query = {"layout": "pivot", "lby": "dept", "lby2": "name"}
    pivot = _get(_client("HR"), query)["layout_page"]["pivot"]
    expected = _service(report, query).pivot
    assert expected is not None
    assert pivot == _expected_pivot(expected)
    grid, expected_grid = pivot["grids"][0], expected.grids[0]
    assert grid["corner_label"] == expected_grid.corner_label
    assert grid["grand"] == expected_grid.grand
    assert grid["col_heads"][0] == {"label": expected_grid.col_heads[0][0], "href": expected_grid.col_heads[0][1]}
    row, expected_row = grid["rows"][0], expected_grid.rows[0]
    assert row["label"] == expected_row.label
    assert row["href"] == expected_row.href
    assert row["total"] == expected_row.total
    assert row["cells"][0] == {"text": expected_row.cells[0][0], "href": expected_row.cells[0][1]}
    assert expected_grid.rows[0].cells[0][1], "a pivot cell links to its rows"
