"""Click-through from a layout to the table: a chart bar, a pivot cell and a board lane each link to the rows of their
category (the address with the layout dropped and one more rule)."""

import html
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from accounts.models import User
from django.test import Client
from employees.services import macs_writes

from reports import rules as rules_mod

from .conftest import legacy

pytestmark = pytest.mark.django_db

STAFF = "/reports/staff-list/"
CHART_JSON = re.compile(r'<script id="report-chart-data" type="application/json">(.*?)</script>', re.S)
DEPT_A = "Алфа хэлтэс"
DEPT_B = "Бета хэлтэс"


@pytest.fixture
def staff(actor: User, job_values: dict[str, Any]) -> dict[str, Any]:
    """Two people in department A (both in the position «Нягтлан»), one in B with another position, and one with no
    department."""
    dept_a = macs_writes.save_department(DEPT_A)
    dept_b = macs_writes.save_department(DEPT_B)
    position_b = macs_writes.save_position("Ахлах нягтлан")
    legacy(actor, job_values, department=dept_a)
    legacy(actor, job_values, department=dept_a)
    legacy(actor, job_values, department=dept_b, position=position_b)
    legacy(actor, job_values, department=None, given_name="Онцгой")
    return {"a": DEPT_A, "b": DEPT_B}


def _chart_data(page: str) -> dict[str, Any]:
    match = CHART_JSON.search(page)
    assert match is not None, "no report-chart-data script"
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def _query(href: str) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(html.unescape(href)).query, keep_blank_values=True)


def _rules_of(href: str) -> rules_mod.Group | None:
    values = [value for key, value in _query(href) if key == "rules"]
    assert len(values) == 1, href
    return rules_mod.parse_rules(values[0])


def _rule_links(page: str) -> list[str]:
    """Every link of the page whose address carries a rules parameter (the layout bar's links carry none)."""
    hrefs = [html.unescape(href) for href in re.findall(r'<a href="([^"]+)"', page)]
    return [href for href in hrefs if any(key == "rules" for key, _ in _query(href))]


def _link_to(page: str, label: str) -> str:
    """The href of the link whose text is `label` (the chart table's category cell, a pivot header, a lane heading)."""
    match = re.search(rf'<a href="([^"]+)"[^>]*>{re.escape(label)}</a>', page)
    assert match is not None, label
    return html.unescape(match.group(1))


