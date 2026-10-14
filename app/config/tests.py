import json

from django.test import Client
from django.utils import translation


def test_mongolian_catalog_loads() -> None:
    with translation.override("mn"):
        assert translation.gettext("Return to site") == "Сайт руу буцах"
        assert translation.gettext("Log in") == "Нэвтрэх"  # from Django itself


def test_mongolian_by_default_even_for_english_browser(client: Client) -> None:
    response = client.get("/admin/login/", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9")
    assert response.headers["Content-Language"] == "mn"
    assert "Нэвтрэх" in response.content.decode()


def test_language_switcher_choice_wins(client: Client) -> None:
    client.cookies["django_language"] = "en"
    response = client.get("/admin/login/")
    assert response.headers["Content-Language"] == "en"


def test_mongolian_js_catalog(admin_client: Client) -> None:
    body = admin_client.get("/admin/jsi18n/").content.decode()
    assert json.dumps("(дарж арилгах)") in body  # from app/locale/mn djangojs.po; served JSON-escaped
