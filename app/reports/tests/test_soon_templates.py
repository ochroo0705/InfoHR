"""The two «дөхсөн» starter templates read their window from CompanySettings.soon_days (default 30)."""

import html
import re
from typing import Any

import pytest
from django.http import QueryDict
from django.test import Client
from employees.models import CompanySettings

from reports.filters import parse_filters
from reports.rules import Group, Rule, parse_rules
from reports.staff_list import REPORT as STAFF_REPORT

pytestmark = pytest.mark.django_db

PAGE = "/reports/staff-list/"
GROUP_OPEN = '<optgroup label="Загвар">'
CONTRACT = "Гэрээ дуусах дөхсөн"
PROBATION = "Туршилтын хугацаа дуусах дөхсөн"
AGE = "Нас 55+"
SURVEYS = (
    "Өндөр настнууд (60+), холбоо барих",
    "Насны бүлэг, хүйсээр",
    "Хүйс, боловсролоор",
    "Гутлын хэмжээ, хүйсээр",
    "Хувцасны хэмжээ, хүйсээр",
)


def _group_html(page: str) -> str:
    """The text of the first «Загвар» optgroup on the page."""
    start = page.index(GROUP_OPEN)
    return page[start : page.index("</optgroup>", start)]


def _option_url(page: str, name: str) -> str:
    """The address the «Загвар» option `name` links to, unescaped."""
    match = re.search(rf'value="([^"]*)"[^>]*>{re.escape(name)}</option>', _group_html(page))
    assert match is not None, name
    return html.unescape(match.group(1))


def _rules_of(url: str) -> Any:
    query = url.split("?", 1)[1]
    return parse_rules(parse_filters(QueryDict(query)).rules)


def test_default_window_is_30_for_both(client: Client, login_hr: Any) -> None:
    page = client.get(PAGE).content.decode()
    assert _rules_of(_option_url(page, CONTRACT)) == Group("and", (Rule("contract_end", "next_days", "30"),))
    assert _rules_of(_option_url(page, PROBATION)) == Group("and", (Rule("probation_end", "next_days", "30"),))


def test_changing_the_setting_changes_both(client: Client, login_hr: Any) -> None:
    row = CompanySettings.get()
    row.soon_days = 45
    row.save()
    page = client.get(PAGE).content.decode()
    assert _rules_of(_option_url(page, CONTRACT)) == Group("and", (Rule("contract_end", "next_days", "45"),))
    assert _rules_of(_option_url(page, PROBATION)) == Group("and", (Rule("probation_end", "next_days", "45"),))


def test_template_order_and_names_unchanged() -> None:
    assert [t.name for t in STAFF_REPORT.templates] == [CONTRACT, PROBATION, AGE, *SURVEYS]
