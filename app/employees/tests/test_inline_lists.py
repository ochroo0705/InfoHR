"""Inline list rows on the personal tab (UI_RULES §2f pilot): Гадаад хэл and Яаралтай үед холбогдох."""

import html
import re
from typing import Any, cast

import pytest
from django.test import Client
from django.urls import reverse
from macs.models import ContactRow, DriverType

from employees import sections
from employees.models import ActivityEntry, Employee
from employees.services import personal_rows
from employees.services import personal_writes as pw

from .test_personal_views import (
    CHANGES,
    add_url,
    delete_post,
    delete_url,
    edit_post,
    edit_url,
    lists,
    only_key,
    shown_value,
    values_for,
)
from .test_views import login_as

__all__ = ["lists"]  # the fixture, imported for these tests


def _items(context: dict[str, object]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], context["items"])


def inline(url: str) -> str:
    return f"{url}?inline=1"


def list_url(employee: Employee, kind: str) -> str:
    return reverse("employees:personal_list", args=[employee.pk, kind])


def test_add_opens_an_empty_row_in_the_list(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    body = client.get(inline(add_url(hired, "language"))).content.decode()
    assert 'id="list-language"' in body and "data-inline-row" in body and 'id="inline-language-form"' in body
    assert 'form="inline-language-form"' in body and "f-soft" in body
    assert "fixed inset-0" not in body  # no pop-up
    assert "data-dirty" not in body  # a fresh row holds nothing unsaved yet
    assert "+ нэмэх</button>" not in body  # one open row at a time


def test_add_saves_and_redraws_the_list_with_the_log(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    response = client.post(inline(add_url(hired, "language")), values_for("language", lists))
    body = response.content.decode()
    assert response.status_code == 200
    assert len(personal_rows.rows("language", hired)) == 1
    assert 'id="list-language"' in body and "Англи" in body and "data-inline-row" not in body
    assert (
        'id="activity-list" hx-swap-oob="innerHTML"' in body
        and 'id="activity" hx-swap-oob' not in body
        and 'id="activity-count" hx-swap-oob="true"' in body
    )
    assert 'id="menu-count-language" hx-swap-oob="true" class="text-xs text-slate-400">1<' in body


def test_invalid_row_stays_open_with_its_error(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    data = {k: v for k, v in values_for("contact", lists).items() if k != "name"}
    body = client.post(inline(add_url(hired, "contact")), data).content.decode()
    assert "data-inline-row" in body and "text-red-600" in body
    assert 'id="inline-contact-form" data-dirty' in body  # typed values still unsaved: leaving the page asks
    assert personal_rows.rows("contact", hired) == []
    assert "hx-swap-oob" not in body  # nothing written, nothing else to refresh


def test_edit_opens_the_row_in_place_and_saves(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "contact"), values_for("contact", lists))
    key = only_key(hired, "contact")
    body = client.get(inline(edit_url(hired, "contact", key))).content.decode()
    assert "data-inline-row" in body and 'value="Болд"' in body and "Устгах уу?" in body
    post = edit_post(client, hired, "contact", key)
    body = client.post(inline(edit_url(hired, "contact", key)), {**post, "name": "Дорж"}).content.decode()
    assert "Дорж" in body and "data-inline-row" not in body
    assert ContactRow.objects.get(pk=key).name == "Дорж"
    assert "menu-count-contact" not in body  # the menu shows the address count for that section, not contacts


def test_stale_edit_keeps_the_row_open(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "contact"), values_for("contact", lists))
    key = only_key(hired, "contact")
    post = edit_post(client, hired, "contact", key)
    ContactRow.objects.filter(pk=key).update(relative="Эгч")  # changed elsewhere meanwhile
    body = client.post(inline(edit_url(hired, "contact", key)), {**post, "name": "Дорж"}).content.decode()
    assert pw.STALE in body and "data-inline-row" in body
    assert ContactRow.objects.get(pk=key).name == "Болд"


def test_delete_in_the_row(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "language"), values_for("language", lists))
    key = only_key(hired, "language")
    loaded = delete_post(client, hired, "language", key)
    body = client.post(inline(delete_url(hired, "language", key)), loaded).content.decode()
    assert personal_rows.rows("language", hired) == []
    assert "бүртгэгдээгүй" in body and 'class="text-xs text-slate-300">0<' in body
    assert ActivityEntry.objects.filter(employee=hired, personal=True).count() == 2


