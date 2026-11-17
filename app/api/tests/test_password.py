import secrets

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

PASSWORD = secrets.token_urlsafe(16)
NEW_PASSWORD = "Aa1" + secrets.token_urlsafe(12)


@pytest.fixture
def forced_user(db: None) -> object:
    user = get_user_model().objects.create_user("forced-user", password=PASSWORD)
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])
    return user


@pytest.fixture
def forced_client(forced_user: object) -> Client:
    client = Client(enforce_csrf_checks=True)
    client.force_login(forced_user)
    return client


@pytest.fixture
def user_for_password(db: None) -> object:
    # An ordinary account (no forced change): the old password is required.
    return get_user_model().objects.create_user("normal-user", password=PASSWORD)


def _token(client: Client) -> str:
    return client.get("/api/v1/auth/csrf").json()["token"]


def test_forced_user_gets_json_403(forced_client: Client) -> None:
    # Task 6 adds /api/v1/nav; until then /api/v1/openapi.json is the non-exempt API path used here.
    response = forced_client.get("/api/v1/openapi.json")

    assert response.status_code == 403
    assert response.json()["code"] == "password_change_required"


def test_forced_user_reaches_auth(forced_client: Client) -> None:
    response = forced_client.get("/api/v1/auth/csrf")

    assert response.status_code == 200


def test_password_change_ok(forced_client: Client, forced_user: object) -> None:
    response = forced_client.post(
        "/api/v1/auth/password",
        {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=_token(forced_client),
    )

    assert response.status_code == 204
    forced_user.refresh_from_db()
    assert forced_user.must_change_password is False
    assert forced_client.get("/api/v1/auth/csrf").status_code == 200
    assert "_auth_user_id" in forced_client.session


def test_password_change_mismatch(forced_client: Client, forced_user: object) -> None:
    response = forced_client.post(
        "/api/v1/auth/password",
        {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD + "x"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=_token(forced_client),
    )

    assert response.status_code == 400
    assert "new_password2" in response.json()["field_errors"]
    forced_user.refresh_from_db()
    assert forced_user.must_change_password is True


def test_html_redirect_unchanged(forced_client: Client) -> None:
    response = forced_client.get("/")

    assert response.status_code == 302
    assert response["Location"] == reverse("password_change")


def test_password_without_csrf_refused(user_for_password: object) -> None:
    # Signed-in session, valid body, but no X-CSRFToken header: must be refused.
    client = Client(enforce_csrf_checks=True)
    client.force_login(user_for_password)

    response = client.post(
        "/api/v1/auth/password",
        {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        content_type="application/json",
    )

    assert response.status_code == 403
    user_for_password.refresh_from_db()
    assert user_for_password.check_password(PASSWORD) is True


def test_password_change_normal_user_wrong_old(user_for_password: object) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(user_for_password)

    response = client.post(
        "/api/v1/auth/password",
        {"old_password": "wrong-" + PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=_token(client),
    )

    assert response.status_code == 400
    assert "old_password" in response.json()["field_errors"]
    user_for_password.refresh_from_db()
    assert user_for_password.check_password(PASSWORD) is True


def test_password_change_normal_user_ok(user_for_password: object) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(user_for_password)

    response = client.post(
        "/api/v1/auth/password",
        {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=_token(client),
    )

    assert response.status_code == 204
    user_for_password.refresh_from_db()
    assert user_for_password.check_password(NEW_PASSWORD) is True
