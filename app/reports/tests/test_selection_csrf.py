"""The five selection endpoints need the CSRF token: a logged-in POST without it is refused (403), with it the request
reaches the view (any status but 403). The client enforces the middleware check, which the other tests switch off."""

from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee

from reports.tests.conftest import legacy

pytestmark = pytest.mark.django_db

PAGE = "/reports/staff-list/"
QUERY = "state=all&cols=code&cols=name"
ENDPOINTS = [
    "/reports/staff-list/selected/excel/",
    "/reports/staff-list/selected/csv/",
    "/reports/staff-list/selected/print/",
    "/reports/staff-list/selected/copy/",
    "/reports/staff-list/selected/checklist/",
]


@pytest.fixture
def staff(actor: User, job_values: dict[str, Any]) -> Employee:
    return legacy(actor, job_values)


@pytest.fixture
def hr_client(login_as: Callable[..., User]) -> Client:
    """An HR user whose client enforces CSRF, after one page load (the page sets the csrftoken cookie)."""
    client = Client(enforce_csrf_checks=True)
    login_as(client, "HR", "csrf-hr")
    client.get(PAGE)
    assert "csrftoken" in client.cookies
    return client


@pytest.mark.parametrize("url", ENDPOINTS)
def test_post_without_the_token_is_refused(hr_client: Client, staff: Employee, url: str) -> None:
    resp = hr_client.post(url, {"query": QUERY, "ids": [str(staff.pk)]})
    assert resp.status_code == 403


@pytest.mark.parametrize("url", ENDPOINTS)
def test_post_with_the_token_field_is_accepted(hr_client: Client, staff: Employee, url: str) -> None:
    token = hr_client.cookies["csrftoken"].value
    resp = hr_client.post(url, {"query": QUERY, "ids": [str(staff.pk)], "csrfmiddlewaretoken": token})
    assert resp.status_code != 403


@pytest.mark.parametrize("url", ENDPOINTS)
def test_post_with_the_token_header_is_accepted(hr_client: Client, staff: Employee, url: str) -> None:
    token = hr_client.cookies["csrftoken"].value
    resp = hr_client.post(url, {"query": QUERY, "ids": [str(staff.pk)]}, HTTP_X_CSRFTOKEN=token)
    assert resp.status_code != 403
