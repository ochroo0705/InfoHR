"""The employee page's three tabs are stacked sections in one scroll (plan 2026-11-09-employee-page-one-scroll, task 3).

Work, salary and personal are all visible, in that order, on one page; the rail and the narrow-screen bar are anchor
links that scroll to them. Permission rules stay: no salary section or link without can_view_salary, no personal
section or link without can_view_personal. The script behaviour is checked by its hooks in the page (there is no DOM
in the test run).
"""

import re
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from employees.models import Employee
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

SECTION_TITLES = {"work": "Ажил", "salary": "Цалин, даатгал", "personal": "Хувийн"}


def _page(client: Client, employee: Employee, role: str) -> str:
    login_as(client, role)
    return client.get(reverse("employees:detail", args=[employee.pk])).content.decode()


def _open_tag(body: str, name: str) -> str:
    match = re.search(rf'<section id="tab-{name}"[^>]*>', body)
    assert match is not None, f"section tab-{name} is missing"
    return match.group(0)


def test_all_permitted_sections_are_visible_without_hidden(client: Client, hired: Employee) -> None:
    body = _page(client, hired, "Admin")
    for name in ("work", "salary", "personal"):
        assert "hidden" not in _open_tag(body, name), f"tab-{name} must not start hidden"


def test_sections_come_in_document_order_work_salary_personal(client: Client, hired: Employee) -> None:
    body = _page(client, hired, "Admin")
    assert body.index('id="tab-work"') < body.index('id="tab-salary"') < body.index('id="tab-personal"')


def test_role_without_salary_rights_has_no_salary_section_or_link(client: Client, hired: Employee) -> None:
    body = _page(client, hired, "HR")
    assert 'id="tab-salary"' not in body
    assert 'href="#salary"' not in body
    assert 'id="tab-work"' in body and 'id="tab-personal"' in body


def test_rail_links_keep_the_order_work_salary_personal(client: Client, hired: Employee) -> None:
    body = _page(client, hired, "Admin")
    rail = body[body.index('id="emp-rail"') : body.index("</aside>", body.index('id="emp-rail"'))]
    assert rail.index('href="#work"') < rail.index('href="#salary"') < rail.index('href="#personal"')
    assert rail.count('class="rtab') == 3


def test_each_section_starts_with_its_heading(client: Client, hired: Employee) -> None:
    body = _page(client, hired, "Admin")
    for name, label in SECTION_TITLES.items():
        pattern = (
            rf'<section id="tab-{name}"[^>]*>\s*'
            rf'<h2 class="mb-4 text-lg font-semibold text-slate-900">{re.escape(label)}</h2>'
        )
        assert re.search(pattern, body), f"tab-{name} must start with its h2 «{label}»"


def test_sections_scroll_below_the_top_bar_and_later_ones_have_a_top_line(client: Client, hired: Employee) -> None:
    body = _page(client, hired, "Admin")
    for name in ("work", "salary", "personal"):
        # below lg the sticky anchor bar (top-14 plus its height) covers more than 80 px; at lg the header scrolls away
        assert "scroll-mt-28 lg:scroll-mt-20" in _open_tag(body, name)
    assert "border-t border-slate-200" not in _open_tag(body, "work")
    assert "border-t border-slate-200" in _open_tag(body, "salary")
    assert "border-t border-slate-200" in _open_tag(body, "personal")


def test_narrow_bar_is_a_sticky_anchor_bar(client: Client, hired: Employee) -> None:
    body = _page(client, hired, "Admin")
    nav_tag = re.search(r'<nav [^>]*aria-label="Ажилтны хэсгүүд"[^>]*>', body)
    assert nav_tag is not None
    assert "sticky top-14 z-20 bg-surface" in nav_tag.group(0)
    assert "lg:hidden" in nav_tag.group(0)


def test_script_scrolls_sections_and_saves_the_section_in_view(client: Client, hired: Employee) -> None:
    body = _page(client, hired, "Admin")
    assert "function showTab(name,quiet)" in body
    assert "function setActive(name)" in body
    assert "swapIn(" not in body, "the panels no longer swap in: they are all visible"
    assert "document.getElementById('emp-tab').value=currentSection;" in body
    assert "getElementById('emp-tab').value=location.hash" not in body
    assert "history.replaceState(null,'',a.hash)" in body
    assert "currentSection='work'" in body and "window.addEventListener('scroll'" in body
    assert "requestAnimationFrame" in body and "{passive:true}" in body
    assert "getBoundingClientRect().top<=120" in body


def test_redraw_ignores_the_hash_and_scrolls_to_the_first_error(client: Client, hired: Employee) -> None:
    """The inline script runs again on every htmx redraw of <main>: only the first load reads the address (fix 1)."""
    body = _page(client, hired, "Admin")
    assert "window.__empLoaded" in body and "var redraw=!!window.__empLoaded" in body
    assert "if(redraw){" in body
    assert "document.querySelector('[aria-invalid=\"true\"]')" in body
    assert "bad.scrollIntoView({behavior:'instant',block:'center'})" in body


def test_scroll_and_click_handlers_are_replaced_on_redraw_not_stacked(client: Client, hired: Employee) -> None:
    """A redraw must remove the previous scroll and click listeners before adding its own (fix 3)."""
    body = _page(client, hired, "Admin")
    assert "removeEventListener('scroll',window.__empScroll)" in body
    assert "removeEventListener('click',window.__empClick)" in body
    assert "window.__empClick=function" in body and "window.__empScroll=function" in body
    assert "window.addEventListener('scroll',window.__empScroll" in body
    assert "document.addEventListener('click',window.__empClick)" in body


def test_header_work_link_relies_on_the_document_click_handler() -> None:
    """The header's next-event link is drawn only when an event is pending, so the template source is checked."""
    templates = Path(__file__).resolve().parents[1] / "templates" / "employees"
    header = (templates / "_header.html").read_text(encoding="utf-8")
    assert "showTab('work')" not in header
    assert 'href="#work"' in header


def test_click_on_a_section_link_locks_the_spy_for_600_ms(client: Client, hired: Employee) -> None:
    """A clicked section link stays marked while the smooth scroll runs (fix 4)."""
    body = _page(client, hired, "Admin")
    assert "spyLockUntil=Date.now()+600" in body
    assert "if(Date.now()<spyLockUntil)return;" in body
