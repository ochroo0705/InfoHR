import pytest
from accounts.models import User
from django.test import Client

pytestmark = pytest.mark.django_db


def test_report_page_body_carries_the_user_id(client: Client, login_hr: User) -> None:
    """The browser script keys the remembered setup by this id, so each user gets their own memory."""
    response = client.get("/reports/staff-list/")
    assert response.status_code == 200
    assert f'data-user-id="{login_hr.pk}"'.encode() in response.content


def test_report_page_has_a_reset_link(client: Client, login_hr: User) -> None:
    response = client.get("/reports/staff-list/")
    assert response.status_code == 200
    assert b"data-reset-all" in response.content


def test_login_page_has_no_user_id(client: Client) -> None:
    response = client.get("/login/")
    assert response.status_code == 200
    assert b"data-user-id" not in response.content
