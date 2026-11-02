"""The system-log page (/logs/system/): who may open it, filters in the address, batches, escaping."""

from typing import Any

import pytest
from accounts.audit import Category
from accounts.models import SystemLogEntry, User
from config import batching
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

URL = "/logs/system/"
PASSWORD = "x-long-pass-123"  # noqa: S105
HTMX = {"HX-Request": "true"}
HIDDEN_ENTRY = "Нууц бичлэг 4471"


def _user(name: str, role: str | None, *, first: str = "", last: str = "") -> User:
    user = User.objects.create_user(name, password=PASSWORD, first_name=first, last_name=last)  # noqa: S106
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _row(message: str, **fields: Any) -> SystemLogEntry:
    actor = fields.get("actor")
    fields.setdefault("actor_name", actor.username if actor is not None else "")
    fields.setdefault("category", Category.ACCESS)
    fields.setdefault("action", "login")
    fields.setdefault("changes", [])
    return SystemLogEntry.objects.create(message=message, **fields)


@pytest.fixture
def admin(db: None) -> User:
    return _user("sys_page_admin", "Admin", first="Болд", last="Админ")


@pytest.fixture
def hr(db: None) -> User:
    return _user("sys_page_hr", "HR", first="Оюун", last="Хүний")


@pytest.fixture
def entries(admin: User) -> None:
    _row(HIDDEN_ENTRY, actor=admin, ip="10.0.0.5")
    _row("Ажлын цагийг тохируулсан", category=Category.SETTINGS, action="setting_added", actor=admin, ip="10.0.1.7")
    _row("Тайлан татсан", category=Category.EXPORT, action="export_list", actor_name="wrong.user", ip="192.168.1.1")


def test_hr_gets_403_and_no_entry_text(hr: User, entries: None) -> None:
    response = _client(hr).get(URL)
    assert response.status_code == 403
    assert HIDDEN_ENTRY not in response.content.decode()


def test_hr_gets_403_on_htmx_too(hr: User, entries: None) -> None:
    response = _client(hr).get(URL, headers=HTMX)
    assert response.status_code == 403
    assert HIDDEN_ENTRY not in response.content.decode()


def test_anonymous_is_sent_to_login(entries: None) -> None:
    response = Client().get(URL)
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_access_category_shows_its_label(admin: User) -> None:
    _row("Нэвтэрсэн", category=Category.ACCESS, actor=admin, ip="10.0.0.9")
    body = _client(admin).get(URL).content.decode()
    assert "Нэвтрэлт, эрх" in body


def test_admin_sees_entries_and_column_headings(admin: User, entries: None) -> None:
    response = _client(admin).get(URL)
    body = response.content.decode()
    assert response.status_code == 200
    assert HIDDEN_ENTRY in body
    assert "Ажлын цагийг тохируулсан" in body
    assert "Нэвтрэх нэр (буруу оруулсан байж болно)" in body  # the actor column note


def test_empty_actor_shows_system_and_empty_state_text(admin: User) -> None:
    _row("Систем хийсэн үйлдэл", actor_name="", action="macs_sync", category=Category.IMPORT)
    body = _client(admin).get(URL).content.decode()
    assert '<td class="whitespace-nowrap">Систем</td>' in body  # the actor cell itself, not just the word
    assert "Бүртгэл олдсонгүй" not in body
    empty = _client(admin).get(URL, {"q": "огт-байхгүй-үг"}).content.decode()
    assert "Бүртгэл олдсонгүй" in empty


def test_category_and_action_filters_in_the_address(admin: User, entries: None) -> None:
    client = _client(admin)
    body = client.get(URL, {"category": Category.SETTINGS}).content.decode()
    assert "Ажлын цагийг тохируулсан" in body
    assert HIDDEN_ENTRY not in body
    body = client.get(URL, {"action": "export_list"}).content.decode()
    assert "Тайлан татсан" in body
    assert "Ажлын цагийг тохируулсан" not in body


def test_ip_filter_in_the_address(admin: User, entries: None) -> None:
    body = _client(admin).get(URL, {"ip": "10.0"}).content.decode()
    assert HIDDEN_ENTRY in body and "Ажлын цагийг тохируулсан" in body
    assert "Тайлан татсан" not in body


def test_who_filter_in_the_address(admin: User, entries: None) -> None:
    body = _client(admin).get(URL, {"by": "wrong.user"}).content.decode()
    assert "Тайлан татсан" in body
    assert HIDDEN_ENTRY not in body


def test_htmx_filter_pushes_the_cleaned_address(admin: User, entries: None) -> None:
    response = _client(admin).get(URL, {"category": Category.EXPORT, "q": "  экспорт "}, headers=HTMX)
    assert response.status_code == 200
    assert "<html" not in response.content.decode()
    assert response["HX-Push-Url"] == f"{URL}?q=%D1%8D%D0%BA%D1%81%D0%BF%D0%BE%D1%80%D1%82&category=export"


