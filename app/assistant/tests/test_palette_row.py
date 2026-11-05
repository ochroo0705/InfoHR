from collections.abc import Callable

import pytest
from accounts.models import User
from django.test import Client, override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

ON = {"ASSISTANT_PROVIDER": "gemini", "ASSISTANT_API_KEY": "k", "ASSISTANT_MODEL": "m"}


def _get(client: Client, role_user: Callable[[str], User], q: str) -> str:
    client.force_login(role_user("hr"))
    return client.get(reverse("employees:palette"), {"q": q}).content.decode()


@override_settings(ASSISTANT_PROVIDER="")
def test_no_ask_row_when_off(client: Client, role_user: Callable[[str], User]) -> None:
    body = _get(client, role_user, "яаж чөлөө")
    assert "data-palette-ask" not in body


@override_settings(**ON)
def test_ask_row_when_on(client: Client, role_user: Callable[[str], User]) -> None:
    body = _get(client, role_user, "чөлөө")
    assert "data-palette-ask" in body
    assert "Асуух: «чөлөө»" in body
    assert "data-palette-ask-first" not in body


@override_settings(**ON)
def test_question_marks_ask_first(client: Client, role_user: Callable[[str], User]) -> None:
    body = _get(client, role_user, "яаж чөлөө бүртгэх вэ")
    assert "data-palette-ask-first" in body


@override_settings(**ON)
def test_no_ask_row_for_empty_box(client: Client, role_user: Callable[[str], User]) -> None:
    body = _get(client, role_user, "")
    assert "data-palette-ask" not in body


@override_settings(**ON)
def test_ask_row_escapes(client: Client, role_user: Callable[[str], User]) -> None:
    body = _get(client, role_user, "<b>x")
    assert "&lt;b&gt;x" in body
    assert "<b>x" not in body
