"""The employee log page (/logs/): who may open it, filters in the address, batches and the system tab."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from config import batching
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import ActivityEntry, ActivityKind, Employee, HrOrder, OrderState, OrderType
from employees.services import history, macs_writes

pytestmark = pytest.mark.django_db

URL = "/logs/"
PASSWORD = "x-long-pass-123"  # noqa: S105
HTMX = {"HX-Request": "true"}


def _user(name: str, role: str | None, *, first: str = "", last: str = "") -> User:
    user = User.objects.create_user(name, password=PASSWORD, first_name=first, last_name=last)  # noqa: S106
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _entry(employee: Employee, message: str, **fields: Any) -> ActivityEntry:
    fields.setdefault("kind", ActivityKind.CHANGED)
    return ActivityEntry.objects.create(employee=employee, message=message, **fields)


def _hire(actor: User, family: str, given: str, register_no: str) -> Employee:
    job: dict[str, Any] = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {
        "family_name": family,
        "given_name": given,
        "register_no": register_no,
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    return history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=Decimal("2500000"), by=actor)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("log_page_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def own(actor: User) -> Employee:
    employee = _hire(actor, "Батын", "Сараа", "УБ99120001")
    _entry(employee, "Хаяг өөрчлөгдсөн", changes=[{"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"}])
    return employee


@pytest.fixture
def other(actor: User) -> Employee:
    employee = _hire(actor, "Доржийн", "Ганзориг", "УБ99120002")
    _entry(employee, "Ажлын байр шилжсэн")
    return employee


@pytest.fixture
def hr(own: Employee, other: Employee) -> User:
    return _user("log_page_hr", "HR", first="Оюун", last="Хүний")


def test_hr_gets_the_log_with_known_entries(hr: User) -> None:
    response = _client(hr).get(URL)
    assert response.status_code == 200
    body = response.content.decode()
    assert "Хаяг өөрчлөгдсөн" in body
    assert "Ажлын байр шилжсэн" in body


def test_employee_role_gets_403_without_any_entry(own: Employee) -> None:
    staff = _user("log_page_staff", "Employee", first="Сараа", last="Батын")
    response = _client(staff).get(URL)
    assert response.status_code == 403
    assert "Хаяг өөрчлөгдсөн" not in response.content.decode()


def test_anonymous_is_sent_to_login(own: Employee) -> None:
    response = Client().get(URL)
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_employee_filter_shows_chip_and_only_that_person(hr: User, own: Employee, other: Employee) -> None:
    response = _client(hr).get(URL, {"employee": own.pk})
    body = response.content.decode()
    assert response.status_code == 200
    assert "Ажилтан: Батын Сараа" in body
    assert "Хаяг өөрчлөгдсөн" in body
    assert "Ажлын байр шилжсэн" not in body


def test_unknown_employee_is_dropped_silently(hr: User, own: Employee, other: Employee) -> None:
    response = _client(hr).get(URL, {"employee": 999999})
    body = response.content.decode()
    assert response.status_code == 200
    assert "Ажилтан: " not in body
    assert "Ажлын байр шилжсэн" in body


def test_kind_filter_narrows_rows(hr: User, own: Employee, other: Employee) -> None:
    _entry(own, "Шинэ ажилтан нэмсэн", kind=ActivityKind.ADDED)
    client = _client(hr)
    body = client.get(URL, {"kind": [ActivityKind.ADDED]}).content.decode()
    assert "Шинэ ажилтан нэмсэн" in body  # the filter really returns the ADDED row ...
    assert "Хаяг өөрчлөгдсөн" not in body  # ... and drops the CHANGED one (a «Өөрчилсөн» entry)


def test_empty_result_says_so(hr: User, own: Employee) -> None:
    body = _client(hr).get(URL, {"q": "огт-байхгүй-үг"}).content.decode()
    assert "Бүртгэл олдсонгүй" in body


def test_htmx_batch_returns_rows_only(monkeypatch: pytest.MonkeyPatch, hr: User, own: Employee) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 3)
    for i in range(8):
        _entry(own, f"Запис {i}")
    client = _client(hr)

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
    assert "Запис 4" in second_body and "Запис 2" in second_body
    assert "Запис 7" not in second_body
    assert "Запис 1" not in second_body


def test_garbage_address_gives_200(hr: User, own: Employee) -> None:
    client = _client(hr)
    address = URL + "?offset=abc&from=zzz&to=9999-99-99&kind=%00&employee=1e9&by=x"
    assert client.get(address).status_code == 200
    assert client.get(address, headers=HTMX).status_code == 200


def test_system_tab_only_for_view_audit(hr: User, own: Employee) -> None:
    assert "Системийн бүртгэл" not in _client(hr).get(URL).content.decode()
    admin = _user("log_page_admin", "Admin", first="Болд", last="Админ")
    assert "Системийн бүртгэл" in _client(admin).get(URL).content.decode()


def test_htmx_offset_with_superscript_two_gives_200(hr: User, own: Employee) -> None:
    response = _client(hr).get(URL + "?offset=%C2%B2", headers=HTMX)
    assert response.status_code == 200
    assert "<html" not in response.content.decode()


def test_htmx_offset_with_thirty_digits_gives_200(hr: User, own: Employee) -> None:
    response = _client(hr).get(URL + "?offset=" + "9" * 30, headers=HTMX)
    assert response.status_code == 200
    assert "<html" not in response.content.decode()


def test_search_and_message_are_escaped(hr: User, own: Employee) -> None:
    _entry(own, "<script>alert(1)</script>")
    client = _client(hr)

    typed = client.get(URL, {"q": '"><img src=x onerror=1>'})
    typed_body = typed.content.decode()
    assert typed.status_code == 200
    assert '"><img src=x onerror=1>' not in typed_body
    assert "&quot;&gt;&lt;img src=x onerror=1&gt;" in typed_body  # the box shows the text, escaped

    listed = client.get(URL).content.decode()
    assert "<script>alert(1)</script>" not in listed
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in listed


def test_only_an_entry_with_an_order_opens_the_order_pop_up(hr: User, own: Employee, other: Employee) -> None:
    order = HrOrder.objects.create(employee=own, is_hire=True, order_type=OrderType.HIRED, state=OrderState.PENDING)
    _entry(own, "Тушаалтай бичлэг", order=order)
    body = _client(hr).get(URL).content.decode()
    url = reverse("employees:order_detail", args=[own.pk, order.pk])
    assert f'hx-get="{url}"' in body  # the row with the order opens its pop-up
    assert body.count("/order/") == 1  # the entry without an order carries no such link


def test_oldest_param_orders_rows_and_selects_option(hr: User, own: Employee) -> None:
    _entry(own, "Эхний бичлэг")
    _entry(own, "Сүүлийн бичлэг")
    client = _client(hr)
    newest = client.get(URL).content.decode()
    assert newest.index("Сүүлийн бичлэг") < newest.index("Эхний бичлэг")
    assert '<option value="1" selected>' not in newest
    oldest = client.get(URL, {"oldest": "1"}).content.decode()
    assert oldest.index("Эхний бичлэг") < oldest.index("Сүүлийн бичлэг")
    assert '<option value="1" selected>Хуучин нь эхэнд</option>' in oldest
    dropped = client.get(URL, {"oldest": "yes"}).content.decode()
    assert dropped.index("Сүүлийн бичлэг") < dropped.index("Эхний бичлэг")
    assert '<option value="1" selected>' not in dropped
