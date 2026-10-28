"""Employee page headings (UI_RULES §8): one title style, violet topic-group dividers, no анкет numbers, empty
lists noted on their title line, no lines between sections."""

import re
from typing import Any

from django.test import Client

from employees.models import Employee

from .test_personal_views import add_url, lists, render_section, values_for
from .test_views import login_as

__all__ = ["lists"]  # the fixture, imported for these tests

GROUPS = ["Үндсэн мэдээлэл", "Боловсрол, туршлага", "Шагнал, сахилга", "Эрүүл мэнд, цэрэг", "Бусад"]
# The first section of each group, in page order.
FIRST = ["identity", "education", "award", "body", "other"]
OLD_TITLE = "text-sm font-semibold text-slate-800"


def _page(client: Client, employee: Employee) -> str:
    login_as(client, "HR")
    return client.get(f"/employees/{employee.pk}/").content.decode()


def _personal(page: str) -> str:
    return page[page.index('id="sec-identity"') : page.index("</section>", page.index('id="sec-other"'))]


def test_group_dividers_start_each_topic_group(client: Client, hired: Employee) -> None:
    page = _page(client, hired)
    found = re.findall(r'class="grp-divider"[^>]*>([^<]+)<', page)
    assert found == GROUPS
    for title, first in zip(GROUPS, FIRST, strict=True):
        divider = page.index(f">{title}<", page.index('class="grp-divider"'))
        assert divider < page.index(f'id="sec-{first}"'), title


def test_no_anketa_numbers_on_page_or_menu(client: Client, hired: Employee) -> None:
    page = _page(client, hired)
    menu = page[page.index('id="personal-nav"') : page.index("</nav>", page.index('id="personal-nav"'))]
    assert not re.search(r">\s*\d+\.\s*</span>", _personal(page) + menu)


def test_titles_share_one_style_without_section_lines(client: Client, hired: Employee) -> None:
    page = _page(client, hired)
    personal = _personal(page)
    assert 'class="sec-title' in personal and OLD_TITLE not in personal
    assert "border-b border-slate-100 py-5" not in personal  # no line between sections
    work = page[page.index("Албан тушаал, байршил") - 200 : page.index("Хуучин системээс (MACS)") + 50]
    assert 'class="sec-title' in work and OLD_TITLE not in work


def test_empty_list_is_noted_on_its_title_line(client: Client, hired: Employee) -> None:
    page = _page(client, hired)
    talent = page[page.index('id="sec-talent"') : page.index("</section>", page.index('id="sec-talent"'))]
    assert re.search(r'class="sec-title[^"]*"[^>]*>Авьяас\s*<span[^>]*>бүртгэгдээгүй</span>', talent)
    assert "<p" not in talent  # no separate «бүртгэгдээгүй» line
    gift = page[page.index('id="sec-gift"') : page.index("</section>", page.index('id="sec-gift"'))]
    assert re.search(r">Олгосон бэлэг\s*<span[^>]*>бүртгэгдээгүй</span>", gift)  # pop-up lists too


def _cells(html_part: str, tag: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", html_part, re.S)]


def test_education_cells_sit_under_their_headers(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    """«Боловсрол» shows the education level and «Мэргэшил» the qualification (they were swapped)."""
    login_as(client, "HR")
    client.post(add_url(hired, "education"), values_for("education", lists))
    body = client.get(f"/employees/{hired.pk}/section/education/").content.decode()
    table = body[body.index("<table") :]
    headers, cells = _cells(table, "th"), _cells(table[table.index("<tbody") :], "td")
    assert cells[headers.index("Боловсрол")] == lists["edu_level"].name
    assert cells[headers.index("Мэргэшил")] == "—"


def test_personal_tables_are_framed_with_a_plain_header(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    for kind in ("education", "family", "address"):
        client.post(add_url(hired, kind), values_for(kind, lists))
    personal = _personal(client.get(f"/employees/{hired.pk}/").content.decode())
    assert personal.count("<table") == 3 and personal.count('<div class="ptable"><table>') == 3
    assert "uppercase" not in personal


def test_work_experience_has_one_period_column(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "before_work"), values_for("before_work", lists))
    client.post(add_url(hired, "before_work"), {**values_for("before_work", lists), "start_text": "", "end_text": ""})
    body = render_section("before_work", hired)
    assert _cells(body, "th") == ["Газар", "Мэргэжил", "Хугацаа", "Гарсан шалтгаан"]
    assert "2019 оны 3-р сар – 2021 оны 6-р сар" in body  # the old program's free text, as typed
    assert ">2019 – 2021<" in body  # years when the text is empty


def _salary_tab(client: Client, employee: Employee) -> str:
    login_as(client, "Admin", name="admin-viewer")  # sees and edits salary, bank and insurance
    page = client.get(f"/employees/{employee.pk}/").content.decode()
    start = page.index('id="tab-salary"')
    return page[start : page.index("</section>", start)]


def test_salary_tab_follows_the_page_style(client: Client, hired: Employee) -> None:
    """The salary tab uses the same titles, framed table and soft boxes as the other tabs (UI_RULES §2e, §4, §8)."""
    tab = _salary_tab(client, hired)
    assert tab.count('class="sec-title') >= 2  # salary history and «Банк, даатгал»
    assert '<div class="ptable"><table>' in tab
    assert re.search(r'<select[^>]*name="si-bank"[^>]*class="[^"]*f-soft', tab) or re.search(
        r'<select[^>]*class="[^"]*f-soft[^"]*"[^>]*name="si-bank"', tab
    )
    assert re.search(r'name="si-account_no"[^>]*class="[^"]*f-soft|class="[^"]*f-soft[^>]*name="si-account_no"', tab)
