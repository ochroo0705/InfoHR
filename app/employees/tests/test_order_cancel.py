"""Cancelling a registered (not yet signed) order on its own, with a reason (D-035): only an order with no change behind
it (the hire order). A change's order is cancelled together with the change; signed orders are not cancelled here."""

from datetime import date

import pytest
from accounts.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from employees.models import ActivityKind, Employee, EventType, HrOrder, OrderState
from employees.services import orders

from .conftest import link_login
from .test_event_views import promote_data, url
from .test_views import login_as

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n%test\n"


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


def promoted(hr: Client, hired: Employee, actor: User, number: str = "77") -> tuple[HrOrder, HrOrder]:
    """The hire order (registered as 10) and a promotion order (registered under `number`)."""
    hire = orders.register(
        HrOrder.objects.get(employee=hired, is_hire=True),
        number="10", date=date(2026, 1, 5), summary="", issued_by="", by=actor,
    )  # fmt: skip
    hr.post(url(hired, "promotion"), promote_data(hired, **{"order-number": number, "order-date": "2026-02-01"}))
    return hire, HrOrder.objects.get(employee=hired, event__type=EventType.PROMOTION)


def cancel_url(emp: Employee, order: HrOrder) -> str:
    return f"/employees/{emp.pk}/order/{order.pk}/cancel/"


def test_cancelling_the_hire_order_logs_reason_and_keeps_number(hr: Client, hired: Employee, actor: User) -> None:
    hire, _ = promoted(hr, hired, actor)
    done = orders.cancel_order(hire, reason="Буруу бичсэн", by=actor)
    assert (done.state, done.cancel_reason, done.number) == (OrderState.CANCELLED, "Буруу бичсэн", "10")
    last = done.activity.order_by("id").last()
    assert last is not None and "цуцалсан" in last.message and "Буруу бичсэн" in last.message and last.by == actor
    assert last.kind == ActivityKind.CANCELLED


def test_a_changes_order_is_not_cancelled_on_its_own(hr: Client, hired: Employee, actor: User) -> None:
    _, promotion = promoted(hr, hired, actor)
    with pytest.raises(orders.OrderError):
        orders.cancel_order(promotion, reason="x", by=actor)  # it goes with its change
    assert hr.get(cancel_url(hired, promotion)).status_code == 404
    assert HrOrder.objects.get(pk=promotion.pk).state == OrderState.REGISTERED


def test_only_a_registered_order_can_be_cancelled(hr: Client, hired: Employee, actor: User) -> None:
    pending = HrOrder.objects.get(employee=hired, is_hire=True)
    with pytest.raises(orders.OrderError):
        orders.cancel_order(pending, reason="x", by=actor)  # never issued
    _, signed = promoted(hr, hired, actor)
    orders.attach_signed_file(signed, SimpleUploadedFile("a.pdf", PDF), by=actor)
    with pytest.raises(orders.OrderError):
        orders.cancel_order(signed, reason="x", by=actor)  # signed orders are final
    signed.refresh_from_db()
    assert signed.state == OrderState.SIGNED
    HrOrder.objects.filter(pk=pending.pk).update(state=OrderState.CANCELLED)
    with pytest.raises(orders.OrderError):
        orders.cancel_order(HrOrder.objects.get(pk=pending.pk), reason="x", by=actor)  # already cancelled


def test_cancel_form_asks_only_for_a_reason_and_saves(hr: Client, hired: Employee, actor: User) -> None:
    promotion, _ = promoted(hr, hired, actor)
    page = hr.get(cancel_url(hired, promotion)).content.decode()
    assert "Цуцлах шалтгаан" in page and "cancel_order_no" not in page
    assert "Өөрчлөлт өөрөө хэвээр үлдэнэ" in page
    assert hr.post(cancel_url(hired, promotion), {}).status_code == 200  # the reason is required
    assert hr.post(cancel_url(hired, promotion), {"reason": "Буруу"}).status_code == 204
    promotion.refresh_from_db()
    assert promotion.state == OrderState.CANCELLED and promotion.cancel_order_no == ""


def test_cancel_view_rules(client: Client, hired: Employee, actor: User) -> None:
    pending = HrOrder.objects.get(employee=hired, is_hire=True)
    assert client.get(cancel_url(hired, pending)).status_code == 302
    link_login(hired, login_as(client, "Employee", "me"))
    assert client.get(cancel_url(hired, pending)).status_code == 403
    login_as(client, "HR", "hr2")
    assert client.get(cancel_url(hired, pending)).status_code == 404  # nothing to cancel on a pending order


def test_a_signed_order_has_no_cancel_page(hr: Client, hired: Employee, actor: User) -> None:
    promotion, _ = promoted(hr, hired, actor)
    orders.attach_signed_file(promotion, SimpleUploadedFile("a.pdf", PDF), by=actor)
    assert hr.get(cancel_url(hired, promotion)).status_code == 404
    assert hr.post(cancel_url(hired, promotion), {"reason": "x"}).status_code == 404


def test_detail_pop_up_offers_cancel_only_for_a_registered_order(hr: Client, hired: Employee, actor: User) -> None:
    promotion, change_order = promoted(hr, hired, actor)
    detail = f"/employees/{hired.pk}/order/{promotion.pk}/detail/"
    assert "Тушаал цуцлах" in hr.get(detail).content.decode()
    assert "Тушаал цуцлах" not in hr.get(f"/employees/{hired.pk}/order/{change_order.pk}/detail/").content.decode()
    orders.attach_signed_file(promotion, SimpleUploadedFile("a.pdf", PDF), by=actor)
    body = hr.get(detail).content.decode()
    assert "Тушаал цуцлах" not in body and "Шинэ тушаалаар солих" not in body
    HrOrder.objects.filter(pk=promotion.pk).update(state=OrderState.CANCELLED)
    assert "Тушаал цуцлах" not in hr.get(detail).content.decode()
