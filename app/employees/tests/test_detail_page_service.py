"""The employee page's read rules, with no request (employees/services/detail_page.py)."""

from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.utils import timezone

from employees import views
from employees.models import Employee
from employees.services import detail_page

pytestmark = pytest.mark.django_db

REQUEST_KEYS = {"form", "si_form", "order_warning"}


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("detail_hr", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    return user


def _request(user: User) -> Any:
    request = RequestFactory().get("/")
    request.user = user
    request.session = {}
    return request


def test_facts_plus_request_keys_are_the_django_context(hired: Employee, hr_user: User) -> None:
    facts = detail_page.detail_facts(hr_user, hired, timezone.localdate())
    context = views.detail_context(_request(hr_user), hired)
    assert set(facts) | REQUEST_KEYS == set(context)


def test_facts_hide_salary_from_a_user_without_the_right(hired: Employee) -> None:
    viewer = User.objects.create_user("detail_plain", password="x-long-pass-123")  # noqa: S106
    facts = detail_page.detail_facts(viewer, hired, timezone.localdate())
    assert facts["can_view_salary"] is False
    assert facts["salary"] is None
    assert facts["salaries"] == []
