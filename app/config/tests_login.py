import pytest
from django.test import Client


def test_home_requires_login(client: Client) -> None:
    response = client.get("/")
    assert response.status_code == 302 and "/login/" in response.headers["Location"]


@pytest.mark.django_db
def test_login_page_is_mongolian(client: Client) -> None:
    body = client.get("/login/").content.decode()
    assert "Нэвтрэх" in body and "htmx.min.js" in body
