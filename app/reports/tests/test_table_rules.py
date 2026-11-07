"""The table applies the address rules, totals and marks to the columns the user may see, and no others."""

import json
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from reports import views
from reports.filters import Filters, parse_filters
from reports.models import SavedView
from reports.registry import REPORTS
from reports.table import build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

SALARY_RULE = '{"op":"and","items":[{"c":"pay","o":"gt","v":"0"}]}'
SCORE_RULE = '{"op":"and","items":[{"c":"score","o":"gt","v":"2"}]}'


def _people() -> list[Any]:
    return [
        SimpleNamespace(name="Бат", score=1, pay=1000),
        SimpleNamespace(name="Дорж", score=3, pay=2000),
        SimpleNamespace(name="Сараа", score=4, pay=None),
        SimpleNamespace(name="Болд", score=5, pay=500),
    ]


def _report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """Shows only the name by default; score is hidden, pay needs the salary permission."""
    report = Report(
        key="rules-test",
        title="Дүрмийн тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="score", label="Оноо", value=lambda r: r.score, numeric=True),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True),
        ),
        default_columns=("name",),
        rows=lambda user, filters: _people(),
        group_options=("name",),
    )
    monkeypatch.setitem(REPORTS, "rules-test", report)
    return report


def _filters(**params: str) -> Filters:
    """The filters as the address gives them (parse_filters), so the tests use the same path as the page."""
    return parse_filters(QueryDict(urlencode(params)))


def _names(table: Any) -> list[str]:
    return [cell[0].value for cell in table.groups[0][1]]


def test_rule_on_a_column_not_shown_still_filters(monkeypatch: pytest.MonkeyPatch, hr_user: User) -> None:
    report = _report(monkeypatch)
    table = build_table(report, hr_user, _filters(rules=SCORE_RULE))
    assert "score" not in [c.key for c in table.columns]  # the rule column is hidden
    assert _names(table) == ["Дорж", "Сараа", "Болд"]


def test_salary_rule_is_dropped_for_a_user_without_the_permission(
    monkeypatch: pytest.MonkeyPatch, hr_user: User
) -> None:
    report = _report(monkeypatch)
    plain = build_table(report, hr_user, Filters())
    with_rule = build_table(report, hr_user, _filters(rules=SALARY_RULE))
    assert [row for row in with_rule.groups[0][1]] == [row for row in plain.groups[0][1]]
    assert with_rule.count == plain.count == 4
    assert with_rule.filters.rules == ""
    assert with_rule.rules_text == ""


def test_salary_rule_applies_for_a_user_with_the_permission(
    monkeypatch: pytest.MonkeyPatch, accountant_user: User
) -> None:
    report = _report(monkeypatch)
    table = build_table(report, accountant_user, _filters(rules=SALARY_RULE))
    assert _names(table) == ["Бат", "Дорж", "Болд"]  # Сараа has no pay
    assert table.filters.rules != ""


def test_salary_totals_and_marks_are_dropped_for_a_user_without_the_permission(
    monkeypatch: pytest.MonkeyPatch, hr_user: User, accountant_user: User
) -> None:
    report = _report(monkeypatch)
    marks = '[{"c":"pay","o":"gt","v":"0","k":"red"},{"c":"score","o":"gt","v":"2","k":"green"}]'
    params = {"totals": "pay:sum,score:max", "marks": marks}
    hidden = build_table(report, hr_user, _filters(**params))
    assert hidden.filters.totals == "score:max"
    assert '"pay"' not in hidden.filters.marks
    assert '"score"' in hidden.filters.marks  # the score mark survives: it is a column the user may see
    seen = build_table(report, accountant_user, _filters(**params))
    assert seen.filters.totals == "pay:sum,score:max"
    assert '"pay"' in seen.filters.marks


def test_count_is_the_number_of_filtered_rows(monkeypatch: pytest.MonkeyPatch, hr_user: User) -> None:
    report = _report(monkeypatch)
    table = build_table(report, hr_user, _filters(rules=SCORE_RULE))
    assert table.count == 3
    assert table.count == len(table.groups[0][1])


def test_garbage_rules_leave_the_table_unfiltered(monkeypatch: pytest.MonkeyPatch, hr_user: User) -> None:
    report = _report(monkeypatch)
    for text in ("{nope", "[1,2,3]", '{"op":"and","items":[{"c":"score","o":"gt"', "x" * 3000):
        table = build_table(report, hr_user, _filters(rules=text))
        assert table.count == 4
        assert table.filters.rules == ""


