"""The Work tab's one list: each change row carries its order (number, state), a click opens the order pop-up, a
cancelled change stays as a struck-through row, and the pop-up cancels the change with its order."""

import pytest
from accounts.models import User
from django.test import Client

from employees.models import Employee, EventType, HrOrder, OrderState
from employees.services import events

from .test_event_views import promote_data, url
from .test_order_cancel import hr, promoted  # noqa: F401  (hr is a fixture)

pytestmark = pytest.mark.django_db


def page(hr: Client, emp: Employee) -> str:  # noqa: F811
    return hr.get(f"/employees/{emp.pk}/").content.decode()


def detail(emp: Employee, order: HrOrder) -> str:
    return f"/employees/{emp.pk}/order/{order.pk}/detail/"


def test_change_rows_carry_their_orders_and_open_the_pop_up(hr: Client, hired: Employee, actor: User) -> None:  # noqa: F811
    hire, promotion = promoted(hr, hired, actor)
    body = page(hr, hired)
    assert "<th>Тушаал</th><th>Тушаалын төлөв</th><th>Хугацаа</th>" in body  # own order columns, date last
    assert f'hx-get="{detail(hired, promotion)}"' in body and "№ 77" in body  # the planned change
    assert f'hx-get="{detail(hired, hire)}"' in body and "№ 10" in body  # the hire row
    assert "Бусад тушаал" not in body  # nothing is left over


def test_a_change_without_a_number_shows_that_it_waits(hr: Client, hired: Employee) -> None:  # noqa: F811
    hr.post(url(hired, "promotion"), promote_data(hired))
    assert "дугаар хүлээгдэж байна" in page(hr, hired)


def test_cancelled_change_stays_as_a_struck_through_row_and_orders_leave_no_leftover(
    hr: Client,  # noqa: F811
    hired: Employee,
    actor: User,
) -> None:
    _, promotion = promoted(hr, hired, actor)
    assert promotion.event is not None
    events.cancel(promotion.event, reason="Буруу", by=actor)
    body = page(hr, hired)
    row = body[body.rindex("<tr", 0, body.index(f'hx-get="{detail(hired, promotion)}"')) :]  # the row's own <tr>
    assert "line-through" in row.split("</tr>")[0] and "Цуцалсан" in row.split("</tr>")[0] and "№ 77" in row
    assert "Бусад тушаал" not in body
    assert HrOrder.objects.get(pk=promotion.pk).state == OrderState.CANCELLED


def test_pop_up_cancels_the_change_with_its_order(hr: Client, hired: Employee, actor: User) -> None:  # noqa: F811
    hire, promotion = promoted(hr, hired, actor)
    body = hr.get(detail(hired, promotion)).content.decode()
    assert f"/employees/{hired.pk}/event/{promotion.event_id}/cancel/" in body and "Тушаал цуцлах" not in body
    assert promotion.event is not None and promotion.event.type == EventType.PROMOTION
    assert "Тушаал цуцлах" in hr.get(detail(hired, hire)).content.decode()  # the hire order has no change to go with