def test_garbage_address_gives_200(admin: User, entries: None) -> None:
    client = _client(admin)
    address = URL + "?offset=abc&from=zzz&to=9999-99-99&category=%00&ip=%00&offset=%C2%B2&action=drop&by=%00"
    assert client.get(address).status_code == 200
    response = client.get(address, headers=HTMX)
    assert response.status_code == 200
    assert "<html" not in response.content.decode()


def test_htmx_offset_with_thirty_digits_gives_200(admin: User, entries: None) -> None:
    response = _client(admin).get(URL + "?offset=" + "9" * 30, headers=HTMX)
    assert response.status_code == 200
    assert "<html" not in response.content.decode()


def test_htmx_batch_returns_rows_only(monkeypatch: pytest.MonkeyPatch, admin: User) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 3)
    for i in range(8):
        _row(f"Запис {i}")
    client = _client(admin)

    first = client.get(URL, {"q": "Запис"})
    first_body = first.content.decode()
    assert first.status_code == 200
    assert "Запис 7" in first_body and "Запис 5" in first_body
    assert "Запис 4" not in first_body
    assert "offset=3" in first_body  # the next-batch pill

    second = client.get(URL, {"q": "Запис", "offset": "3"}, headers=HTMX)
    second_body = second.content.decode()
    assert second.status_code == 200
    assert "<html" not in second_body
    assert "<table" not in second_body  # a later batch adds rows only
    assert "Запис 4" in second_body and "Запис 2" in second_body
    assert "Запис 7" not in second_body
    assert "Запис 1" not in second_body


def test_search_and_message_are_escaped(admin: User) -> None:
    _row("<script>alert(1)</script>", actor_name="<b>x</b>")
    client = _client(admin)

    typed = client.get(URL, {"q": '"><img src=x onerror=1>'})
    typed_body = typed.content.decode()
    assert typed.status_code == 200
    assert '"><img src=x onerror=1>' not in typed_body
    assert "&quot;&gt;&lt;img src=x onerror=1&gt;" in typed_body  # the box shows the text, escaped

    listed = client.get(URL).content.decode()
    assert "<script>alert(1)</script>" not in listed
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in listed
    assert "<b>x</b>" not in listed


def test_deleted_actor_name_renders_in_the_row(admin: User) -> None:
    gone = _user("gone_view_actor", "HR", first="Өнөр", last="Одоо")
    _row("Устсан хэрэглэгчийн мөр", actor=gone)
    gone.delete()
    body = _client(admin).get(URL, {"q": "Устсан"}).content.decode()
    assert "Устсан хэрэглэгчийн мөр" in body
    assert '<td class="whitespace-nowrap">gone_view_actor</td>' in body


def test_ip_exact_address_does_not_match_a_longer_one(admin: User) -> None:
    _row("Гарал A", ip="10.0.0.5")
    _row("Гарал B", ip="10.0.0.50")
    body = _client(admin).get(URL, {"ip": "10.0.0.5"}).content.decode()
    assert "Гарал A" in body
    assert "Гарал B" not in body


def test_oldest_param_orders_rows_and_selects_option(admin: User) -> None:
    _row("Эхний мөр")
    _row("Сүүлийн мөр")
    client = _client(admin)
    newest = client.get(URL).content.decode()
    assert newest.index("Сүүлийн мөр") < newest.index("Эхний мөр")
    assert '<option value="1" selected>' not in newest
    oldest = client.get(URL, {"oldest": "1"}).content.decode()
    assert oldest.index("Эхний мөр") < oldest.index("Сүүлийн мөр")
    assert '<option value="1" selected>Хуучин нь эхэнд</option>' in oldest
    assert "Сүүлийн мөр" in oldest


def test_oldest_accepts_only_one(admin: User) -> None:
    _row("Эхний мөр")
    _row("Сүүлийн мөр")
    body = _client(admin).get(URL, {"oldest": "yes"}).content.decode()
    assert body.index("Сүүлийн мөр") < body.index("Эхний мөр")  # another value is dropped: newest first
    assert '<option value="1" selected>' not in body


def test_oldest_is_kept_in_the_pushed_address(admin: User) -> None:
    _row("Эхний мөр")
    response = _client(admin).get(URL, {"oldest": "1", "q": "мөр"}, headers=HTMX)
    assert "oldest=1" in response["HX-Push-Url"]


def test_employee_page_links_to_the_system_tab(admin: User, entries: None) -> None:
    body = _client(admin).get(reverse("logs:employee")).content.decode()
    assert f'href="{URL}"' in body
    body = _client(admin).get(URL).content.decode()
    assert 'aria-current="page"' in body and f'href="{URL}"' in body