def _anchor_text(page: str, href: str) -> str:
    """The text inside the link whose address is `href`, tags stripped: the figure a pivot cell shows."""
    for found, inner in re.findall(r'<a href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        if html.unescape(found) == href:
            return re.sub(r"<[^>]+>", "", inner).strip()
    raise AssertionError(href)


def _lane_link(page: str, label: str) -> tuple[str, int]:
    """The href and the count of the board lane heading «<label> · <count>»."""
    match = re.search(rf'<a href="([^"]+)"[^>]*>{re.escape(label)} · (\d+)</a>', page)
    assert match is not None, label
    return html.unescape(match.group(1)), int(match.group(2))


def _count_line(client: Client, href: str) -> str:
    resp = client.get(href)
    assert resp.status_code == 200, href
    text = resp.content.decode()
    match = re.search(r"Нийт: \d+", text)
    assert match is not None, href
    return match.group(0)


# ---- the chart ----


def test_chart_category_links_to_the_table_of_its_rows(client: Client, login_hr: User, staff: dict[str, Any]) -> None:
    page = client.get(STAFF, {"layout": "chart", "lby": "department"}).content.decode()
    data = _chart_data(page)
    href = _link_to(page, DEPT_A)
    assert "layout" not in dict(_query(href))
    assert _rules_of(href) == rules_mod.Group(op="and", items=(rules_mod.Rule("department", "eq", DEPT_A),))
    shown = int(data["values"][data["labels"].index(DEPT_A)])
    assert _count_line(client, href) == f"Нийт: {shown}"


def test_chart_json_has_one_href_per_label(client: Client, login_hr: User, staff: dict[str, Any]) -> None:
    page = client.get(STAFF, {"layout": "chart", "lby": "department"}).content.decode()
    data = _chart_data(page)
    assert len(data["hrefs"]) == len(data["labels"]) == 3
    assert data["hrefs"][0] != ""
    assert _rules_of(data["hrefs"][0]) is not None


def test_chart_blank_category_link_uses_the_empty_operator(
    client: Client, login_hr: User, staff: dict[str, Any]
) -> None:
    page = client.get(STAFF, {"layout": "chart", "lby": "department"}).content.decode()
    data = _chart_data(page)
    assert data["labels"][-1] == "—"
    href = data["hrefs"][-1]
    rules = _rules_of(href)
    assert rules is not None and rules.items == (rules_mod.Rule("department", "empty", ""),)
    resp = client.get(href)
    assert resp.status_code == 200
    assert "Онцгой" in resp.content.decode()


def test_chart_link_keeps_the_existing_rules_and_adds_the_category(
    client: Client, login_hr: User, staff: dict[str, Any]
) -> None:
    existing = rules_mod.dump_rules(rules_mod.Group(op="and", items=(rules_mod.Rule("position", "eq", "Нягтлан"),)))
    page = client.get(STAFF, {"layout": "chart", "lby": "department", "rules": existing}).content.decode()
    data = _chart_data(page)
    href = _link_to(page, DEPT_A)
    assert _rules_of(href) == rules_mod.Group(
        op="and",
        items=(rules_mod.Rule("position", "eq", "Нягтлан"), rules_mod.Rule("department", "eq", DEPT_A)),
    )
    shown = int(data["values"][data["labels"].index(DEPT_A)])
    assert _count_line(client, href) == f"Нийт: {shown}"


def test_chart_labels_that_differ_only_by_case_get_no_link(
    client: Client, login_hr: User, actor: User, job_values: dict[str, Any]
) -> None:
    # «Борлуулалт» and «БОРЛУУЛАЛТ» would both keep both rows under the rule's comparison: neither is a link
    legacy(actor, job_values, department=macs_writes.save_department("Борлуулалт"))
    legacy(actor, job_values, department=macs_writes.save_department("БОРЛУУЛАЛТ"))
    legacy(actor, job_values, department=macs_writes.save_department("Санхүү"))
    page = client.get(STAFF, {"layout": "chart", "lby": "department"}).content.decode()
    data = _chart_data(page)
    for label in ("Борлуулалт", "БОРЛУУЛАЛТ"):
        assert data["hrefs"][data["labels"].index(label)] == ""
        assert f">{label}</a>" not in page
    assert data["hrefs"][data["labels"].index("Санхүү")] != ""


def test_drawn_category_gets_no_link_when_a_folded_one_collides_with_it(
    client: Client, login_hr: User, actor: User, job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # With two categories drawn, the first one is drawn and the rest fold into «Бусад». The folded «АЛФА» rows match
    # the drawn «Алфа» rule too, so the drawn bar must not link either.
    monkeypatch.setattr("reports.layouts.CHART_CAP", 2)
    for name in ("Алфа", "АЛФА", "Яя"):
        legacy(actor, job_values, department=macs_writes.save_department(name))
    page = client.get(STAFF, {"layout": "chart", "lby": "department"}).content.decode()
    data = _chart_data(page)
    assert data["labels"][0] in ("Алфа", "АЛФА")
    assert data["labels"][1] == "Бусад"
    assert data["hrefs"] == ["", ""]


# ---- the pivot ----


def test_pivot_cell_link_carries_both_rules_and_gives_the_cell_count(
    client: Client, login_hr: User, staff: dict[str, Any]
) -> None:
    page = client.get(STAFF, {"layout": "pivot", "lby": "department", "lby2": "position"}).content.decode()
    expected = rules_mod.Group(
        op="and",
        items=(rules_mod.Rule("department", "eq", DEPT_A), rules_mod.Rule("position", "eq", "Нягтлан")),
    )
    matches = [href for href in _rule_links(page) if _rules_of(href) == expected]
    assert len(matches) == 1, matches
    href = matches[0]
    shown = _anchor_text(page, href)
    assert shown.isdigit(), shown
    assert _count_line(client, href) == f"Нийт: {shown}"


# ---- the board ----


def test_board_lane_heading_links_to_the_table_of_its_lane(
    client: Client, login_hr: User, staff: dict[str, Any]
) -> None:
    page = client.get(STAFF, {"layout": "board", "lby": "department"}).content.decode()
    href, lane_count = _lane_link(page, DEPT_A)
    assert "layout" not in dict(_query(href))
    assert _count_line(client, href) == f"Нийт: {lane_count}"
