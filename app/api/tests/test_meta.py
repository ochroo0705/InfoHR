import secrets

import pytest
from accounts import modules
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from employees.models import CompanySettings

pytestmark = pytest.mark.django_db

PASSWORD = secrets.token_urlsafe(16)
SLOT_PERM = "employees.manage_position_slots"
AUDIT_PERM = "accounts.view_audit"


def _perm(app_label: str, codename: str) -> Permission:
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


@pytest.fixture(autouse=True)
def _fresh_module_cache() -> object:
    modules.clear_cache()
    yield
    modules.clear_cache()


@pytest.fixture
def user(db: None) -> User:
    user = User.objects.create_user("meta-user", password=PASSWORD, last_name="Бат", first_name="Эрдэнэ")
    user.user_permissions.add(_perm("accounts", "view_audit"), _perm("employees", "manage_position_slots"))
    return user


def test_meta_anonymous(client: Client) -> None:
    response = client.get("/api/v1/meta")

    assert response.status_code == 200
    body = response.json()
    assert body["user"] is None
    assert body["api_version"] == 1
    assert "csrf" in body
    assert body["backend_version"] == "dev"


def test_meta_signed_in(client: Client, user: User) -> None:
    client.force_login(user)

    body = client.get("/api/v1/meta").json()

    assert body["user"]["username"] == "meta-user"
    assert body["user"]["full_name"] == "Бат Эрдэнэ"
    assert body["user"]["must_change_password"] is False
    assert AUDIT_PERM in body["user"]["perms"]
    assert body["user"]["perms"] == sorted(body["user"]["perms"])


def test_meta_module_off(client: Client, user: User) -> None:
    client.force_login(user)
    modules.set_state({"slots": False})

    body = client.get("/api/v1/meta").json()

    assert body["modules"]["slots"] is False
    assert body["modules"]["recruitment"] is True
    assert SLOT_PERM not in body["user"]["perms"]
    assert AUDIT_PERM in body["user"]["perms"]


def test_meta_no_company_row(client: Client) -> None:
    assert not CompanySettings.objects.filter(pk=1).exists()

    body = client.get("/api/v1/meta").json()

    assert body["company"] == {"name": "", "logo_url": None}
    assert not CompanySettings.objects.filter(pk=1).exists()


def test_meta_reachable_when_forced(client: Client, user: User) -> None:
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])
    client.force_login(user)

    response = client.get("/api/v1/meta")

    assert response.status_code == 200
    assert response.json()["user"]["must_change_password"] is True
