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


def test_personal_group_hooks(client: Client, hired: Employee) -> None:
    """The topic groups are <details data-pgroup> with an id (#personal-<group>); basic is open, the rest closed."""
    body = _page(client, hired)
    assert 'id="personal-nav"' not in body
    assert re.search(r'<details data-pgroup="basic" id="personal-basic"[^>]*\sopen>', body)
    assert re.search(r'<details data-pgroup="edu" id="personal-edu"[^>]*>', body)
    assert 'id="sec-identity"' in body


def test_showtab_scrolls_to_the_section_instead_of_swapping_panels(client: Client, hired: Employee) -> None:
    """The three sections are stacked and all shown, so no panel swaps in: showTab scrolls to its section."""
    body = _page(client, hired)
    assert "swapIn" not in body, "detail.html no longer swaps panels in: every section is visible"
    assert "function showTab(name,quiet)" in body
    assert "s.scrollIntoView({behavior:quiet" in body, "showTab must scroll to #tab-<name> (smooth unless quiet)"
    assert "prefers-reduced-motion: reduce" in body[body.index("function showTab(name,quiet)") :][:400], (
        "showTab must scroll at once under prefers-reduced-motion"
    )


def test_openGroup_opens_the_details_element_without_swap_in() -> None:
    """A group is a <details>: opening it sets open, with no data-off and no swap-in (plan 2026-11-09 task 4)."""
    js = SECTIONS_JS.read_text(encoding="utf-8")
    assert "data-off" not in js, "sections.js must not hide groups with data-off any more"
    assert "swapIn" not in js, "sections.js no longer swaps a group in: a details opens at once"
    assert re.search(r"function groupEl\(key\)", js)
    assert "g.open = true" in js, "opening a group must set details.open"


def test_a_group_with_errors_or_unsaved_input_opens_itself() -> None:
    js = SECTIONS_JS.read_text(encoding="utf-8")
    assert re.search(r"""querySelector\(['"]\[aria-invalid="true"\], \[data-dirty\]['"]\)""", js), (
        'sections.js must open any group that holds [aria-invalid="true"] or [data-dirty]'
    )


def test_field_focus_opens_closed_groups_quietly_through_the_hook() -> None:
    js = SECTIONS_JS.read_text(encoding="utf-8")
    assert re.search(r"window\.hrOpenGroup = function \(key, animate\) \{", js), (
        "sections.js must expose window.hrOpenGroup(key, animate), which opens the group"
    )
    focus = FIELD_FOCUS_JS.read_text(encoding="utf-8")
    assert "window.hrOpenGroup(name, false)" in focus, (
        "employee_field_focus.js must open a closed group quietly (no swap-in on first render)"
    )
