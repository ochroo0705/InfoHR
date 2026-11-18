"""The employee page's small writes: a note (POST /api/v1/employees/{pk}/note), a setup item toggle (POST
.../setup/{key}) and a login create (POST .../login, answered no-store with the one-time password)."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from employees.models import ActivityEntry, ActivityKind, Employee, SetupItem
from employees.services import history, logins, macs_writes
from employees.tests.conftest import hire_values

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("employee_misc_write_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    return user


@pytest.fixture
def accountant(db: None) -> User:
    user = User.objects.create_user("employee_misc_write_acc", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.ACCOUNTANT)[0])  # cannot manage employees
    return user


@pytest.fixture
def hired(hr_user: User) -> Employee:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _note(client: Client, pk: int, text: str) -> Any:
    return client.post(
        f"/api/v1/employees/{pk}/note",
        data=json.dumps({"text": text}),
        content_type="application/json",
    )


def _login(client: Client, pk: int, username: str) -> Any:
    return client.post(
        f"/api/v1/employees/{pk}/login",
        data=json.dumps({"username": username}),
        content_type="application/json",
    )


def _toggle(client: Client, pk: int, key: str) -> Any:
    return client.post(f"/api/v1/employees/{pk}/setup/{key}")


# --- note ---------------------------------------------------------------------------------------------------------


def test_note_adds_an_activity_entry(hr_user: User, hired: Employee) -> None:
    response = _note(_client(hr_user), hired.pk, "  Сайн уу  ")
    assert response.status_code == 204, response.content
    entry = ActivityEntry.objects.get(employee=hired, kind=ActivityKind.NOTE)
    assert entry.message == "Сайн уу"
    assert entry.by == hr_user


def test_blank_note_adds_nothing_and_is_204(hr_user: User, hired: Employee) -> None:
    before = ActivityEntry.objects.filter(employee=hired).count()
    response = _note(_client(hr_user), hired.pk, "   ")
    assert response.status_code == 204
    assert ActivityEntry.objects.filter(employee=hired).count() == before


def test_non_manager_cannot_add_a_note(accountant: User, hired: Employee) -> None:
    before = ActivityEntry.objects.filter(employee=hired).count()
    response = _note(_client(accountant), hired.pk, "Сайн уу")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert ActivityEntry.objects.filter(employee=hired).count() == before


def test_note_unknown_pk_is_404(hr_user: User) -> None:
    assert _note(_client(hr_user), 999999, "Сайн уу").status_code == 404


def test_note_anonymous_is_401(hired: Employee) -> None:
    assert _note(Client(), hired.pk, "Сайн уу").status_code == 401


# --- setup toggle -------------------------------------------------------------------------------------------------


def test_toggle_ticks_and_unticks_a_setup_item(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    assert _toggle(client, hired.pk, "contract").status_code == 204
    assert SetupItem.objects.filter(employee=hired, key="contract").exists()
    assert _toggle(client, hired.pk, "contract").status_code == 204
    assert not SetupItem.objects.filter(employee=hired, key="contract").exists()


def test_toggling_a_system_item_is_400(hr_user: User, hired: Employee) -> None:
    response = _toggle(_client(hr_user), hired.pk, "bank")  # bank is ticked by the data, not by hand
    assert response.status_code == 400
    assert response.json()["form_errors"]
    assert not SetupItem.objects.filter(employee=hired, key="bank").exists()


def test_non_manager_cannot_toggle_a_setup_item(accountant: User, hired: Employee) -> None:
    response = _toggle(_client(accountant), hired.pk, "contract")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert not SetupItem.objects.filter(employee=hired).exists()


def test_toggle_after_setup_is_done_is_403(hr_user: User, hired: Employee) -> None:
    hired.ext.setup_required = False
    hired.ext.save(update_fields=["setup_required"])
    response = _toggle(_client(hr_user), hired.pk, "contract")
    assert response.status_code == 403
    assert not SetupItem.objects.filter(employee=hired).exists()


def test_toggle_unknown_pk_is_404(hr_user: User) -> None:
    assert _toggle(_client(hr_user), 999999, "contract").status_code == 404


def test_toggle_anonymous_is_401(hired: Employee) -> None:
    assert _toggle(Client(), hired.pk, "contract").status_code == 401


# --- login create -------------------------------------------------------------------------------------------------


def test_login_create_returns_username_and_password_no_store(hr_user: User, hired: Employee) -> None:
    response = _login(_client(hr_user), hired.pk, "new.staff")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["username"] == "new.staff"
    assert body["password"]
    assert response["Cache-Control"] == "no-store"
    hired.ext.refresh_from_db()
    assert hired.ext.user is not None and hired.ext.user.username == "new.staff"


def test_second_login_for_the_same_employee_is_400(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    assert _login(client, hired.pk, "new.staff").status_code == 200
    response = _login(client, hired.pk, "other.name")
    assert response.status_code == 400
    assert response.json()["form_errors"]
    assert not User.objects.filter(username="other.name").exists()


def test_taken_username_is_400_form_error(hr_user: User, hired: Employee) -> None:
    User.objects.create_user("taken.name", password=PASSWORD)
    response = _login(_client(hr_user), hired.pk, "taken.name")
    assert response.status_code == 400
    assert response.json()["form_errors"]


def test_blank_username_is_a_field_error(hr_user: User, hired: Employee) -> None:
    response = _login(_client(hr_user), hired.pk, "   ")
    assert response.status_code == 400
    body = response.json()
    assert body["field_errors"]["username"]
    hired.ext.refresh_from_db()
    assert hired.ext.user is None


def test_non_manager_cannot_create_a_login(accountant: User, hired: Employee) -> None:
    response = _login(_client(accountant), hired.pk, "new.staff")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    hired.ext.refresh_from_db()
    assert hired.ext.user is None


def test_login_unknown_pk_is_404(hr_user: User) -> None:
    assert _login(_client(hr_user), 999999, "new.staff").status_code == 404


def test_login_anonymous_is_401(hired: Employee) -> None:
    assert _login(Client(), hired.pk, "new.staff").status_code == 401


def test_non_string_note_text_is_400(hr_user: User, hired: Employee) -> None:
    response = _client(hr_user).post(
        f"/api/v1/employees/{hired.pk}/note",
        data=json.dumps({"text": 5}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["field_errors"]["text"]


def test_non_string_username_is_400(hr_user: User, hired: Employee) -> None:
    response = _client(hr_user).post(
        f"/api/v1/employees/{hired.pk}/login",
        data=json.dumps({"username": ["new.staff"]}),
        content_type="application/json",
    )
    assert response.status_code == 400
    hired.ext.refresh_from_db()
    assert hired.ext.user is None


# --- the service, as the Django views call it -------------------------------------------------------------------


def test_create_login_twice_for_one_employee_is_a_value_error(hr_user: User, hired: Employee) -> None:
    logins.create_login(hired, "first.name", by=hr_user)
    with pytest.raises(ValueError, match="аль хэдийн байна"):
        logins.create_login(hired, "second.name", by=hr_user)
    assert not User.objects.filter(username="second.name").exists()


def test_create_login_with_an_existing_username_is_a_value_error(hr_user: User, hired: Employee) -> None:
    User.objects.create_user("taken.name", password=PASSWORD)
    with pytest.raises(ValueError, match="бүртгэлтэй байна"):
        logins.create_login(hired, "taken.name", by=hr_user)
    hired.ext.refresh_from_db()
    assert hired.ext.user is None
