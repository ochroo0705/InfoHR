"""History of one order (who/when/what) and the link between an order and the order that cancelled it."""

from datetime import date

import pytest
from accounts.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from employees.models import ActivityEntry, Employee, Event, EventType, HrOrder, OrderState, OrderType
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


def hire_order(emp: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=emp, is_hire=True)


def history(order: HrOrder) -> list[ActivityEntry]:
    return list(order.activity.order_by("id"))


def test_a_pending_order_has_no_history_yet(hired: Employee) -> None:
    assert history(hire_order(hired)) == []  # the hire/change entry of the activity drawer already says it was made


def test_registering_and_editing_are_logged_with_who_and_what_changed(hired: Employee, actor: User) -> None:
    order = hire_order(hired)
    orders.register(order, number="12", date=date(2026, 1, 5), summary="Томилов", issued_by="Б. Дорж", by=actor)
    registered = history(order)[-1]
    assert "бүртгэсэн" in registered.message and registered.by == actor
    assert {"field": "Дугаар", "old": "", "new": "12"} in registered.changes
    orders.register(order, number="13", date=date(2026, 1, 5), summary="Томилов", issued_by="Б. Дорж", by=actor)
    edited = history(order)[-1]
    assert "засварласан" in edited.message and edited.changes == [{"field": "Дугаар", "old": "12", "new": "13"}]


def test_saving_an_order_without_changes_adds_no_entry(hired: Employee, actor: User) -> None:
    order = hire_order(hired)
    kwargs = {"number": "12", "date": date(2026, 1, 5), "summary": "", "issued_by": "Б. Дорж", "by": actor}
    orders.register(order, **kwargs)  # type: ignore[arg-type]
    count = order.activity.count()
    orders.register(order, **kwargs)  # type: ignore[arg-type]
    assert order.activity.count() == count


def test_signing_and_cancelling_are_logged(hr: Client, hired: Employee, actor: User) -> None:
    hr.post(url(hired, "promotion"), promote_data(hired, **{"order-number": "77", "order-date": "2026-02-01"}))
    event = hired.events.get(type=EventType.PROMOTION)
    order = HrOrder.objects.get(event=event)
    orders.attach_signed_file(order, SimpleUploadedFile("a.pdf", PDF), by=actor)
    assert "гарын үсэгтэй файл" in history(order)[-1].message and history(order)[-1].by == actor
    assert (
        hr.post(
            f"/employees/{hired.pk}/event/{event.pk}/cancel/", {"reason": "Буруу", "cancel_order_no": "78"}
        ).status_code
        == 204
    )
    last = history(order)[-1]
    assert "цуцалсан" in last.message and "Буруу" in last.message and "№ 78" in last.message
    assert last.by is not None and last.by.username == "hr1"


def test_order_entries_also_show_in_the_employee_activity(hired: Employee, actor: User) -> None:
    order = hire_order(hired)
    orders.register(order, number="12", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    assert hired.activity.filter(order=order, message__contains="№ 12").exists()


def make_cancelled(emp: Employee, number: str, cancelled_by_no: str) -> HrOrder:
    # An applied change whose order was cancelled (not a waiting change, which shows in the «Гарын үсэг хүлээж» block).
    event = Event.objects.create(
        employee=emp, type=EventType.PROMOTION, effective=date(2026, 2, 1), applied_at=timezone.now()
    )
    return HrOrder.objects.create(
        employee=emp, event=event, order_type=OrderType.POSITION, state=OrderState.CANCELLED,
        number=number, number_key=number.casefold(), date=date(2026, 2, 1), cancel_order_no=cancelled_by_no,
    )  # fmt: skip


def test_cancellation_links_point_both_ways(hired: Employee, actor: User) -> None:
    hire = orders.register(hire_order(hired), number="20", date=date(2026, 3, 1), summary="", issued_by="", by=actor)
    gone = make_cancelled(hired, "15", "20")
    orphan = make_cancelled(hired, "16", "999")  # the cancelling order is not one of ours
    links = orders.cancellation_links([hire, gone, orphan])
    assert links[gone.pk]["cancelled_by"] == hire and links[hire.pk]["cancels"] == [gone]
    assert links[orphan.pk]["cancelled_by"] is None and links[hire.pk]["cancels"] == [gone]


def test_panel_opens_the_cancelling_order_pop_up(hr: Client, hired: Employee, actor: User) -> None:
    hire = orders.register(hire_order(hired), number="20", date=date(2026, 3, 1), summary="", issued_by="", by=actor)
    gone = make_cancelled(hired, "15", "20")
    body = hr.get(f"/employees/{hired.pk}/").content.decode()
    detail = f"/employees/{hired.pk}/order/%s/detail/"
    assert f'id="order-{gone.pk}"' in body  # not claimed by a change row: it stays in the «Бусад тушаал» panel
    assert f'hx-get="{detail % hire.pk}"' in body  # the hire row and the link both open the hire order's pop-up


def test_history_pop_up_lists_only_this_orders_entries(hr: Client, hired: Employee, actor: User) -> None:
    order = hire_order(hired)
    orders.register(order, number="12", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    other = make_cancelled(hired, "15", "")
    orders_url = f"/employees/{hired.pk}/order/{order.pk}/history/"
    body = hr.get(orders_url).content.decode()
    assert "Тушаалын түүх" in body and "бүртгэсэн" in body
    assert "цуцалсан" not in body
    assert hr.get(f"/employees/{hired.pk}/order/{other.pk}/history/").status_code == 200


def test_history_pop_up_needs_a_login_and_a_visible_employee(client: Client, hired: Employee) -> None:
    order_url = f"/employees/{hired.pk}/order/{hire_order(hired).pk}/history/"
    assert client.get(order_url).status_code == 302
    link_login(hired, login_as(client, "Employee", "me"))
    assert client.get(order_url).status_code == 200  # their own record


def test_work_tab_tables_are_framed(hr: Client, hired: Employee, actor: User) -> None:
    """«Ажлын түүх» and «Бусад тушаал» use the page's framed table (UI_RULES §4); the orders frame never clips the
    rows' «Үйлдэл ▾» menus."""
    orders.register(hire_order(hired), number="20", date=date(2026, 3, 1), summary="", issued_by="", by=actor)
    make_cancelled(hired, "15", "20")
    body = hr.get(f"/employees/{hired.pk}/").content.decode()
    work = body[body.index('id="tab-work"') : body.index('id="tab-personal"')]
    assert '<div class="ptable"><table>' in work and '<div class="ptable overflow-visible"><table>' in work
    assert "uppercase" not in work
