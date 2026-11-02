"""Which changes need an HR order is a per-install setting (CompanySettings.order_*, D-052). A type that is off
applies on its date with no order; everything already recorded stays as it was."""

from datetime import date

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from macs.models import Employee as MacsEmployee
from macs.models import FiredReason

from employees.models import CompanySettings, Employee, Event, HrOrder, JobStatus, OrderType
from employees.services import events, history, macs_writes

from .conftest import named
from .test_hire_personal import hire_post
from .test_views import login_as

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)


def switch_off(*flags: str) -> None:
    CompanySettings.objects.update_or_create(pk=1, defaults={flag: False for flag in flags})


def promote(employee: Employee, actor: User) -> Event:
    position = macs_writes.save_position("Ахлах мэргэжилтэн")
    return events.record(
        employee,
        type="promotion",
        effective=DAY,
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
    )


def test_every_type_needs_an_order_by_default() -> None:
    settings = CompanySettings.get()
    assert all(settings.requires_order(t.value) for t in OrderType)


def test_a_type_that_is_off_applies_at_once_with_no_order(hired: Employee, actor: User) -> None:
    switch_off("order_position")
    ev = promote(hired, actor)
    assert ev.applied_at is not None
    assert not HrOrder.objects.filter(event=ev).exists()
    job = history.job_on(hired, DAY)
    assert job is not None and job.position.name == "Ахлах мэргэжилтэн"


def test_other_types_still_wait_for_their_order(hired: Employee, actor: User) -> None:
    switch_off("order_position")  # position orders are on paper, department transfers are not
    engineering = macs_writes.save_department("Инженер")
    ev = events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert ev.applied_at is None
    assert HrOrder.objects.filter(event=ev).exists()


def test_termination_with_its_order_off_applies_at_once(hired: Employee, actor: User) -> None:
    switch_off("order_fired", "order_pension")
    ev = events.record(
        hired,
        type="termination",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    assert ev.applied_at is not None and not HrOrder.objects.filter(event=ev).exists()
    job = history.job_on(hired, DAY)
    assert job is not None and job.status == JobStatus.LEFT


def test_turning_a_type_off_leaves_a_waiting_change_waiting(hired: Employee, actor: User) -> None:
    ev = promote(hired, actor)  # on by default: it waits for its order
    assert ev.applied_at is None
    switch_off("order_position")
    ev.refresh_from_db()
    assert ev.applied_at is None and HrOrder.objects.filter(event=ev).exists()


def test_orders_made_before_the_switch_stay_in_the_register(hired: Employee, actor: User, hr_client: Client) -> None:
    order = HrOrder.objects.get(event=promote(hired, actor))
    switch_off("order_position")
    body = hr_client.get("/employees/orders/").content.decode()
    assert reverse("employees:order_detail", args=[hired.pk, order.pk]) in body


@pytest.fixture
def hr_client(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


def test_hire_form_has_order_fields_by_default(hr_client: Client) -> None:
    assert 'name="order-number"' in hr_client.get("/employees/new/").content.decode()


def test_hire_with_its_order_off_has_no_order_fields_and_no_order(hr_client: Client) -> None:
    switch_off("order_hired")
    assert 'name="order-number"' not in hr_client.get("/employees/new/").content.decode()
    response = hr_client.post("/employees/new/", hire_post({}))
    assert response.status_code in (200, 204, 302)
    assert MacsEmployee.objects.count() == 1
    assert not HrOrder.objects.exists()


def test_event_form_hides_the_order_fields_only_when_every_type_it_can_need_is_off(
    hired: Employee, hr_client: Client
) -> None:
    url = f"/employees/{hired.pk}/event/transfer/"
    assert 'name="order-number"' in hr_client.get(url).content.decode()
    switch_off("order_department", "order_position")
    assert 'name="order-number"' in hr_client.get(url).content.decode()  # employee type changes still need one
    switch_off("order_department", "order_position", "order_type_changed")
    assert 'name="order-number"' not in hr_client.get(url).content.decode()


def test_admin_page_offers_the_six_switches() -> None:
    CompanySettings.get()
    client = Client()
    client.force_login(User.objects.create_superuser("switch_admin", password="x-long-pass-123"))  # noqa: S106
    body = client.get(reverse("admin:employees_companysettings_change", args=[1])).content.decode()
    for flag in CompanySettings.ORDER_FLAGS.values():
        assert f'name="{flag}"' in body
