"""System log: login, failed login and logout are recorded; the client IP comes from the trusted proxy setting."""

from collections.abc import Iterator
from typing import Any

import pytest
from django.test import RequestFactory
from django.urls import reverse

from accounts import audit_context
from accounts.middleware import client_ip
from accounts.models import SystemLogEntry, User

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    audit_context.clear_context()
    yield
    audit_context.clear_context()


@pytest.fixture
def user() -> User:
    return User.objects.create_user("audit_access_user", password=PASSWORD)


def _rows(action: str) -> list[SystemLogEntry]:
    return list(SystemLogEntry.objects.filter(action=action).order_by("id"))


def test_login_logged_with_ip(client: Any, user: User) -> None:
    response = client.post(reverse("login"), {"username": user.username, "password": PASSWORD})

    assert response.status_code == 302
    rows = _rows("login")
    assert len(rows) == 1
    assert rows[0].category == "access"
    assert rows[0].actor == user
    assert rows[0].ip == "127.0.0.1"


def test_failed_login_records_typed_username_not_password(client: Any, user: User) -> None:
    wrong_password = "wrong-secret-987"  # noqa: S105
    client.post(reverse("login"), {"username": user.username, "password": wrong_password})

    rows = _rows("login_failed")
    assert len(rows) == 1
    entry = rows[0]
    assert entry.actor is None
    assert entry.message == user.username
    for field in SystemLogEntry._meta.fields:
        assert wrong_password not in str(getattr(entry, field.attname))


def test_long_unicode_username_cut_to_150(client: Any) -> None:
    long_name = "Ө" * 300
    client.post(reverse("login"), {"username": long_name, "password": "whatever-pass-1"})  # noqa: S106

    rows = _rows("login_failed")
    assert len(rows) == 1
    assert rows[0].message == "Ө" * 150


def test_logout_logged(client: Any, user: User) -> None:
    client.force_login(user)

    response = client.post(reverse("logout"))

    assert response.status_code == 302
    rows = _rows("logout")
    assert len(rows) == 1
    assert rows[0].actor == user
    assert rows[0].category == "access"


def test_client_ip_uses_proxy_header_only_when_setting_set(settings: Any) -> None:
    factory = RequestFactory()
    request = factory.get("/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1", REMOTE_ADDR="10.9.9.9")

    settings.AUDIT_TRUSTED_PROXY_HEADER = "HTTP_X_FORWARDED_FOR"
    assert client_ip(request) == "10.0.0.1"

    settings.AUDIT_TRUSTED_PROXY_HEADER = ""
    assert client_ip(request) == "10.9.9.9"


def test_client_ip_garbage_header_gives_none(settings: Any) -> None:
    factory = RequestFactory()
    request = factory.get("/", HTTP_X_FORWARDED_FOR="not-an-ip", REMOTE_ADDR="10.9.9.9")
    settings.AUDIT_TRUSTED_PROXY_HEADER = "HTTP_X_FORWARDED_FOR"

    assert client_ip(request) is None


def test_log_failure_does_not_block_login(client: Any, user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def boom(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise RuntimeError("database is down")

    monkeypatch.setattr(SystemLogEntry.objects, "create", boom)

    response = client.post(reverse("login"), {"username": user.username, "password": PASSWORD})

    assert calls, "the log insert was never attempted"
    assert calls[0]["action"] == "login"
    assert response.status_code == 302
    assert "_auth_user_id" in client.session


def test_anonymous_logout_writes_no_row(client: Any) -> None:
    response = client.post(reverse("logout"))

    assert response.status_code == 302
    assert _rows("logout") == []
