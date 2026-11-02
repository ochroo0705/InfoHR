"""AccessScope: per-user data scope row. Default is not limited; changes are written to the system log.

Design: docs/superpowers/specs/2026-10-29-data-scope-and-team-design.md §4.
"""

import re
from collections.abc import Iterator

import pytest
from django.test import Client
from django.urls import reverse
from employees.services.macs_writes import save_department
from employees.tests.helpers import make_branch

from accounts import audit_context
from accounts.models import AccessScope, SystemLogEntry, User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    audit_context.clear_context()
    yield
    audit_context.clear_context()


@pytest.fixture
def actor() -> User:
    return User.objects.create_user("scope_actor", password="x-long-pass-123")  # noqa: S106


def test_defaults() -> None:
    user = User.objects.create_user("scope_defaults", password="x-long-pass-123")  # noqa: S106

    scope = AccessScope.objects.create(user=user)
    scope.refresh_from_db()

    assert scope.limited is False
    assert scope.branch_ids == []
    assert scope.department_ids == []
    assert scope.include_sub_departments is True
    assert scope.own_team is False


def test_user_without_row_has_no_access_scope() -> None:
    user = User.objects.create_user("scope_none", password="x-long-pass-123")  # noqa: S106

    assert hasattr(user, "access_scope") is False


def test_change_is_logged(actor: User) -> None:
    user = User.objects.create_user("scope_changed", password="x-long-pass-123")  # noqa: S106
    scope = AccessScope.objects.create(user=user)
    audit_context.set_context(actor, None)

    scope.limited = True
    scope.save()

    entries = list(SystemLogEntry.objects.filter(action="setting_changed").order_by("id"))
    assert len(entries) == 1
    assert entries[0].category == "settings"
    assert entries[0].actor == actor


def test_user_page_loads_with_scope_block(client: Client) -> None:
    admin = User.objects.create_superuser("scope_root", password="Root-pass-1")  # noqa: S106
    client.force_login(admin)
    user = User.objects.create_user("scope_page", password="x-long-pass-123")  # noqa: S106

    response = client.get(reverse("admin:accounts_user_change", args=[user.pk]))

    assert response.status_code == 200
    assert "Үзэх хүрээ" in response.content.decode()


def test_save_stores_ints(client: Client) -> None:
    admin = User.objects.create_superuser("scope_root2", password="Root-pass-2")  # noqa: S106
    client.force_login(admin)
    user = User.objects.create_user("scope_save", password="x-long-pass-123")  # noqa: S106
    branch = make_branch("Төв салбар")
    department = save_department("Үйлдвэрлэл")

    response = client.post(
        reverse("admin:accounts_user_change", args=[user.pk]),
        {
            "username": user.username,
            "is_active": "on",
            "date_joined_0": "2026-01-01",
            "date_joined_1": "00:00:00",
            "access_scope-TOTAL_FORMS": "1",
            "access_scope-INITIAL_FORMS": "0",
            "access_scope-MIN_NUM_FORMS": "0",
            "access_scope-MAX_NUM_FORMS": "1",
            "access_scope-0-limited": "on",
            "access_scope-0-branch_ids": [str(branch.pk)],
            "access_scope-0-department_ids": [str(department.pk)],
            "access_scope-0-include_sub_departments": "on",
        },
    )

    assert response.status_code == 302
    scope = AccessScope.objects.get(user=user)
    assert scope.limited is True
    assert scope.branch_ids == [branch.pk]
    assert scope.department_ids == [department.pk]
    assert all(isinstance(value, int) for value in scope.branch_ids + scope.department_ids)


def _checked_values(html: str, name: str) -> set[str]:
    """Values of the checkbox inputs called `name` that carry the checked attribute."""
    checked: set[str] = set()
    for tag in re.findall(r"<input\b[^>]*>", html):
        if f'name="{name}"' not in tag or not re.search(r"\bchecked\b", tag):
            continue
        value = re.search(r'value="([^"]*)"', tag)
        if value:
            checked.add(value.group(1))
    return checked


def _user_post(user: User, **scope: object) -> dict[str, object]:
    """User change form as a browser sends it: the basic fields plus the «Үзэх хүрээ» block.
    include_sub_departments is sent as «on» because the form shows it ticked by default."""
    data: dict[str, object] = {
        "username": user.username,
        "is_active": "on",
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
        "access_scope-TOTAL_FORMS": "1",
        "access_scope-INITIAL_FORMS": "0",
        "access_scope-MIN_NUM_FORMS": "0",
        "access_scope-MAX_NUM_FORMS": "1",
        "access_scope-0-include_sub_departments": "on",
    }
    data.update({f"access_scope-0-{key}": value for key, value in scope.items()})
    return data


def test_crafted_unknown_branch_id_is_rejected(client: Client) -> None:
    admin = User.objects.create_superuser("scope_root4", password="Root-pass-4")  # noqa: S106
    client.force_login(admin)
    user = User.objects.create_user("scope_crafted", password="x-long-pass-123")  # noqa: S106
    url = reverse("admin:accounts_user_change", args=[user.pk])

    response = client.post(url, _user_post(user, limited="on", branch_ids="999999"))
    assert response.status_code == 200
    assert AccessScope.objects.filter(user=user).exists() is False

    response = client.post(url, _user_post(user, limited="on", branch_ids="abc"))
    assert response.status_code == 200
    assert AccessScope.objects.filter(user=user).exists() is False


def test_unchanged_save_creates_no_row(client: Client) -> None:
    admin = User.objects.create_superuser("scope_root5", password="Root-pass-5")  # noqa: S106
    client.force_login(admin)
    user = User.objects.create_user("scope_untouched", password="x-long-pass-123")  # noqa: S106

    response = client.post(reverse("admin:accounts_user_change", args=[user.pk]), _user_post(user))

    assert response.status_code == 302
    assert AccessScope.objects.filter(user=user).exists() is False


def test_existing_scope_is_preselected(client: Client) -> None:
    admin = User.objects.create_superuser("scope_root6", password="Root-pass-6")  # noqa: S106
    client.force_login(admin)
    user = User.objects.create_user("scope_preset", password="x-long-pass-123")  # noqa: S106
    branch = make_branch("Баруун салбар")
    department = save_department("Санхүү")
    AccessScope.objects.create(user=user, limited=True, branch_ids=[branch.pk], department_ids=[department.pk])

    response = client.get(reverse("admin:accounts_user_change", args=[user.pk]))
    html = response.content.decode()

    assert response.status_code == 200
    assert str(branch.pk) in _checked_values(html, "access_scope-0-branch_ids")
    assert str(department.pk) in _checked_values(html, "access_scope-0-department_ids")
