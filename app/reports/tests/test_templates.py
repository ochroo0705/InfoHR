"""Starter templates («Загвар»): built from rules, listed read-only beside the saved views, and filtering their rows."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from reports.filters import parse_filters
from reports.registry import REPORTS
from reports.rules import Group, Rule, parse_rules
from reports.staff_list import REPORT as STAFF_REPORT
from reports.starter import rule_template
from reports.table import build_table
from reports.types import Column, Report, Template

from .conftest import legacy

pytestmark = pytest.mark.django_db

PAGE = "/reports/staff-list/"
GROUP_OPEN = '<optgroup label="Загвар">'
CONTRACT = "Гэрээ дуусах дөхсөн"
PROBATION = "Туршилтын хугацаа дуусах дөхсөн"
AGE = "Нас 55+"


def _template(name: str) -> Template:
    return next(t for t in STAFF_REPORT.templates if t.name == name)


def _group_html(page: str) -> str:
    """The text of the first «Загвар» optgroup on the page."""
    start = page.index(GROUP_OPEN)
    return page[start : page.index("</optgroup>", start)]


def test_rule_template_round_trips_to_the_same_rules() -> None:
    rules = (Rule("age", "gte", "55"), Rule("contract_end", "next_days", "60"))
    template = rule_template("Тест", *rules)
    assert template.name == "Тест"
    parsed = parse_rules(parse_filters(QueryDict(template.query)).rules)
    assert parsed == Group("and", rules)


def test_staff_list_has_the_three_starter_templates() -> None:
    assert [t.name for t in STAFF_REPORT.templates] == [CONTRACT, PROBATION, AGE]


def test_hr_sees_all_three_templates_inside_the_group(client: Client, login_hr: User) -> None:
    group = _group_html(client.get(PAGE).content.decode())
    for name in (CONTRACT, PROBATION, AGE):
        assert name in group


def test_accountant_without_personal_permission_misses_the_age_template(
    client: Client, login_as: Callable[..., User]
) -> None:
    login_as(client, "Accountant", "tpl-accountant")
    page = client.get(PAGE).content.decode()
    age_url = f"{PAGE}?{_template(AGE).query}"
    assert AGE not in page
    assert age_url not in page
    group = _group_html(page)
    assert CONTRACT in group and PROBATION in group


def _scored_report(monkeypatch: pytest.MonkeyPatch, templates: tuple[Template, ...]) -> Report:
    people = [
        SimpleNamespace(name="Бат", score=1),
        SimpleNamespace(name="Дорж", score=3),
        SimpleNamespace(name="Болд", score=5),
    ]
    report = Report(
        key="tpl-test",
        title="Загварын тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="score", label="Оноо", value=lambda r: r.score, numeric=True),
        ),
        default_columns=("name", "score"),
        rows=lambda user, filters: people,
        group_options=("name",),
        saved_views=True,
        templates=templates,
    )
    monkeypatch.setitem(REPORTS, "tpl-test", report)
    return report


def test_template_url_opens_and_its_rule_filters(monkeypatch: pytest.MonkeyPatch, login_hr: User) -> None:
    more_than_two = rule_template("Оноо 2-оос их", Rule("score", "gt", "2"))
    more_than_four = rule_template("Оноо 4-өөс их", Rule("score", "gt", "4"))
    _scored_report(monkeypatch, (more_than_two, more_than_four))
    url = reverse("reports:report", args=["tpl-test"]) + "?" + more_than_two.query
    client = Client()
    client.force_login(login_hr)
    response = client.get(url)
    assert response.status_code == 200
    page = response.content.decode()
    assert "Дорж" in page and "Болд" in page and "Бат" not in page


def test_the_matching_template_is_selected_and_the_plain_option_is_not(
    monkeypatch: pytest.MonkeyPatch, login_hr: User
) -> None:
    more_than_two = rule_template("Оноо 2-оос их", Rule("score", "gt", "2"))
    more_than_four = rule_template("Оноо 4-өөс их", Rule("score", "gt", "4"))
    _scored_report(monkeypatch, (more_than_two, more_than_four))
    base = reverse("reports:report", args=["tpl-test"])
    client = Client()
    client.force_login(login_hr)
    page = client.get(f"{base}?{more_than_two.query}").content.decode()
    assert f'value="{base}?{more_than_two.query}" selected>Оноо 2-оос их</option>' in page
    assert f'value="{base}?{more_than_four.query}">Оноо 4-өөс их</option>' in page
    assert f'value="{base}?view=plain" selected>' not in page


def test_templates_have_no_edit_button(monkeypatch: pytest.MonkeyPatch, login_hr: User) -> None:
    more_than_two = rule_template("Оноо 2-оос их", Rule("score", "gt", "2"))
    _scored_report(monkeypatch, (more_than_two,))
    client = Client()
    client.force_login(login_hr)
    page = client.get(f"{reverse('reports:report', args=['tpl-test'])}?{more_than_two.query}").content.decode()
    assert "Оноо 2-оос их" in page
    # the saved-view edit link is absent; the summary line's «Засах» opens the rules pop-up, which is allowed
    assert "/reports/views/" not in page


def test_a_report_without_templates_renders_no_optgroup(monkeypatch: pytest.MonkeyPatch, login_hr: User) -> None:
    _scored_report(monkeypatch, ())
    client = Client()
    client.force_login(login_hr)
    page = client.get(reverse("reports:report", args=["tpl-test"])).content.decode()
    assert "<optgroup" not in page


def test_staff_contract_template_url_returns_200(client: Client, login_hr: User) -> None:
    response = client.get(f"{PAGE}?{_template(CONTRACT).query}")
    assert response.status_code == 200


def test_template_rule_filters_rows_through_the_table(monkeypatch: pytest.MonkeyPatch, hr_user: User) -> None:
    more_than_two = rule_template("Оноо 2-оос их", Rule("score", "gt", "2"))
    report = _scored_report(monkeypatch, (more_than_two,))
    table = build_table(report, hr_user, parse_filters(QueryDict(more_than_two.query)))
    assert [cell[0].value for cell in table.groups[0][1]] == ["Дорж", "Болд"]


def test_date_templates_match_nobody_when_no_one_has_the_date(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    legacy(actor, job_values)  # no contract end and no probation end on record
    legacy(actor, job_values)
    plain = build_table(STAFF_REPORT, hr_user, parse_filters(QueryDict("")))
    assert plain.count >= 2
    for name in (CONTRACT, PROBATION):
        table = build_table(STAFF_REPORT, hr_user, parse_filters(QueryDict(_template(name).query)))
        assert table.count == 0, name
