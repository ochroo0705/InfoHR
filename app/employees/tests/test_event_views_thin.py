"""Pins the rendered date box of the event form, which the Django view writes after the event service builds the form:
the htmx attributes come first and the text-box flag last, as the view always rendered them."""

import re
from datetime import timedelta

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from employees.models import Employee, HrOrder

from .test_event_views import schedule
from .test_views import login_as

pytestmark = pytest.mark.django_db


def url(emp: Employee, type: str) -> str:
    return f"/employees/{emp.pk}/event/{type}/"


def effective_tag(body: str) -> str:
    return re.search(r'<input[^>]*name="effective"[^>]*>', body).group(0)


def test_bad_date_box_keeps_htmx_attributes_before_the_text_box_flag(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    tomorrow = (timezone.localdate() + timedelta(days=30)).isoformat()
    body = client.get(url(hired, "promotion"), {"effective": "2026-13-45", "prev_effective": tomorrow}).content.decode()
    tag = effective_tag(body)
    assert 'type="text"' in tag
    assert f'hx-get="{url(hired, "promotion")}"' in tag
    assert tag.index("hx-params=") < tag.index("data-datepicker")


def test_real_date_box_has_no_text_box_flag(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    tomorrow = (timezone.localdate() + timedelta(days=30)).isoformat()
    body = client.get(url(hired, "promotion"), {"effective": tomorrow}).content.decode()
    tag = effective_tag(body)
    assert f'hx-get="{url(hired, "promotion")}"' in tag
    assert "data-datepicker" not in tag


def test_empty_event_post_shows_the_order_block_unbound(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(url(hired, "promotion"), {})
    assert response.status_code == 200
    order_form = response.context["order_form"]
    assert order_form is not None and not order_form.is_bound


def test_empty_cancel_post_shows_the_unbound_form(client: Client, hired: Employee, actor: User) -> None:
    event = schedule(hired, actor)
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/event/{event.pk}/cancel/", {})
    assert response.status_code == 200
    form = response.context["form"]
    assert not form.is_bound and not form.errors
    assert "errorlist" not in response.content.decode()


def test_empty_upload_post_shows_the_unbound_form(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    response = client.post(reverse("employees:order_upload", args=[hired.pk, order.pk]), {})
    assert response.status_code == 200
    form = response.context["form"]
    assert not form.is_bound and not form.errors
    assert "errorlist" not in response.content.decode()
