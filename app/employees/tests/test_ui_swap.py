"""The personal tab's section swap (plan 2026-11-08-selection-motion, task 7).

detail.html (showTab) and sections.js (openGroup) find the tabs, the sections and the menu links by these hooks, and add
the swap-in class to the panel that comes into view. These tests keep the hooks in the markup and the class in the page
and in the script; they do not run the script (there is no DOM in the test run).
"""

import re
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from employees.models import Employee
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

SECTIONS_JS = Path(__file__).resolve().parents[2] / "static/js/sections.js"
FIELD_FOCUS_JS = Path(__file__).resolve().parents[2] / "static/js/employee_field_focus.js"


def _page(client: Client, employee: Employee) -> str:
    login_as(client, "HR")
    return client.get(reverse("employees:detail", args=[employee.pk])).content.decode()


def test_tab_sections_keep_their_ids(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    assert '<section id="tab-work"' in body
    assert '<section id="tab-personal"' in body


def test_tab_links_point_at_their_sections(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    # The horizontal tab bar (.tab, below lg) and the rail copy (.rtab) both carry href="#<tab>".
    assert '<a href="#work" class="tab"' in body
    assert '<a href="#personal" class="tab"' in body
    assert re.search(r'<a href="#work" class="rtab', body)
    assert re.search(r'<a href="#personal" class="rtab', body)


def test_personal_menu_hooks(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    start = body.index('id="personal-nav"')
    nav = body[start : body.index("</nav>", start)]
    assert 'data-pgroup-link="basic"' in nav
    assert 'href="#personal-basic"' in nav
    assert 'data-sec="identity"' in nav
    assert 'id="sec-identity"' in body
    assert re.search(r'data-pgroup="basic"', body)


def test_showtab_calls_swap_in_on_the_panel_that_comes_into_view(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    assert "swapIn(s)" in body, "detail.html showTab must call swapIn on the panel that becomes visible"
    assert "function swapIn(el)" in body
    assert "prefers-reduced-motion: reduce" in body[body.index("function swapIn(el)") :][:200], (
        "swapIn in detail.html must skip the class under prefers-reduced-motion"
    )


def test_openGroup_calls_swap_in_on_the_group_that_comes_into_view() -> None:
    js = SECTIONS_JS.read_text(encoding="utf-8")
    assert "swapIn(g)" in js, "sections.js openGroup must call swapIn on the group that loses data-off"
    assert "function swapIn(el)" in js
    assert re.search(r"function swapIn\(el\) \{\s*if \(reduce\) return;", js), (
        "sections.js swapIn must skip the class under prefers-reduced-motion"
    )


def test_field_focus_opens_closed_groups_quietly_through_the_hook() -> None:
    js = SECTIONS_JS.read_text(encoding="utf-8")
    assert re.search(
        r"window\.hrOpenGroup = function \(key, animate\) \{ pickGroup\(key, animate\); remember\(\); \};", js
    ), "sections.js must expose window.hrOpenGroup, which calls pickGroup and then remember()"
    focus = FIELD_FOCUS_JS.read_text(encoding="utf-8")
    assert "window.hrOpenGroup(name, false)" in focus, (
        "employee_field_focus.js must open a closed group quietly (no swap-in on first render)"
    )
