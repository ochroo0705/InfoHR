import secrets

import pytest
from accounts import login_throttle
from django.contrib.auth import get_user_model
from django.test import Client

PASSWORD = secrets.token_urlsafe(16)


@pytest.fixture
def user(db: None) -> object:
    return get_user_model().objects.create_user("auth-user", password=PASSWORD)


@pytest.fixture
def logged_in_client(user: object) -> Client:
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    return client


def test_csrf_returns_token(client: Client) -> None:
    response = client.get("/api/v1/auth/csrf")

    assert response.status_code == 200
    assert len(response.json()["token"]) >= 32


def test_post_without_token_refused(logged_in_client: Client) -> None:
    response = logged_in_client.post("/api/v1/auth/logout")

    assert response.status_code == 403


def test_post_with_token_accepted(logged_in_client: Client) -> None:
    token = logged_in_client.get("/api/v1/auth/csrf").json()["token"]

    response = logged_in_client.post("/api/v1/auth/logout", HTTP_X_CSRFTOKEN=token)

    assert response.status_code == 204


def test_login_without_token_refused(user: object) -> None:
    client = Client(enforce_csrf_checks=True)

    response = client.post(
        "/api/v1/auth/login",
        {"username": "auth-user", "password": PASSWORD},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert "_auth_user_id" not in client.session


def test_login_ok(user: object) -> None:
    client = Client(enforce_csrf_checks=True)
    token = client.get("/api/v1/auth/csrf").json()["token"]

    response = client.post(
        "/api/v1/auth/login",
        {"username": "auth-user", "password": PASSWORD},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["must_change_password"] is False
    # login() rotates the CSRF secret: the pre-login token is stale and the returned one must work.
    assert body["csrf"] != token
    assert "_auth_user_id" in client.session

    logout = client.post("/api/v1/auth/logout", HTTP_X_CSRFTOKEN=body["csrf"])

    assert logout.status_code == 204


def test_login_wrong_password(user: object) -> None:
    client = Client()

    response = client.post(
        "/api/v1/auth/login",
        {"username": "auth-user", "password": "wrong-" + PASSWORD},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["form_errors"] == ["Нэвтрэх нэр эсвэл нууц үг буруу байна."]
    assert "_auth_user_id" not in client.session


def test_login_locked(user: object) -> None:
    client = Client()
    bad = {"username": "auth-user", "password": "wrong-" + PASSWORD}
    for _ in range(login_throttle.USER_LIMIT):
        client.post("/api/v1/auth/login", bad, content_type="application/json")

    response = client.post(
        "/api/v1/auth/login",
        {"username": "auth-user", "password": PASSWORD},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["form_errors"] == [login_throttle.LOCK_MESSAGE]


def test_logout(logged_in_client: Client) -> None:
    token = logged_in_client.get("/api/v1/auth/csrf").json()["token"]

    logged_in_client.post("/api/v1/auth/logout", HTTP_X_CSRFTOKEN=token)

    assert "_auth_user_id" not in logged_in_client.session
