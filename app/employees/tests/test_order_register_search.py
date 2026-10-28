"""Register search (order number, employee name or code) and the order detail pop-up."""

from datetime import date

import pytest
from django.test import Client
from macs.models import Command, Employee

from employees.models import HrOrder, OrderState, OrderType

from .conftest import link_login
from .test_order_register import make_order
from .test_views import login_as

pytestmark = pytest.mark.django_db

REGISTER = "/employees/orders/"


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


def numbers(client: Client, **query: str) -> list[str]:
    body = client.get(REGISTER, query).content.decode()
    return [n for n in ("181", "182", "А/7", "L-9") if f"№ {n}" in body]


@pytest.fixture
def three(hired: Employee) -> Employee:
    HrOrder.objects.filter(employee=hired).delete()
    make_order(hired, "181", date(2026, 3, 1))
    make_order(hired, "182", date(2026, 3, 2))
    make_order(hired, "А/7", date(2026, 3, 3))
    Command.objects.create(employee_id=hired.pk, number="L-9", date=date(2026, 3, 4), summary="Хуучин")
    return hired


def test_search_by_order_number(hr: Client, three: Employee) -> None:
    assert numbers(hr, q="181") == ["181"]
    assert numbers(hr, q="а/7") == ["А/7"]  # case does not matter
    assert numbers(hr, q="l-9") == ["L-9"]  # old-program rows are searched too
    assert numbers(hr, q="18") == ["181", "182"]


def test_search_by_employee_name_words_and_code(hr: Client, three: Employee) -> None:
    name = three.full_name.split()
    assert numbers(hr, q=name[-1]) == ["181", "182", "А/7", "L-9"]
    assert numbers(hr, q=" ".join(reversed(name))) == ["181", "182", "А/7", "L-9"]  # every word, any order
    assert numbers(hr, q=three.code or "") == ["181", "182", "А/7", "L-9"]
    assert numbers(hr, q=f"{name[0]} 182") == ["182"]  # a name word and a number together
    assert numbers(hr, q="zzzz") == []


def test_search_works_with_the_other_filters_and_the_print_view(hr: Client, three: Employee) -> None:
    assert numbers(hr, q="18", year="2026", state="registered") == ["181", "182"]
    assert numbers(hr, q="18", year="2025") == []
    body = hr.get("/employees/orders/print/", {"q": "181"}).content.decode()
    assert "181" in body and "182" not in body


def test_register_shows_the_search_box_and_a_native_year_filter(hr: Client, three: Employee) -> None:
    body = hr.get(REGISTER).content.decode()
    assert 'name="q"' in body and "Дугаар, ажилтны нэр, кодоор хайх" in body
    assert 'name="year" data-search="off"' in body  # Бүх он must stay readable


def test_register_rows_open_the_detail_pop_up_except_old_program_rows(hr: Client, three: Employee) -> None:
    body = hr.get(REGISTER).content.decode()
    order = HrOrder.objects.get(number="181")
    assert f"/employees/{three.pk}/order/{order.pk}/detail/" in body
    assert body.count("/detail/") == 3 and body.count("location.href") == 1  # the old-program row


def test_detail_pop_up_shows_the_facts_and_the_actions(hr: Client, three: Employee) -> None:
    order = HrOrder.objects.get(number="181")
    body = hr.get(f"/employees/{three.pk}/order/{order.pk}/detail/").content.decode()
    assert "Тушаал № 181" in body and three.full_name in body and "Тушаал 181" in body  # summary
    assert f"/employees/{three.pk}/order/{order.pk}/document/" in body and "Засах" in body and "Файл хавсаргах" in body
    assert f"/employees/{three.pk}/" in body  # link to the employee page


def test_detail_pop_up_of_a_signed_or_cancelled_order_has_no_edit(hr: Client, three: Employee) -> None:
    order = HrOrder.objects.get(number="181")
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.SIGNED)
    body = hr.get(f"/employees/{three.pk}/order/{order.pk}/detail/").content.decode()
    assert "Засах" not in body and "Файл хавсаргах" not in body and "Word татах" in body
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    body = hr.get(f"/employees/{three.pk}/order/{order.pk}/detail/").content.decode()
    assert "Word татах" not in body


def test_detail_pop_up_links_cancelled_and_cancelling_orders(hr: Client, three: Employee) -> None:
    gone = HrOrder.objects.get(number="181")
    other = HrOrder.objects.get(number="182")
    HrOrder.objects.filter(pk=other.pk).update(number_key="182")  # the service sets it; the test helper does not
    HrOrder.objects.filter(pk=gone.pk).update(state=OrderState.CANCELLED, cancel_order_no="182", cancel_reason="Алдаа")
    body = hr.get(f"/employees/{three.pk}/order/{gone.pk}/detail/").content.decode()
    assert f"/employees/{three.pk}/order/{other.pk}/detail/" in body and "Алдаа" in body
    body = hr.get(f"/employees/{three.pk}/order/{other.pk}/detail/").content.decode()
    assert f"/employees/{three.pk}/order/{gone.pk}/detail/" in body and "тушаалыг цуцалсан" in body


def test_detail_pop_up_access(client: Client, three: Employee) -> None:
    order = HrOrder.objects.get(number="181")
    detail = f"/employees/{three.pk}/order/{order.pk}/detail/"
    assert client.get(detail).status_code == 302
    link_login(three, login_as(client, "Employee", "me"))
    body = client.get(detail).content.decode()
    assert "Тушаал № 181" in body and "Засах" not in body and "Word татах" not in body  # read-only for the employee
    assert (
        client.get(
            f"/employees/{three.pk}/order/{HrOrder.objects.exclude(employee=three).count() + 99999}/detail/"
        ).status_code
        == 404
    )


def test_hire_order_detail_names_the_hire(hr: Client, hired: Employee) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True, order_type=OrderType.HIRED)
    body = hr.get(f"/employees/{hired.pk}/order/{order.pk}/detail/").content.decode()
    assert "Ажилд авсан" in body and "Санхүү" in body and "Нягтлан" in body
