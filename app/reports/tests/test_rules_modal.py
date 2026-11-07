"""The «Шүүлтүүр» pop-up: the conditions the user may use, the current ones, and the summary line on the report page."""

import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse

from reports import rules as rules_mod
from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "rules-modal-test"
SCORE_RULE = '{"op":"and","items":[{"c":"score","o":"gt","v":"2"}]}'
MIXED_RULE = '{"op":"and","items":[{"c":"score","o":"gt","v":"2"},{"c":"pay","o":"gt","v":"0"}]}'


def _people() -> list[Any]:
    return [
        SimpleNamespace(name="Бат", score=1, pay=1000, start=date(2026, 1, 5)),
        SimpleNamespace(name="Дорж", score=3, pay=2000, start=date(2026, 2, 5)),
    ]


def _report(monkeypatch: pytest.MonkeyPatch, **changes: Any) -> Report:
    """Name and score are shown to HR; pay needs the salary permission; start is a date."""
    report = Report(
        key=KEY,
        title="Шүүлтүүрийн тайлан",
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


def test_modal_offers_only_the_columns_the_user_may_see(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")  # view_personal, no view_salary
    response = client.get(reverse("reports:rules", args=[KEY]))
    assert response.status_code == 200
    columns = _json_script(response.content.decode(), "rules-columns")
    assert columns == [
        {"key": "name", "label": "Нэр", "kind": "text"},
        {"key": "score", "label": "Оноо", "kind": "number"},
        {"key": "start", "label": "Эхэлсэн огноо", "kind": "date"},
    ]
    assert "pay" not in response.content.decode()


def test_rules_json_keeps_only_the_allowed_columns(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    response = client.get(reverse("reports:rules", args=[KEY]), {"rules": MIXED_RULE})
    assert response.status_code == 200
    assert response.context["rules_json"] == SCORE_RULE
    assert _json_script(response.content.decode(), "rules-current") == SCORE_RULE
    assert "macs.view_salary" not in response.content.decode()


def test_rules_json_is_empty_without_rules(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    response = client.get(reverse("reports:rules", args=[KEY]))
    assert response.context["rules_json"] == ""


def test_keep_inputs_carry_other_filters_but_not_rules(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    response = client.get(reverse("reports:rules", args=[KEY]), {"state": "all", "rules": SCORE_RULE})
    page = response.content.decode()
    action = reverse("reports:report", args=[KEY])
    assert f'action="{action}"' in page and 'method="get"' in page
    pairs = re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)"', page)
    assert ("state", "all") in pairs
    assert [value for name, value in pairs if name == "rules" and value] == []  # the rules text is never kept


def test_statistic_report_has_no_rules_pop_up(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch, shows_count=False)
    login_as(client, "HR")
    assert client.get(reverse("reports:rules", args=[KEY])).status_code == 404


def test_pop_up_needs_the_report_permission(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "Employee", name="plain")
    assert client.get(reverse("reports:rules", args=[KEY])).status_code == 403


def test_ops_json_has_the_operator_codes_of_each_kind(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    page = client.get(reverse("reports:rules", args=[KEY])).content.decode()
    ops = _json_script(page, "rules-ops")
    assert {kind: [item["code"] for item in items] for kind, items in ops.items()} == {
        kind: list(codes) for kind, codes in rules_mod.OPS.items()
    }
    assert {item["label"] for item in ops["number"]} >= {"тэнцүү", "хооронд"}


def test_report_page_shows_the_summary_with_the_column_label(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    page = client.get(reverse("reports:report", args=[KEY]), {"rules": SCORE_RULE}).content.decode()
    assert "Нөхцөл: Оноо" in page
    assert "Засах" in page and "Цэвэрлэх" in page
    label = re.search(r"Нөхцөл:[^<]*", page)
    assert label is not None
    assert "score" not in label.group(0)  # the label, never the key


def test_report_page_has_no_summary_without_rules(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    page = client.get(reverse("reports:report", args=[KEY])).content.decode()
    assert "Нөхцөл:" not in page


def test_clear_link_is_the_address_without_rules(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    response = client.get(reverse("reports:report", args=[KEY]), {"cols": "score", "rules": SCORE_RULE})
    clear = response.context["clear_rules_url"]
    assert "rules=" not in clear
    assert "cols=score" in clear
    assert f'href="{clear}"' in response.content.decode()


def test_shuulter_button_on_the_staff_list(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get(reverse("reports:report", args=["staff-list"])).content.decode()
    assert "Шүүлтүүр" in page
    assert 'hx-get="/reports/staff-list/rules/?' in page


def test_no_shuulter_button_for_a_statistic_report(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch, shows_count=False)
    login_as(client, "HR")
    page = client.get(reverse("reports:report", args=[KEY])).content.decode()
    assert ">Шүүлтүүр</button>" not in page
    assert "/rules/" not in page


def test_rule_text_is_escaped_in_the_page_and_the_pop_up(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    rule = json.dumps({"op": "and", "items": [{"c": "name", "o": "contains", "v": "</script><b>"}]})
    modal = client.get(reverse("reports:rules", args=[KEY]), {"rules": rule}).content.decode()
    assert "</script><b>" not in modal
    assert "\\u003C/script" in modal
    report_page = client.get(reverse("reports:report", args=[KEY]), {"rules": rule}).content.decode()
    assert "</script><b>" not in report_page


def test_pop_up_carries_the_switch_off_and_group_delete_wording(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    page = client.get(reverse("reports:rules", args=[KEY])).content.decode()
    assert "Бүх нөхцөл нэгэн зэрэг биелсэн байх болно. Үргэлжлүүлэх үү?" in page
    assert "Бүлгийг бүх нөхцөлтэй нь хасах уу?" in page


def test_exponent_number_is_kept_in_the_rules_json(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    rule = '{"op":"and","items":[{"c":"score","o":"gt","v":"1e5"}]}'
    response = client.get(reverse("reports:rules", args=[KEY]), {"rules": rule})
    assert response.context["rules_json"] == rule  # the server reads 1e5 as a number now


def test_error_line_is_hidden_until_needed(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    page = client.get(reverse("reports:rules", args=[KEY])).content.decode()
    error = re.search(r"<p data-rules-error[^>]*>", page)
    assert error is not None
    assert "hidden" in error.group(0) and "role=" not in error.group(0)
