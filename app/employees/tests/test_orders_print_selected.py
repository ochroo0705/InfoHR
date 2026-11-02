"""Printing the ticked orders of the register as one PDF."""

import re
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse

from employees.models import Employee, HrOrder, OrderState
from employees.services import order_docs

from .test_order_docs import _need_pdf_font, hire_order, hr  # noqa: F401  (hr is a fixture)
from .test_views import login_as

pytestmark = pytest.mark.django_db


def _pages(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", data))


def _post(client: Client, *ids: object) -> Any:
    return client.post(reverse("employees:orders_print_selected"), {"ids": list(ids)})


def test_two_orders_make_a_two_page_pdf(hired: Employee, actor: User) -> None:
    _need_pdf_font()
    order = hire_order(hired)
    data, used = order_docs.render_pdf_many([order, order], actor)
    assert data.startswith(b"%PDF-") and _pages(data) == 2 and used == [order, order]
    assert _pages(order_docs.render_pdf(order, actor)) == 1


def test_nothing_to_print_is_an_error(actor: User) -> None:
    with pytest.raises(order_docs.OrderDocError):
        order_docs.render_pdf_many([], actor)


def test_view_returns_one_pdf(hr: Client, hired: Employee) -> None:  # noqa: F811
    _need_pdf_font()
    order = hire_order(hired)
    response = _post(hr, order.pk)
    assert response.status_code == 200 and response["Content-Type"] == order_docs.PDF_TYPE
    assert b"".join(response.streaming_content).startswith(b"%PDF-")


def test_cancelled_or_unknown_or_bad_ids_print_nothing(hr: Client, hired: Employee) -> None:  # noqa: F811
    _need_pdf_font()
    order = hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    assert _post(hr, order.pk).status_code == 400
    assert _post(hr, 999999, "abc", "-1", "9" * 30).status_code == 400
    assert hr.post(reverse("employees:orders_print_selected")).status_code == 400


def test_needs_the_manage_right_and_post(hr: Client, hired: Employee) -> None:  # noqa: F811
    order = hire_order(hired)
    assert _post(Client(), order.pk).status_code == 302  # not logged in: sent to the login page
    accountant = Client()
    login_as(accountant, "Accountant", "acc1")
    assert _post(accountant, order.pk).status_code == 403
    assert hr.get(reverse("employees:orders_print_selected")).status_code == 405


def test_register_shows_pickers_to_a_manager(hr: Client, hired: Employee) -> None:  # noqa: F811
    body = hr.get(reverse("employees:orders")).content.decode()
    assert 'class="order-pick' in body and "Сонгосныг хэвлэх" in body
