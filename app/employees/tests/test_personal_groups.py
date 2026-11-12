"""Personal tab topic groups are collapsible <details> groups in one scroll (UI_RULES §8, plan 2026-11-09 task 4).

Each of the five groups is a <details data-pgroup="<key">; its <summary> shows the group title and one count chip per
section that has rows. The section menu in the page rail is gone.
"""

import re
from pathlib import Path
from typing import Any

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from employees.models import Employee

from .test_personal_views import add_url, lists, values_for  # noqa: F401  (lists: the fixture)
from .test_views import login_as

__all__ = ["lists"]  # the fixture, imported for the family test below

pytestmark = pytest.mark.django_db

GROUP_KEYS = ["basic", "edu", "award", "health", "other"]
GROUP_TITLES = {
    "basic": "Үндсэн мэдээлэл",
    "edu": "Боловсрол, туршлага",
    "award": "Шагнал, сахилга",
    "health": "Эрүүл мэнд, цэрэг",
    "other": "Бусад",
}


def _page(client: Client, employee: Employee) -> str:
    login_as(client, "HR")
    return client.get(reverse("employees:detail", args=[employee.pk])).content.decode()


def _details_tags(body: str) -> list[str]:
    return re.findall(r"<details [^>]*data-pgroup=\"\w+\"[^>]*>", body)


def _tag_for(body: str, key: str) -> str:
    [tag] = [t for t in _details_tags(body) if f'data-pgroup="{key}"' in t]
    return tag


def _is_open(tag: str) -> bool:
    return re.search(r"\sopen(\s|>)", tag) is not None


def test_personal_tab_has_five_collapsible_groups(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    assert re.findall(r'<details [^>]*data-pgroup="(\w+)"', body) == GROUP_KEYS
    assert _is_open(_tag_for(body, "basic"))
    assert all(not _is_open(_tag_for(body, key)) for key in GROUP_KEYS[1:])
    assert all(f'id="personal-{key}"' in _tag_for(body, key) for key in GROUP_KEYS)


def test_no_personal_nav_and_no_data_off_on_the_page(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    assert 'id="personal-nav"' not in body
    assert "data-off" not in body


def test_group_summary_lists_chip_for_a_section_with_rows(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "family"), values_for("family", lists)).status_code == 204
    body = client.get(reverse("employees:detail", args=[hired.pk])).content.decode()
    start = body.index('data-pgroup="basic"')
    summary = body[start : body.index("</summary>", start)]
    assert ">Гэр бүл <span" in summary
    assert 'id="menu-count-family">1</span>' in summary


def test_group_summary_has_no_chip_for_a_section_without_rows(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    assert 'id="menu-count-gift" class="invisible"' in body  # zero rows: the chip is in the page, its number hidden
    assert 'id="menu-count-language" class="invisible"' in body
    award = body[body.index('data-pgroup="award"') : body.index("</summary>", body.index('data-pgroup="award"'))]
    assert 'Олгосон бэлэг <span id="menu-count-gift" class="invisible">0</span>' in award  # CSS hides the whole chip


def test_zero_count_chip_is_hidden_by_class_and_a_count_has_no_class(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    """A zero count keeps its chip in the page with the number span class="invisible" (CSS hides the chip);
    a non-zero count has its number span with no class at all."""
    login_as(client, "HR")
    assert client.post(add_url(hired, "family"), values_for("family", lists)).status_code == 204
    body = client.get(reverse("employees:detail", args=[hired.pk])).content.decode()
    assert 'Олгосон бэлэг <span id="menu-count-gift" class="invisible">0</span>' in body
    assert 'Гэр бүл <span id="menu-count-family">1</span>' in body


def test_summary_is_a_real_summary_inside_its_details(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    for key in GROUP_KEYS:
        start = body.index(_tag_for(body, key))
        head = body[start : body.index("</summary>", start)]
        assert "<summary" in head, key
        assert GROUP_TITLES[key] in head, key
        assert head.count("<summary") == 1, key


def test_rail_keeps_personal_link_but_no_sub_menu(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    rail = body[body.index('id="emp-rail"') : body.index("</aside>", body.index('id="emp-rail"'))]
    assert 'href="#personal"' in rail
    assert "Хувийн</a>" in rail
    assert "personal-nav" not in rail
    assert "data-pgroup-link" not in rail
    assert "menu-group" not in rail


def test_summary_partial_shows_a_number_for_the_chip() -> None:
    html = render_to_string(
        "employees/_personal_group_summary.html",
        {"title": "Боловсрол, туршлага", "group": "edu", "section_counts": {"education": 2, "language": 0}},
    )
    assert "Боловсрол, туршлага" in html
    assert ">Боловсрол <span" in html and 'id="menu-count-education">2</span>' in html
    # zero rows: the chip is there, hidden by CSS
    assert 'Гадаад хэл <span id="menu-count-language" class="invisible">0</span>' in html


def test_summary_partial_other_chip_only_with_filled_fields() -> None:
    empty = render_to_string(
        "employees/_personal_group_summary.html",
        {"title": "Бусад", "group": "other", "section_counts": {"other": "0/10"}},
    )
    filled = render_to_string(
        "employees/_personal_group_summary.html",
        {"title": "Бусад", "group": "other", "section_counts": {"other": "3/10"}},
    )
    assert 'Бусад мэдээлэл <span id="menu-count-other" class="invisible">0/10</span>' in empty  # not filled: hidden
    assert 'id="menu-count-other">3/10</span>' in filled


def test_groups_clear_the_sticky_anchor_bar_below_lg(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    for key in GROUP_KEYS:
        assert "scroll-mt-28 lg:scroll-mt-20" in _tag_for(body, key), key


def test_other_chip_refresh_hides_zero_of_n_fields() -> None:
    """The out-of-band refresh (_page_refresh.html) hides the «Бусад мэдээлэл» chip for a «0/5» count, like the chip."""
    empty = render_to_string("employees/_page_refresh.html", {"menu_sec": "other", "menu_count": "0/5"})
    filled = render_to_string("employees/_page_refresh.html", {"menu_sec": "other", "menu_count": "3/5"})
    assert 'id="menu-count-other" hx-swap-oob="true" class="invisible">0/5</span>' in empty
    assert 'class="invisible"' not in filled and ">3/5</span>" in filled


def test_group_open_state_is_recorded_only_from_a_reader_click() -> None:
    """A parser-made <details open> after a redraw fires toggle too; it must not overwrite the reader's state."""
    js = (Path(__file__).resolve().parents[2] / "static/js/sections.js").read_text(encoding="utf-8")
    assert "addEventListener('toggle'" not in js
    assert "details[data-pgroup] > summary" in js
    assert "openState[g.getAttribute('data-pgroup')] = g.open" in js


def test_summary_partial_has_no_number_inside_the_title() -> None:
    html = render_to_string(
        "employees/_personal_group_summary.html", {"title": "Бусад", "group": "other", "section_counts": {}}
    )
    assert "<button" not in html
    assert not re.search(r"\d+\.\s*<", html)