def test_known_only_keeps_each_sort_and_group_key(monkeypatch: pytest.MonkeyPatch) -> None:
    report = Report(
        key="known-test",
        title="Тест",
        filters=(),
        columns=(
            Column(key="department", label="Хэлтэс", value=lambda r: r),
            Column(key="position", label="Албан тушаал", value=lambda r: r),
            Column(key="salary", label="Цалин", value=lambda r: r),
        ),
        default_columns=("department",),
        rows=lambda user, filters: [],
        group_options=("department", "position"),
    )
    kept = views._known_only(report, Filters(sort="department,-salary", group="department,position"))
    assert kept.sort == "department,-salary"
    assert kept.group == "department,position"
    dropped = views._known_only(report, Filters(sort="department,-nope,-salary", group="nope,position"))
    assert dropped.sort == "department,-salary"
    assert dropped.group == "position"


def test_print_names_the_rule_by_label_and_hides_the_hidden_column(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")  # HR may not see salary
    rule = '{"op":"and","items":[{"c":"score","o":"gte","v":"3"},{"c":"pay","o":"gt","v":"0"}]}'
    url = reverse("reports:print", args=["rules-test"])
    response = client.get(url, {"rules": rule})
    assert response.status_code == 200
    lines = response.context["lines"]
    rule_lines = [line for line in lines if line.startswith("Нөхцөл:")]
    assert len(rule_lines) == 1
    assert rule_lines[0].startswith("Нөхцөл: Оноо")
    assert "Цалин" not in rule_lines[0]
    assert "pay" not in rule_lines[0]


# ---- saved views: a hidden column's rule must never be stored for, or shown to, a user who may not see it ----

LIMIT_VALUE = "7654321"
PAY_RULE = '{"op":"and","items":[{"c":"pay","o":"gt","v":"7654321"}]}'
SCORE_TEXT_RULE = '{"op":"and","items":[{"c":"score","o":"gt","v":"2"}]}'


def _saveable(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = replace(_report(monkeypatch), saved_views=True)
    monkeypatch.setitem(REPORTS, "rules-test", report)
    return report


def test_saved_view_leak_probe_hr_cannot_see_the_salary_threshold(
    client: Client, login_as: Callable[..., User]
) -> None:
    """The reviewer's probe on the real staff list: HR saves a salary rule, and no HR page shows the threshold."""
    login_as(client, "HR", "leak-author")
    rule = json.dumps({"op": "and", "items": [{"c": "salary", "o": "gt", "v": LIMIT_VALUE}]}, separators=(",", ":"))
    saved = client.post(
        reverse("reports:view_new", args=["staff-list"]), {"name": "Лийк", "query": urlencode({"rules": rule})}
    )
    assert saved.status_code == 204
    assert LIMIT_VALUE not in SavedView.objects.get(name="Лийк").query  # stored cleaned for the author
    assert LIMIT_VALUE not in client.get(reverse("reports:report", args=["staff-list"])).content.decode()
    other = Client()
    login_as(other, "HR", "leak-viewer")
    assert LIMIT_VALUE not in other.get(reverse("reports:report", args=["staff-list"])).content.decode()


def test_view_new_stores_the_query_cleaned_for_the_author(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _saveable(monkeypatch)
    login_as(client, "HR", "saver")
    query = urlencode({"rules": SCORE_TEXT_RULE, "totals": "pay:sum,score:max", "marks": "[]"})
    resp = client.post(reverse("reports:view_new", args=["rules-test"]), {"name": "Оноо", "query": query})
    assert resp.status_code == 204
    stored = SavedView.objects.get(name="Оноо").query
    assert "score" in stored and "pay" not in stored


def test_saved_view_options_are_cleaned_for_each_viewer(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _saveable(monkeypatch)
    SavedView.objects.create(report="rules-test", name="Зөвхөн цалин", query=urlencode({"rules": PAY_RULE}))
    login_as(client, "HR", "restricted")
    page = client.get(reverse("reports:report", args=["rules-test"]))
    option = next(o for o in page.context["saved_options"] if o.name == "Зөвхөн цалин")
    assert option.url == reverse("reports:report", args=[report.key]) + "?view=plain"  # name only, the plain address
    assert LIMIT_VALUE not in page.content.decode()


def test_print_and_excel_ignore_sort_and_group_on_a_hidden_column(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(monkeypatch)
    login_as(client, "HR")
    params = {"sort": "pay", "group": "name,score"}
    printed = client.get(reverse("reports:print", args=["rules-test"]), params)
    assert printed.status_code == 200
    assert printed.context["table"].filters.sort == ""
    excel = client.get(reverse("reports:excel", args=["rules-test"]), {"sort": "pay", "rules": PAY_RULE})
    assert excel.status_code == 200
    assert excel["Content-Type"].startswith("application/vnd.openxmlformats")


def test_group_list_drops_minus_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    report = Report(
        key="known-group",
        title="Тест",
        filters=(),
        columns=(
            Column(key="department", label="Хэлтэс", value=lambda r: r),
            Column(key="position", label="Албан тушаал", value=lambda r: r),
        ),
        default_columns=("department",),
        rows=lambda user, filters: [],
        group_options=("department", "position"),
    )
    kept = views._known_only(report, Filters(group="department,-position"))
    assert kept.group == "department"


# ---- fix round 2: column-filter thresholds and hidden keys are cleaned for the saver and for each viewer ----

STAFF = "staff-list"


def _option(page: Any, name: str) -> Any:
    return next(o for o in page.context["saved_options"] if o.name == name)


def test_hr_saved_salary_threshold_is_not_stored_nor_redirected(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "threshold-author")  # HR may not use the salary column filter
    resp = client.post(
        reverse("reports:view_new", args=[STAFF]),
        {"name": "Цалингүй", "query": "salary_from=7654321"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 204
    assert "salary" not in SavedView.objects.get(name="Цалингүй").query
    assert "salary" not in resp["HX-Redirect"] and "7654321" not in resp["HX-Redirect"]


def test_accountant_sees_no_salary_filter_from_an_hr_saved_view(client: Client, login_as: Callable[..., User]) -> None:
    author = Client()
    login_as(author, "HR", "threshold-hr")
    author.post(reverse("reports:view_new", args=[STAFF]), {"name": "Ажилтан", "query": "salary_from=7654321"})
    login_as(client, "Accountant", "threshold-acc")
    page = client.get(reverse("reports:report", args=[STAFF]))
    option = _option(page, "Ажилтан")
    assert "salary" not in option.url and "7654321" not in option.url
    opened = client.get(option.url)
    assert opened.context["filters"].extra == ()
    assert "7654321" not in opened.content.decode()


def test_accountant_saved_salary_threshold_is_not_shown_to_hr(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "threshold-acc2")
    client.post(reverse("reports:view_new", args=[STAFF]), {"name": "Цалин", "query": "salary_from=7654321"})
    hr = Client()
    login_as(hr, "HR", "threshold-hr2")
    page = hr.get(reverse("reports:report", args=[STAFF]))
    option = _option(page, "Цалин")
    assert "salary" not in option.url
    assert "7654321" not in page.content.decode()


def test_restricted_viewer_option_urls_carry_no_hidden_keys(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _saveable(monkeypatch)
    query = urlencode([("cols", "name"), ("cols", "pay"), ("sort", "-pay"), ("group", "name")])
    SavedView.objects.create(report="rules-test", name="Нуугдсан", query=query)
    login_as(client, "HR", "hidden-keys")
    page = client.get(reverse("reports:report", args=["rules-test"]))
    url = _option(page, "Нуугдсан").url
    assert "cols=name" in url and "cols=pay" not in url
    assert "sort" not in url and "pay" not in url
    assert "group=name" in url


def test_fully_visible_saved_view_is_selected_for_the_viewer(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _saveable(monkeypatch)
    query = urlencode([("cols", "name"), ("cols", "score"), ("rules", SCORE_TEXT_RULE)])
    SavedView.objects.create(report="rules-test", name="Бүтэн", query=query)
    login_as(client, "HR", "visible-view")
    url = _option(client.get(reverse("reports:report", args=["rules-test"])), "Бүтэн").url
    opened = client.get(url)
    assert opened.context["current_view"] is not None
    assert opened.context["current_view"].name == "Бүтэн"
    assert _option(opened, "Бүтэн").selected is True
