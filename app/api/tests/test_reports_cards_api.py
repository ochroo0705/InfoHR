"""GET /api/v1/reports/{key}/cards?offset=: one batch of the cards layout, as React reads it.

The batch is the cards the report page draws, from the offset, with next_offset set while a batch follows. These tests
pin the batches (two batches, no title repeated), the junk offsets that start at 0, the no-store header, the rights
(401, 403, 404), a non-cards address refused with 404 «not_found», a title that stays text, and a hidden column that
never reaches the answer.
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from config import batching
from django.contrib.auth.models import Group
from django.test import Client
from reports.registry import REPORTS
from reports.types import Column, Report

from api.tests.logs_support import FORBIDDEN, NOT_LOGGED_IN

pytestmark = pytest.mark.django_db

KEY = "api-cards-test"
URL = f"/api/v1/reports/{KEY}/cards"
LAYOUTS = ("board", "cards", "calendar", "timeline", "chart", "pivot")
NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
# a column no user holds (the permission does not exist): its key, label and values must never reach any answer
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
NAMES = ("Бат", "Дорж", "Сараа")


def _rows() -> list[Any]:
    return [
        SimpleNamespace(
            name=name, dept="Санхүү", start=date(2026, 11, 3 + i), pay=Decimal("1500000"), secret=SECRET_VALUE
        )
        for i, name in enumerate(NAMES)
    ]


def _register(monkeypatch: pytest.MonkeyPatch, rows: Any = _rows) -> Report:
    report = Report(
        key=KEY,
        title="Тестийн найрлага",
        filters=(),
        columns=(NAME, DEPT, START, PAY, SECRET),
        default_columns=("name", "dept"),
        rows=lambda user, filters: rows(),
        saved_views=True,
        layouts=LAYOUTS,
        group_options=("dept",),
        layout_date="start",
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _user(role: str) -> User:
    name = f"cards_api_{role.lower()}"
    user = User.objects.filter(username=name).first()
    if user is None:
        user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


def _client(role: str | None) -> Client:
    client = Client()
    if role is not None:
        client.force_login(_user(role))
    return client


def _get(client: Client, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.get(URL, params or {})
    assert response.status_code == 200, response.content.decode()
    body: dict[str, Any] = response.json()
    return body


def _titles(body: dict[str, Any]) -> list[str]:
    return [item["title"] for item in body["items"]]


def test_cards_route_batches_and_last_batch_next_offset_null(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    client = _client("HR")
    first = _get(client, {"layout": "cards"})
    assert len(first["items"]) == 2
    assert first["next_offset"] == 2
    assert first["total"] == len(NAMES)
    last = _get(client, {"layout": "cards", "offset": "2"})
    assert len(last["items"]) == 1
    assert last["next_offset"] is None
    assert last["total"] == len(NAMES)
    titles = _titles(first) + _titles(last)
    assert sorted(titles) == sorted(NAMES)
    assert len(set(titles)) == len(titles), "no title is repeated across the batches"


@pytest.mark.parametrize("junk", ["-1", "abc", "99999999999999999999"])
def test_cards_route_junk_offset_starts_at_zero(monkeypatch: pytest.MonkeyPatch, junk: str) -> None:
    _register(monkeypatch)
    client = _client("HR")
    default = _get(client, {"layout": "cards"})
    body = _get(client, {"layout": "cards", "offset": junk})
    assert body == default
    assert body["next_offset"] is None


def test_cards_route_is_no_store(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    response = _client("HR").get(URL, {"layout": "cards"})
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"


def test_unknown_key_404_forbidden_403_anonymous_401_on_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    assert _client("HR").get("/api/v1/reports/no-such-report/cards").status_code == 404
    forbidden = _client("Employee").get(URL, {"layout": "cards"})  # an Employee has no reports.view_reports
    assert forbidden.status_code == 403
    assert forbidden.json() == FORBIDDEN
    anonymous = _client(None).get(URL, {"layout": "cards"})
    assert anonymous.status_code == 401
    assert anonymous.json() == NOT_LOGGED_IN


@pytest.mark.parametrize("layout", ["table", "board", "calendar", "timeline", "chart", "pivot"])
def test_cards_route_for_a_non_cards_layout_is_refused(monkeypatch: pytest.MonkeyPatch, layout: str) -> None:
    _register(monkeypatch)
    response = _client("HR").get(URL, {"layout": layout})
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"


def test_cards_title_html_stays_text(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "<img src=x onerror=alert(1)>&amp;"
    _register(
        monkeypatch,
        rows=lambda: [SimpleNamespace(name=raw, dept="Санхүү", start=date(2026, 11, 3), pay=Decimal("1"), secret=1)],
    )
    body = _get(_client("HR"), {"layout": "cards"})
    assert body["items"][0]["title"] == raw  # the answer carries the text as typed; React draws it as text


def test_hidden_column_never_in_cards_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    response = _client("HR").get(
        URL, {"layout": "cards", "columns": f"name,dept,start,pay,{SECRET_KEY}", "lby": SECRET_KEY}
    )
    assert response.status_code == 200
    raw = response.content.decode()
    assert SECRET_KEY not in raw
    assert SECRET_LABEL not in raw
    assert str(SECRET_VALUE) not in raw
    assert json.loads(raw)["total"] == len(NAMES)
