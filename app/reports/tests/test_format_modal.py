"""The «Хэлбэр» pop-up: the totals, pinned columns and colour rules the user may use, the current ones, and the other
filters kept as hidden inputs."""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse

from reports import marks as marks_mod
from reports import rules as rules_mod
from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "format-modal-test"
SCORE_RULE = '{"op":"and","items":[{"c":"score","o":"gt","v":"2"}]}'
SCORE_MARK = '[{"c":"score","o":"gt","v":"2","k":"red"}]'


def _people() -> list[Any]:
    return [
        SimpleNamespace(name="Бат", score=1, pay=1000, start=date(2026, 1, 5)),
        SimpleNamespace(name="Дорж", score=3, pay=2000, start=date(2026, 2, 5)),
    ]


def _report(monkeypatch: pytest.MonkeyPatch, **changes: Any) -> Report:
    """Name and score are shown to HR; pay needs the salary permission; start is a date."""
    report = Report(
        key=KEY,
        title="Хэлбэрийн тайлан",
        filters=("state",),  # declared, so the pop-up keeps it; an undeclared filter is dropped from the address
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="score", label="Оноо", value=lambda r: r.score, numeric=True),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True),
            Column(key="start", label="Эхэлсэн огноо", value=lambda r: r.start, kind="date"),
        ),
        default_columns=("name", "score"),
        rows=lambda user, filters: _people(),
        group_options=("name",),
    )
    report = replace(report, **changes)
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _json_script(page: str, element_id: str) -> Any:
    """The parsed JSON of a json_script element with this id."""
    match = re.search(rf'<script id="{element_id}" type="application/json">(.*?)</script>', page, re.S)
    assert match is not None, f"no json_script {element_id}"
    return json.loads(match.group(1))


def _modal(client: Client, params: Mapping[str, str | Sequence[str]] | None = None) -> Any:
    return client.get(reverse("reports:format", args=[KEY]), params or {})


def test_format_modal_is_200_for_hr(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    response = _modal(client)
    assert response.status_code == 200
    page = response.content.decode()
    assert "data-format-panel" in page and "Хэлбэр" in page
    assert f'action="{reverse("reports:report", args=[KEY])}"' in page and 'method="get"' in page


def test_offers_only_the_columns_the_user_may_see(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")  # view_personal, no view_salary
    page = _modal(client).content.decode()
    columns = _json_script(page, "format-columns")
    assert columns == [
        {"key": "name", "label": "Нэр", "kind": "text"},
        {"key": "score", "label": "Оноо", "kind": "number"},
        {"key": "start", "label": "Эхэлсэн огноо", "kind": "date"},
    ]


def test_a_hidden_column_is_absent_from_totals_and_marks_even_when_the_address_names_it(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    address = {
        "cols": ["name", "pay"],
        "totals": "pay:sum,score:avg",
        "marks": '[{"c":"pay","o":"gt","v":"0","k":"red"},{"c":"score","o":"gt","v":"2","k":"green"}]',
    }
    response = _modal(client, address)
    page = response.content.decode()
    assert _json_script(page, "format-totals") == [["score", "avg"]]
    assert _json_script(page, "format-marks") == [{"c": "score", "o": "gt", "v": "2", "k": "green"}]
    assert _json_script(page, "format-shown") == ["name"]  # pay is not shown to HR, so the shown list lacks it too


def test_current_totals_marks_and_pin_are_preselected(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    address = {"cols": ["name", "score"], "totals": "score:sum,name:count", "marks": SCORE_MARK, "pin": "2"}
    page = _modal(client, address).content.decode()
    assert _json_script(page, "format-totals") == [["score", "sum"], ["name", "count"]]
    assert _json_script(page, "format-marks") == [{"c": "score", "o": "gt", "v": "2", "k": "red"}]
    assert _json_script(page, "format-pin") == 2
    report_page = client.get(reverse("reports:report", args=[KEY]), address)
    shown = [c.key for c in report_page.context["table"].columns]
    assert _json_script(page, "format-shown") == shown == ["name", "score"]


def test_keep_inputs_hold_other_filters_and_rules_but_not_totals_marks_or_pin(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    address = {
        "state": "all",
        "rules": SCORE_RULE,
        "totals": "score:sum",
        "marks": SCORE_MARK,
        "pin": "1",
    }
    response = _modal(client, address)
    page = response.content.decode()
    kept = dict(response.context["keep"])
    assert kept.get("state") == "all"
    assert kept.get("rules") == SCORE_RULE
    assert not {"totals", "marks", "pin"} & set(kept)
    # the page's own hidden inputs: the kept filters carry a value, the totals, marks and pin boxes are empty
    pairs = re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)"', page)
    assert ("state", "all") in pairs
    assert [name for name, value in pairs if value and name in {"totals", "marks", "pin"}] == []


def test_statistic_report_has_no_format_pop_up(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch, shows_count=False)
    login_as(client, "HR")
    assert _modal(client).status_code == 404


def test_pop_up_needs_the_report_permission(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "Employee", name="plain")
    assert _modal(client).status_code == 403


def test_format_button_is_on_the_staff_list(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get(reverse("reports:report", args=["staff-list"])).content.decode()
    assert ">Хэлбэр</button>" in page
    assert 'hx-get="/reports/staff-list/format/?' in page


def test_no_format_button_for_a_statistic_report(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch, shows_count=False)
    login_as(client, "HR")
    page = client.get(reverse("reports:report", args=[KEY])).content.decode()
    assert ">Хэлбэр</button>" not in page
    assert "/format/" not in page


def test_marks_text_from_the_address_is_escaped_in_the_pop_up(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    mark = json.dumps([{"c": "name", "o": "contains", "v": "</script><b>", "k": "red"}])
    page = _modal(client, {"marks": mark}).content.decode()
    assert "</script><b>" not in page
    assert "\\u003C/script" in page
    assert _json_script(page, "format-marks")[0]["v"] == "</script><b>"


def test_ops_json_uses_the_exact_operator_codes(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    page = _modal(client).content.decode()
    ops = _json_script(page, "format-ops")
    assert {kind: [item["code"] for item in items] for kind, items in ops.items()} == {
        kind: list(codes) for kind, codes in rules_mod.OPS.items()
    }


def test_colours_json_has_five_colours_with_the_exact_classes(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    colours = _json_script(_modal(client).content.decode(), "format-colours")
    assert [c["key"] for c in colours] == ["red", "amber", "green", "blue", "grey"]
    assert [c["label"] for c in colours] == ["Улаан", "Шар", "Ногоон", "Цэнхэр", "Саарал"]
    assert {c["key"]: c["classes"] for c in colours} == marks_mod.COLOURS


def test_aggregates_offered_per_kind(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    aggs = _json_script(_modal(client).content.decode(), "format-aggs")
    assert aggs == {
        "number": ["sum", "avg", "min", "max", "count"],
        "date": ["min", "max", "count"],
        "text": ["count"],
    }
