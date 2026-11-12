"""Login throttle: too many failed logins from one IP lock that IP+username (and the IP as a whole) for a while."""

from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import caches
from django.urls import reverse

from accounts import login_throttle
from accounts.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
WRONG = "wrong-pass-987"  # noqa: S105


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    caches[login_throttle.CACHE_ALIAS].clear()
    yield
    caches[login_throttle.CACHE_ALIAS].clear()


@pytest.fixture
def user() -> User:
    return User.objects.create_user("throttle_user", password=PASSWORD)


def _login(client: Any, username: str, password: str, ip: str = "10.0.0.1") -> Any:
    return client.post(reverse("login"), {"username": username, "password": password}, REMOTE_ADDR=ip)


def test_correct_password_works_below_the_limit(client: Any, user: User) -> None:
    for _ in range(login_throttle.USER_LIMIT - 1):
        _login(client, user.username, WRONG)

    assert _login(client, user.username, PASSWORD).status_code == 302


def test_user_is_locked_after_the_limit_even_with_the_right_password(client: Any, user: User) -> None:
    for _ in range(login_throttle.USER_LIMIT):
        _login(client, user.username, WRONG)

    response = _login(client, user.username, PASSWORD)

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_lock_message_is_shown_on_the_login_page(client: Any, user: User) -> None:
    for _ in range(login_throttle.USER_LIMIT):
        _login(client, user.username, WRONG)

    response = _login(client, user.username, PASSWORD)

    assert login_throttle.LOCK_MESSAGE in response.content.decode()


def test_lock_is_per_ip_and_username(client: Any, user: User) -> None:
    for _ in range(login_throttle.USER_LIMIT):
        _login(client, user.username, WRONG, ip="10.0.0.1")

    assert _login(client, user.username, PASSWORD, ip="10.0.0.2").status_code == 302


def test_username_case_does_not_dodge_the_lock(client: Any, user: User) -> None:
    for _ in range(login_throttle.USER_LIMIT):
        _login(client, user.username.upper(), WRONG)

    assert _login(client, user.username, PASSWORD).status_code == 200


def test_one_ip_guessing_many_usernames_is_locked(client: Any, user: User) -> None:
    for number in range(login_throttle.IP_LIMIT):
        _login(client, f"nobody{number}", WRONG)

    assert _login(client, user.username, PASSWORD).status_code == 200


def test_success_resets_the_user_counter(client: Any, user: User) -> None:
    for _ in range(login_throttle.USER_LIMIT - 1):
        _login(client, user.username, WRONG)
    _login(client, user.username, PASSWORD)
    client.logout()

    for _ in range(login_throttle.USER_LIMIT - 1):
        _login(client, user.username, WRONG)

    assert _login(client, user.username, PASSWORD).status_code == 302


def test_admin_login_is_locked_too(client: Any, user: User) -> None:
    for _ in range(login_throttle.USER_LIMIT):
        _login(client, user.username, WRONG)

    response = client.post(
        reverse("admin:login"), {"username": user.username, "password": PASSWORD}, REMOTE_ADDR="10.0.0.1"
    )

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
