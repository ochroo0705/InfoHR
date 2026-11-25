"""GET /api/v1/reports/{key}/columns, /rules and /format: the models of the «Багана сонгох», «Шүүлтүүр» and «Хэлбэр»
pop-ups, as React draws them.

The rules come from reports.services.popups; these tests pin the API's shape, its rights (401 without a login, 403 when
the user cannot open the report, 404 for an unknown key or a report without the feature), the no-store header, the
`keep` pairs, and the review-focus inputs: a column the user may not see never reaches the body, and an `add` chip
survives the round trip.
"""

from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from reports.registry import REPORTS
from reports.types import Column, Report

from api.popups import FORBIDDEN, NOT_FOUND
from api.tests.logs_support import NOT_LOGGED_IN

pytestmark = pytest.mark.django_db

KEY = "api-report-popup-test"
BASE = f"/api/v1/reports/{KEY}"
COLUMNS_URL = f"{BASE}/columns"
RULES_URL = f"{BASE}/rules"
FORMAT_URL = f"{BASE}/format"
ALL_URLS = (COLUMNS_URL, RULES_URL, FORMAT_URL)
NOT_FOUND_BODY = {"field_errors": {}, "form_errors": [NOT_FOUND]}
FORBIDDEN_BODY = {"field_errors": {}, "form_errors": [FORBIDDEN], "code": "forbidden"}
SECRET_SALARY = 731415
RULE_ON_SALARY = '{"op":"and","items":[{"c":"salary","o":"gt","v":"0"}]}'
RULE_ON_NAME = '{"op":"and","items":[{"c":"name","o":"eq","v":"Бат"}]}'
MARK_ON_SALARY = '[{"c":"salary","o":"gt","v":"0","k":"red"}]'

COLUMNS_KEYS = {"groups", "group_choices", "group", "group_text", "keep"}
RULES_KEYS = {"columns", "ops", "rules", "keep"}
FORMAT_KEYS = {"columns", "shown", "ops", "aggs", "agg_labels", "colours", "totals", "marks", "pin", "keep"}


def _client(role: str | None) -> Client:
    client = Client()
    if role is not None:
        name = f"report_popup_api_{role.lower()}"
        user = User.objects.filter(username=name).first()
        if user is None:  # a test may ask for the same role twice
            user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
            user.groups.add(Group.objects.get(name=role))
        client.force_login(User.objects.get(pk=user.pk))
    return client


