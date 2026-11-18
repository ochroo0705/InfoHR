"""POST /api/v1/employees/{pk}/personal/sections/{section}: one personal section's save, and the `loaded` snapshot the
personal tab (GET /api/v1/employees/{pk}/personal) hands the page for the stale check."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees import sections
from employees.models import ActivityEntry, Employee
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("employee_personal_write_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
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


def _identity_loaded(client: Client, pk: int) -> str:
    body = client.get(f"/api/v1/employees/{pk}/personal").json()
    return next(section for section in body["sections"] if section["name"] == "identity")["loaded"]


def _save(client: Client, pk: int, section: str, values: dict[str, str], **extra: Any) -> Any:
    body = {"values": values, **extra}
    return client.post(
        f"/api/v1/employees/{pk}/personal/sections/{section}",
        data=json.dumps(body),
        content_type="application/json",
    )


def test_identity_save_writes_the_field_and_logs_an_activity_row(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    loaded = _identity_loaded(client, hired.pk)
    response = _save(client, hired.pk, "identity", {"clan_name": "Ботгон"}, loaded=loaded)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is True
    assert body["field_errors"] == {} and body["form_errors"] == [] and body["conflicts"] == {}
    assert body["tab"] == "personal"
    hired.refresh_from_db()
    assert hired.clan_name == "Ботгон"
    assert ActivityEntry.objects.filter(employee=hired, personal=True, message="Хувийн мэдээлэл өөрчилсөн").exists()


def test_clash_returns_conflicts_and_writes_nothing(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    loaded = _identity_loaded(client, hired.pk)
    Employee.objects.filter(pk=hired.pk).update(clan_name="Өөр")  # MACS changed it meanwhile
    response = _save(client, hired.pk, "identity", {"clan_name": "Шинэ"}, loaded=loaded)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["conflicts"] == {"clan_name": "Өөр"}
    assert body["field_errors"]["clan_name"]
    assert json.loads(body["loaded"])["clan_name"] == "Өөр"  # a fresh snapshot for the re-render
    hired.refresh_from_db()
    assert hired.clan_name == "Өөр"


def test_resolve_mine_writes_after_a_clash(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    loaded = _identity_loaded(client, hired.pk)
    Employee.objects.filter(pk=hired.pk).update(clan_name="Өөр")
    response = _save(client, hired.pk, "identity", {"clan_name": "Шинэ"}, loaded=loaded, resolve={"clan_name": "mine"})
    assert response.json()["ok"] is True
    hired.refresh_from_db()
    assert hired.clan_name == "Шинэ"


def test_blank_required_field_outside_the_section_does_not_block(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    loaded = _identity_loaded(client, hired.pk)
    Employee.objects.filter(pk=hired.pk).update(work_phone="")  # old data: required, but not in the section
    response = _save(client, hired.pk, "identity", {"clan_name": "Ботгон"}, loaded=loaded)
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_unknown_section_is_404(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    response = _save(client, hired.pk, "nope", {"clan_name": "Ботгон"}, loaded=_identity_loaded(client, hired.pk))
    assert response.status_code == 404


def test_unknown_pk_is_404(hr_user: User) -> None:
    assert _save(_client(hr_user), 999999, "identity", {"clan_name": "Ботгон"}, loaded="{}").status_code == 404


def test_without_the_personal_right_is_403(hired: Employee) -> None:
    accountant = User.objects.create_user("employee_personal_write_acc", password=PASSWORD)
    accountant.groups.add(Group.objects.get_or_create(name=roles.ACCOUNTANT)[0])  # no personal right
    response = _save(_client(accountant), hired.pk, "identity", {"clan_name": "Ботгон"}, loaded="{}")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    hired.refresh_from_db()
    assert hired.clan_name != "Ботгон"


def test_viewer_who_cannot_manage_is_403_and_gets_no_loaded(hired: Employee) -> None:
    reader = User.objects.create_user("employee_personal_write_reader", password=PASSWORD)
    reader.user_permissions.add(
        Permission.objects.get(content_type__app_label="macs", codename="view_personal"),
        Permission.objects.get(content_type__app_label="macs", codename="view_employees"),
    )
    client = _client(reader)
    assert _save(client, hired.pk, "identity", {"clan_name": "Ботгон"}, loaded="").status_code == 403
    assert _identity_loaded(client, hired.pk) == ""  # read-only section: no snapshot to post back


def test_manage_without_view_personal_is_403_and_writes_nothing(hired: Employee) -> None:
    """The AND rule: the section needs both the manage and the personal right, so manage alone is refused."""
    manager = User.objects.create_user("employee_personal_write_manage_only", password=PASSWORD)
    manager.user_permissions.add(
        Permission.objects.get(content_type__app_label="macs", codename="manage_employees"),
        Permission.objects.get(content_type__app_label="macs", codename="view_employees"),
    )
    response = _save(_client(manager), hired.pk, "identity", {"clan_name": "Ботгон"}, loaded="{}")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    hired.refresh_from_db()
    assert hired.clan_name != "Ботгон"


def test_section_save_without_loaded_is_400_and_writes_nothing(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    body = {"values": {"clan_name": "Ботгон"}}  # no `loaded` key at all
    response = client.post(
        f"/api/v1/employees/{hired.pk}/personal/sections/identity",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["field_errors"]["loaded"]
    hired.refresh_from_db()
    assert hired.clan_name != "Ботгон"


def test_section_save_with_empty_loaded_is_400_with_form_errors(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    response = _save(client, hired.pk, "identity", {"clan_name": "Ботгон"}, loaded="")
    assert response.status_code == 400
    assert response.json()["form_errors"] == ["Хуудсыг дахин ачаалж, дахин оролдоно уу."]
    hired.refresh_from_db()
    assert hired.clan_name != "Ботгон"


def test_personal_section_loaded_holds_the_section_field_names(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json()
    for section in body["sections"]:
        loaded = json.loads(section["loaded"])
        assert isinstance(loaded, dict)
        assert set(sections.SECTIONS[section["name"]]) <= set(loaded)
