"""D-083: no screen creates or advertises an order that waits for its number.

Old pending rows may still exist in the data (Task 3 numbers them), so each screen must also cope with one
without advertising it: no Today tile, no attention item, no register filter, and no demo data."""

from io import StringIO

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from employees import attention
from employees.listing import employee_rows
from employees.models import Employee, HrOrder, OrderState, OrderType

from .test_views import login_as

pytestmark = pytest.mark.django_db


def _hr_user(name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    return user


def _legacy_pending(emp: Employee) -> None:
    """An old-data row: a hire order still waiting for its number."""
    HrOrder.objects.create(employee=emp, is_hire=True, order_type=OrderType.HIRED, state=OrderState.PENDING)


def test_attention_has_no_order_to_follow_item(hired: Employee) -> None:
    _legacy_pending(hired)
    today = timezone.localdate()
    found = attention.items(_hr_user("hr_att_pending"), employee_rows(Employee.objects.all(), today), today)
    assert not [a for a in found if a.kind == "order_number"]
    assert not [a for a in found if "дугаар оруулаагүй" in a.text]


def test_attention_has_no_order_item_for_registered_order(hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired).update(state=OrderState.REGISTERED)
    today = timezone.localdate()
    found = attention.items(_hr_user("hr_att_reg"), employee_rows(Employee.objects.all(), today), today)
    assert not [a for a in found if a.kind == "order_number"]


def test_order_register_has_no_pending_filter(hired: Employee) -> None:
    client = Client()
    login_as(client, "HR", "hr_filter")
    html = client.get(reverse("employees:orders")).content.decode()
    assert '<option value="pending"' not in html
    assert '<option value="registered"' in html


def test_today_has_no_order_badge_for_legacy_pending_row(hired: Employee) -> None:
    _legacy_pending(hired)
    client = Client()
    login_as(client, "HR", "hr_today")
    response = client.get(reverse("employees:today"))
    assert "pending_orders" not in response.context
    assert 'data-tile="orders"' not in response.content.decode()


def test_demo_scenarios_create_no_pending_orders(settings: SettingsWrapper) -> None:
    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    states = set(HrOrder.objects.values_list("state", flat=True))
    assert OrderState.PENDING not in states
    assert {OrderState.REGISTERED, OrderState.SIGNED} <= states


def test_legacy_pending_row_renders_without_pending_text(hired: Employee) -> None:
    """An old pending row still renders on every order screen, without the «дугаар хүлээгдэж байна» text."""
    HrOrder.objects.filter(employee=hired, is_hire=True).update(state=OrderState.PENDING, number="", number_key="")
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    client = Client()
    login_as(client, "HR", "hr_legacy")
    pages = [
        reverse("employees:detail", args=[hired.pk]),
        reverse("employees:orders"),
        reverse("employees:today"),
        reverse("employees:order_detail", args=[hired.pk, order.pk]),
    ]
    for url in pages:
        response = client.get(url)
        assert response.status_code == 200, url
        assert "дугаар хүлээгдэж байна" not in response.content.decode(), url