def test_close_shows_the_list_without_an_open_row(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    body = client.get(list_url(hired, "language")).content.decode()
    assert 'id="list-language"' in body and "data-inline-row" not in body and "+ нэмэх</button>" in body
    assert client.get(list_url(hired, "address")).status_code == 404  # address keeps its pop-up


def test_other_lists_keep_the_pop_up(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    body = client.get(inline(add_url(hired, "address"))).content.decode()
    assert "fixed inset-0" in body and "data-inline-row" not in body
    assert client.post(add_url(hired, "language"), values_for("language", lists)).status_code == 204


def test_inline_list_needs_the_edit_right(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    assert client.get(list_url(hired, "language")).status_code == 403


def test_cells_format_dates_money_and_labels(
    client: Client, hired: Employee, lists: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inline cells look like today's tables: ISO dates, mnt money, choice labels (not codes)."""
    login_as(client, "HR")
    client.post(add_url(hired, "material_help"), values_for("material_help", lists))
    client.post(add_url(hired, "complaint"), values_for("complaint", lists))
    monkeypatch.setitem(
        sections.INLINE_LISTS,
        "material_help",
        sections.InlineList(
            "Буцалтгүй тусламж",
            (
                sections.InlineColumn("Огноо", "help_date", fmt="date"),
                sections.InlineColumn("Мөнгөний дүн", "amount", fmt="money"),
            ),
            menu_count=True,
        ),
    )
    monkeypatch.setitem(
        sections.INLINE_LISTS,
        "complaint",
        sections.InlineList("Гомдол", (sections.InlineColumn("Төрөл", "ctype", value="ctype_label"),), True),
    )
    help_rows = personal_rows.rows("material_help", hired)
    cells = _items(sections.inline_context(hired, "material_help", help_rows, True))[0]["cells"]
    assert cells == ["2026-01-15", "1,250,000₮"]
    complaint = personal_rows.rows("complaint", hired)
    label = _items(sections.inline_context(hired, "complaint", complaint, True))[0]["cells"][0]
    assert label == complaint[0].values["ctype_label"] and label != "1"


# Lists edited in their own rows (UI_RULES §2f) with the headers their tables had before.
HEADERS = {
    "family": ["Хамаарал", "Овог", "Нэр", "Төрсөн огноо", "Ажил, албан тушаал", "Утас"],
    "talent": ["Авьяас", "Сургасан он", "Тайлбар"],
    "award": ["Шагналын нэр", "Хаанаас", "Огноо", "Тайлбар"],
    "complaint": ["Огноо", "Төрөл", "Гомдол", "Тайлбар"],
    "driver": ["Жолооны ангилал", "Үнэмлэхний дугаар", "Үнэмлэх авсан огноо"],
    "army_rank": ["Цэргийн цол", "Цол олгосон огноо", "Нэмэгдлийн хэмжээ"],
    "skill": ["Огноо", "Даалгавар", "Нормын тоо", "Хэлтэс", "Тайлбар"],
    "material_help": ["Огноо", "Үндэслэл", "Мөнгөний дүн", "Тайлбар"],
    "discipline": ["Огноо", "Шийтгэлийн нэр", "Хаанаас", "Шийтгэлийн хувь", "Дуусах огноо", "Тайлбар"],
    "military": ["Цэргийн цол", "Бэлтгэл зэрэг", "Алба хаасан жил", "Халагдсан огноо", "Халагдсан шалтгаан"],
}


@pytest.mark.parametrize("kind", list(HEADERS))
def test_inline_add_edit_delete(client: Client, hired: Employee, lists: dict[str, Any], kind: str) -> None:
    login_as(client, "HR")
    body = client.post(inline(add_url(hired, kind)), values_for(kind, lists)).content.decode()
    assert f'id="list-{kind}"' in body and f'id="menu-count-{kind}" hx-swap-oob="true"' in body
    key = only_key(hired, kind)
    assert "data-inline-row" in client.get(inline(edit_url(hired, kind, key))).content.decode()
    post = edit_post(client, hired, kind, key)
    assert client.post(inline(edit_url(hired, kind, key)), {**post, **CHANGES[kind]}).status_code == 200
    changed = personal_rows.rows(kind, hired)[0]
    for name, expected in CHANGES[kind].items():
        assert str(shown_value(changed, name)) == expected, name
    client.post(inline(delete_url(hired, kind, key)), delete_post(client, hired, kind, key))
    assert personal_rows.rows(kind, hired) == []


@pytest.mark.parametrize("kind", list(HEADERS))
def test_inline_list_shows_today_headers(client: Client, hired: Employee, lists: dict[str, Any], kind: str) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, kind), values_for(kind, lists))
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    block = page[page.index(f'id="list-{kind}"') :]
    for header in HEADERS[kind]:
        assert f">{header}</th>" in block[: block.index("</table>")], header


def test_empty_code_list_notice_in_row(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    """No driver types yet: the open row says where to add them, and a save is a field error, never a 500."""
    login_as(client, "HR")
    DriverType.objects.all().delete()
    body = client.get(inline(add_url(hired, "driver"))).content.decode()
    assert "жагсаалт хоосон байна" in body and "data-inline-row" in body
    response = client.post(inline(add_url(hired, "driver")), values_for("driver", lists))
    assert response.status_code == 200 and "text-red-600" in response.content.decode()
    assert personal_rows.rows("driver", hired) == []


def test_stale_edit_of_a_vanished_row_closes_the_list(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    """The old program (or another user) deleted the row meanwhile: the list comes back closed and usable, with
    the message, instead of a hidden open row nobody can close."""
    login_as(client, "HR")
    client.post(add_url(hired, "contact"), values_for("contact", lists))
    key = only_key(hired, "contact")
    post = edit_post(client, hired, "contact", key)
    ContactRow.objects.filter(pk=key).delete()
    body = client.post(inline(edit_url(hired, "contact", key)), {**post, "name": "Дорж"}).content.decode()
    assert pw.STALE in body
    assert "data-inline-row" not in body and "data-dirty" not in body and "+ нэмэх</button>" in body


def test_real_columns_keep_today_cell_formats(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    """The configured lists (not a test copy) show ISO dates, mnt money and choice labels."""
    login_as(client, "HR")
    help_body = client.post(inline(add_url(hired, "material_help")), values_for("material_help", lists)).content
    assert ">2026-01-15<" in help_body.decode() and ">1,250,000₮<" in help_body.decode()
    complaint_body = client.post(inline(add_url(hired, "complaint")), values_for("complaint", lists)).content.decode()
    label = personal_rows.rows("complaint", hired)[0].values["complaint_label"]
    assert f">{label}<" in complaint_body and ">2026-02-01<" in complaint_body


# A write answers with its list (or field block) and the log refresh only, not the whole page (~160 queries).
WRITE_QUERIES = 45


def test_inline_save_does_not_rebuild_the_page(
    client: Client, hired: Employee, lists: dict[str, Any], django_assert_max_num_queries: Any
) -> None:
    login_as(client, "HR")
    with django_assert_max_num_queries(WRITE_QUERIES):
        body = client.post(inline(add_url(hired, "language")), values_for("language", lists)).content.decode()
    assert 'id="activity-list" hx-swap-oob="innerHTML"' in body and "Англи" in body


def test_section_save_does_not_rebuild_the_page(
    client: Client, hired: Employee, django_assert_max_num_queries: Any
) -> None:
    login_as(client, "HR")
    section = reverse("employees:personal_section", args=[hired.pk, "contact"])
    loaded = re.search(r'name="loaded" value="([^"]*)"', client.get(section).content.decode())
    assert loaded is not None
    with django_assert_max_num_queries(WRITE_QUERIES):
        body = client.post(section, {"private_phone": "99001122", "loaded": html.unescape(loaded.group(1))})
    assert 'id="activity-list" hx-swap-oob="innerHTML"' in body.content.decode()


def test_inline_rows_have_their_own_element_ids(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    """Rows open in two lists never share an element id (both have e.g. a «description» box)."""
    login_as(client, "HR")
    language = client.get(inline(add_url(hired, "language"))).content.decode()
    talent = client.get(inline(add_url(hired, "talent"))).content.decode()
    assert 'id="inline-language-description"' in language and 'id="inline-talent-description"' in talent
    assert 'id="id_description"' not in language + talent
    assert 'id="id_language"' in client.get(add_url(hired, "language")).content.decode()  # the pop-up is unchanged
