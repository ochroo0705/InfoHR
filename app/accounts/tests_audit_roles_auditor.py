"""The Auditor role: sees the system log only, no export, no employee data (decided by the user 2026-10-29)."""

import importlib
from types import ModuleType

import pytest
from django.apps import apps
from django.contrib.auth.models import Group
from django.test import Client

from accounts.models import User
from accounts.roles import (
    ACCOUNTANT,
    ADMIN,
    AUDITOR,
    DEFAULT_EMPLOYEE_PERMS,
    DEFAULT_LEAVE_PERMS,
    DEFAULT_LIST_PERMS,
    DEFAULT_REPORT_PERMS,
    DEFAULT_SWITCHES,
    EMPLOYEE,
    HR,
)

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
MIGRATION = "accounts.migrations.0009_auditor_role"


def _migration() -> ModuleType:
    return importlib.import_module(MIGRATION)


def _perm_keys(group_name: str) -> set[tuple[str, str]]:
    group = Group.objects.get(name=group_name)
    return {(p.content_type.app_label, p.codename) for p in group.permissions.select_related("content_type")}


def _auditor(name: str = "auditor_user") -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=AUDITOR))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def test_auditor_group_has_exactly_view_audit() -> None:
    assert _perm_keys(AUDITOR) == {("accounts", "view_audit")}


def test_auditor_has_no_export_and_no_employee_rights() -> None:
    user = _auditor()
    assert user.has_perm("accounts.view_audit")
    assert not user.has_perm("accounts.export_lists")
    assert not user.has_perm("macs.view_employees")
    assert not user.has_perm("macs.view_salary")
    assert not user.has_perm("leave.view_leave")
    assert not user.has_perm("reports.view_reports")
    assert not user.has_perm("lists.manage_lists")


def test_only_admin_and_auditor_hold_view_audit() -> None:
    assert ("accounts", "view_audit") in _perm_keys(ADMIN)
    assert ("accounts", "view_audit") in _perm_keys(AUDITOR)
    for name in (HR, ACCOUNTANT, EMPLOYEE):
        assert ("accounts", "view_audit") not in _perm_keys(name)


def test_role_dicts_list_the_auditor() -> None:
    assert DEFAULT_SWITCHES[AUDITOR] == ("view_audit",)
    for defaults in (DEFAULT_EMPLOYEE_PERMS, DEFAULT_LIST_PERMS, DEFAULT_REPORT_PERMS, DEFAULT_LEAVE_PERMS):
        assert defaults[AUDITOR] == ()


def test_migration_forward_is_idempotent_and_keeps_the_group() -> None:
    group_id = Group.objects.get(name=AUDITOR).pk
    _migration().grant_auditor(apps, None)
    _migration().grant_auditor(apps, None)
    assert Group.objects.filter(name=AUDITOR).count() == 1
    assert Group.objects.get(name=AUDITOR).pk == group_id
    assert _perm_keys(AUDITOR) == {("accounts", "view_audit")}


def test_migration_reverse_keeps_group_with_users_and_deletes_empty_group() -> None:
    migration = _migration()
    user = _auditor("auditor_keeps_group")
    migration.revoke_auditor(apps, None)
    assert Group.objects.filter(name=AUDITOR).exists()
    assert not user.has_perm("accounts.view_audit")  # the grant is gone from the group

    user.groups.clear()
    migration.revoke_auditor(apps, None)
    assert not Group.objects.filter(name=AUDITOR).exists()


def test_landing_page_goes_to_system_log_for_auditor() -> None:
    response = _client(_auditor()).get("/")
    assert response.status_code == 302
    assert response["Location"] == "/logs/system/"


def test_landing_page_goes_to_today_for_hr() -> None:
    user = User.objects.create_user("auditor_hr_user", password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=HR))
    response = _client(User.objects.get(pk=user.pk)).get("/")
    assert response.status_code == 302
    assert response["Location"] == "/employees/today/"


def test_landing_page_goes_to_today_for_admin() -> None:
    user = User.objects.create_user("auditor_admin_user", password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=ADMIN))
    response = _client(User.objects.get(pk=user.pk)).get("/")
    assert response["Location"] == "/employees/today/"