def _register(
    monkeypatch: pytest.MonkeyPatch,
    *,
    picks: bool = True,
    count: bool = True,
    column_filters: tuple[str, ...] = (),
    extra: tuple[Column, ...] = (),
) -> Report:
    """A report with a name column (everyone) and a salary column (macs.view_salary: HR lacks it)."""
    report = Report(
        key=KEY,
        title="Тестийн тайлан",
        filters=("state",),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, group="Ажилтан"),
            Column(
                key="salary",
                label="Цалин",
                value=lambda r: r.salary,
                group="Цалин",
                needs="macs.view_salary",
                numeric=True,
                money=True,
            ),
            *extra,
        ),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=("name",),
        picks_columns=picks,
        shows_count=count,
        column_filters=column_filters,
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _get(client: Client, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.get(url, params or {})
    assert response.status_code == 200, response.content.decode()
    body: dict[str, Any] = response.json()
    return body


def _text(body: Any) -> str:
    """Every string in an answer, joined: to look for a value that must not appear anywhere."""
    if isinstance(body, dict):
        return " ".join(_text(v) for v in body.values())
    if isinstance(body, list):
        return " ".join(_text(v) for v in body)
    return "" if body is None else str(body)


# --- rights and the unknown key -----------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ALL_URLS)
def test_models_require_login(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _register(monkeypatch)
    response = _client(None).get(url)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_columns_404_for_report_without_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch, picks=False)
    response = _client("HR").get(COLUMNS_URL)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY
    assert _client("HR").get(RULES_URL).status_code == 200  # the picker's absence does not hide the other pop-ups


def test_rules_and_format_404_for_statistic_report(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch, count=False)
    client = _client("HR")
    assert client.get(RULES_URL).status_code == 404
    assert client.get(FORMAT_URL).status_code == 404
    assert client.get(COLUMNS_URL).status_code == 200


def test_unknown_report_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    client = _client("HR")
    for url in ("/api/v1/reports/no-such-report/columns", "/api/v1/reports/no-such-report/rules"):
        assert client.get(url).status_code == 404


@pytest.mark.parametrize("url", ALL_URLS)
def test_403_when_user_cannot_open(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _register(monkeypatch)
    response = _client("Employee").get(url)  # an Employee has no reports.view_reports
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_BODY


# --- shape --------------------------------------------------------------------------------------------------------


def test_columns_model_shape_and_keep(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    body = _get(_client("HR"), COLUMNS_URL, {"cols": "name", "group": "name", "state": "all"})
    assert set(body) == COLUMNS_KEYS
    assert [(g["title"], [(p["key"], p["checked"]) for p in g["picks"]]) for g in body["groups"]] == [
        ("Ажилтан", [("name", True)])
    ]  # HR does not see salary, so the «Цалин» group is absent
    assert body["group_choices"] == [{"key": "name", "label": "Нэр"}]
    assert body["group"] == "name"
    assert body["group_text"] == ""
    keep = [tuple(pair) for pair in body["keep"]]
    assert all(name not in ("cols", "group") for name, _ in keep)
    assert ("state", "all") in keep


def test_rules_model_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    body = _get(_client("HR"), RULES_URL, {"rules": RULE_ON_NAME, "cols": "name"})
    assert set(body) == RULES_KEYS
    assert body["columns"] == [{"key": "name", "label": "Нэр", "kind": "text"}]  # salary is not offered to HR
    assert "eq" in [op["code"] for op in body["ops"]["text"]]
    assert set(body["ops"]) == {"text", "number", "date"}
    assert body["rules"] != ""
    assert all(name != "rules" for name, _ in body["keep"])
    assert ["cols", "name"] in body["keep"]


def test_format_model_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    body = _get(_client("HR"), FORMAT_URL, {"cols": "name", "totals": "name:count", "pin": "1"})
    assert set(body) == FORMAT_KEYS
    assert body["columns"] == [{"key": "name", "label": "Нэр", "kind": "text"}]
    assert body["shown"] == ["name"]
    assert body["aggs"]["number"] == ["sum", "avg", "min", "max", "count"]
    assert body["aggs"]["date"] == ["min", "max", "count"]
    assert body["agg_labels"]["sum"] == "Нийлбэр"
    assert [c["key"] for c in body["colours"]] == ["red", "amber", "green", "blue", "grey"]
    assert body["totals"] == [["name", "count"]]
    assert body["marks"] == []
    assert body["pin"] == 1
    assert ["totals", "name:count"] not in body["keep"]
    assert ["cols", "name"] in body["keep"]


# --- review focus: what the user may not see never reaches the body -----------------------------------------------


def test_hidden_column_absent_from_whole_body(monkeypatch: pytest.MonkeyPatch) -> None:
    # HR lacks macs.view_salary: the salary column, its rule, its total, its colour mark and its group are all dropped
    _register(monkeypatch)
    params = {
        "cols": "name,salary",
        "group": "salary",
        "rules": RULE_ON_SALARY,
        "totals": "salary:sum",
        "marks": MARK_ON_SALARY,
    }
    for url in ALL_URLS:
        text = _text(_get(_client("HR"), url, params))
        assert "Цалин" not in text, url
        assert "salary" not in text, url
        assert str(SECRET_SALARY) not in text, url


# --- review focus: an add chip survives the round trip ------------------------------------------------------------


def test_add_chips_survive_in_keep(monkeypatch: pytest.MonkeyPatch) -> None:
    hired = Column(key="first_hire_date", label="Ажилд орсон", value=lambda r: "")
    _register(monkeypatch, column_filters=("hired",), extra=(hired,))
    client = _client("HR")
    for url in (COLUMNS_URL, RULES_URL, FORMAT_URL):
        body = _get(client, url, {"add": "hired"})
        assert body["keep"].count(["add", "hired"]) == 1, url


# --- no-store ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ALL_URLS)
def test_popup_no_store(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _register(monkeypatch)
    assert _client("HR").get(url).headers["Cache-Control"] == "no-store"
