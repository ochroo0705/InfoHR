"""System log: password changes/resets and user, group and permission changes are recorded.

Design: docs/superpowers/specs/2026-10-29-audit-logs-design.md §5.3a.
"""

from collections.abc import Iterator

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext

from accounts import audit_context
from accounts.models import SystemLogEntry, User
from accounts.roles import EMPLOYEE, HR

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    audit_context.clear_context()
    yield
    audit_context.clear_context()


@pytest.fixture
def root() -> User:
    return User.objects.create_superuser("audit_root", password="Root-pass-1")  # noqa: S106


@pytest.fixture
def admin_client(client: Client, root: User) -> Client:
    client.force_login(root)
    return client


def _change_data(user: User, **override: object) -> dict[str, object]:
    data: dict[str, object] = {
        "username": user.username,
        "is_active": "on",
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
    }
    data.update(override)
    return {k: v for k, v in data.items() if v is not None}


def _entries(action: str) -> list[SystemLogEntry]:
    return list(SystemLogEntry.objects.filter(action=action).order_by("id"))


def test_adding_user_to_hr_group_is_logged_with_admin_actor(admin_client: Client, root: User) -> None:
    hr, _ = Group.objects.get_or_create(name=HR)
    staff = User.objects.create_user("audit_staff", password="Staff-pass-1")  # noqa: S106

    response = admin_client.post(
        f"/admin/accounts/user/{staff.pk}/change/",
        _change_data(staff, groups=[hr.pk]),
    )

    assert response.status_code == 302
    # The form also drops the default Employee role (a second groups_changed line), so pick the HR add.
    entry = SystemLogEntry.objects.get(action="groups_changed", target_label="audit_staff", message=f"Нэмсэн: {HR}")
    assert entry.actor == root and entry.actor_name == root.username
    assert entry.target_type == "user"


def test_making_user_inactive_records_old_and_new(admin_client: Client) -> None:
    staff = User.objects.create_user("audit_inactive", password="Staff-pass-1")  # noqa: S106

    admin_client.post(f"/admin/accounts/user/{staff.pk}/change/", _change_data(staff, is_active=None))

    entry = SystemLogEntry.objects.get(action="user_active_changed", target_label="audit_inactive")
    assert entry.message == "Идэвхтэй"
    assert entry.changes == [{"field": "Идэвхтэй", "old": "Тийм", "new": "Үгүй"}]


def test_adding_permission_to_role_group_is_logged(root: User) -> None:
    hr, _ = Group.objects.get_or_create(name=HR)
    audit_context.set_context(root, "10.0.0.7")
    permission = Permission.objects.get(codename="view_audit")

    hr.permissions.add(permission)

    entry = SystemLogEntry.objects.get(action="permissions_changed", target_type="role", target_label=HR)
    assert "view_audit" in entry.message and entry.actor == root and entry.ip == "10.0.0.7"


def test_creating_user_records_login_created(admin_client: Client) -> None:
    admin_client.post("/admin/accounts/user/add/", {"username": "audit_new"})

    entry = SystemLogEntry.objects.get(action="login_created", target_label="audit_new")
    assert entry.target_type == "user"


def test_own_password_change_is_logged_without_password_text(client: Client) -> None:
    user = User.objects.create_user("audit_self", password="Old-pass-1")  # noqa: S106
    client.force_login(user)

    response = client.post(
        "/password/change/",
        {"old_password": "Old-pass-1", "new_password1": "New-pass-2x", "new_password2": "New-pass-2x"},
    )

    assert response.status_code == 302
    entry = SystemLogEntry.objects.get(action="password_changed")
    assert entry.actor == user and entry.target_label == "audit_self"
    assert entry.message == "" and entry.changes == []
    assert "New-pass-2x" not in entry.target_label and "Old-pass-1" not in entry.target_label


def test_admin_password_reset_is_logged_with_target_user(admin_client: Client, root: User) -> None:
    user = User.objects.create_user("audit_reset", password="Old-pass-1")  # noqa: S106

    admin_client.post(f"/admin/accounts/user/{user.pk}/password/")

    entry = SystemLogEntry.objects.get(action="password_reset")
    assert entry.actor == root and entry.target_type == "user" and entry.target_label == "audit_reset"


def test_rolled_back_change_leaves_no_line(root: User) -> None:
    hr, _ = Group.objects.get_or_create(name=HR)
    staff = User.objects.create_user("audit_rolled", password="Staff-pass-1")  # noqa: S106
    audit_context.set_context(root, None)

    with pytest.raises(RuntimeError), transaction.atomic():
        staff.groups.add(hr)
        raise RuntimeError("rollback")

    assert not SystemLogEntry.objects.filter(action="groups_changed", target_label="audit_rolled").exists()
    assert not staff.groups.filter(pk=hr.pk).exists()


def test_log_failure_blocks_role_change(monkeypatch: pytest.MonkeyPatch, root: User) -> None:
    hr, _ = Group.objects.get_or_create(name=HR)
    staff = User.objects.create_user("audit_blocked", password="Staff-pass-1")  # noqa: S106
    audit_context.set_context(root, None)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(SystemLogEntry.objects, "create", boom)

    with pytest.raises(RuntimeError), transaction.atomic():
        staff.groups.add(hr)

    assert not staff.groups.filter(pk=hr.pk).exists()


def test_admin_staff_flag_change_is_logged_as_staff_changed(admin_client: Client) -> None:
    staff = User.objects.create_user("audit_staffflag", password="Staff-pass-1")  # noqa: S106

    admin_client.post(f"/admin/accounts/user/{staff.pk}/change/", _change_data(staff, is_staff="on"))

    entry = SystemLogEntry.objects.get(action="staff_changed", target_label="audit_staffflag")
    assert entry.changes == [{"field": "Удирдлагын хэсэг", "old": "Үгүй", "new": "Тийм"}]
    assert not SystemLogEntry.objects.filter(action="permissions_changed", target_label="audit_staffflag").exists()


def test_fresh_user_gets_no_employee_line_but_later_group_is_logged_once(root: User) -> None:
    hr, _ = Group.objects.get_or_create(name=HR)
    audit_context.set_context(root, None)

    staff = User.objects.create_user("audit_fresh", password="Staff-pass-1")  # noqa: S106
    assert not SystemLogEntry.objects.filter(action="groups_changed", target_label="audit_fresh").exists()
    assert SystemLogEntry.objects.filter(action="login_created", target_label="audit_fresh").count() == 1

    staff.groups.add(hr)

    lines = SystemLogEntry.objects.filter(action="groups_changed", target_label="audit_fresh")
    assert [e.message for e in lines] == [f"Нэмсэн: {HR}"]
    assert staff.groups.filter(name=EMPLOYEE).exists()  # the automatic role itself is still given


def test_employee_role_removal_is_logged_for_existing_user(root: User) -> None:
    staff = User.objects.create_user("audit_emp_drop", password="Staff-pass-1")  # noqa: S106
    audit_context.set_context(root, None)

    staff.groups.clear()

    entry = SystemLogEntry.objects.get(action="groups_changed", target_label="audit_emp_drop")
    assert entry.message == f"Хассан: {EMPLOYEE}"


def test_login_style_save_skips_snapshot_query(root: User) -> None:
    user = User.objects.create_user("audit_lastlogin", password="Staff-pass-1")  # noqa: S106

    with CaptureQueriesContext(connection) as skipped:
        user.save(update_fields=["last_login"])
    with CaptureQueriesContext(connection) as watched:
        user.save(update_fields=["is_active"])

    assert len(skipped) == 1  # the UPDATE only
    assert len(watched) == 2  # snapshot SELECT plus UPDATE


def test_reverse_user_set_add_logs_each_user(root: User) -> None:
    group = Group.objects.create(name="Audit reverse")
    staff = User.objects.create_user("audit_rev_user", password="Staff-pass-1")  # noqa: S106
    audit_context.set_context(root, None)

    group.user_set.add(staff)

    entry = SystemLogEntry.objects.get(action="groups_changed", target_label="audit_rev_user")
    assert entry.message == "Нэмсэн: Audit reverse" and entry.target_type == "user"


def test_reverse_permission_group_set_add_logs_role(root: User) -> None:
    group = Group.objects.create(name="Audit perm role")
    permission = Permission.objects.get(codename="view_audit")
    audit_context.set_context(root, None)

    permission.group_set.add(group)

    entry = SystemLogEntry.objects.get(action="permissions_changed", target_type="role", target_label="Audit perm role")
    assert entry.message == "Нэмсэн: view_audit"


def test_group_permissions_clear_logs_removed_names(root: User) -> None:
    group = Group.objects.create(name="Audit cleared")
    group.permissions.add(*Permission.objects.filter(codename__in=["view_audit", "export_lists"]))
    audit_context.set_context(root, None)

    group.permissions.clear()

    entry = SystemLogEntry.objects.get(
        action="permissions_changed", target_label="Audit cleared", message__startswith="Хассан"
    )
    assert entry.message == "Хассан: export_lists, view_audit" and entry.target_type == "role"


def test_user_groups_clear_logs_removed_names_for_user(root: User) -> None:
    hr, _ = Group.objects.get_or_create(name=HR)
    staff = User.objects.create_user("audit_clear_user", password="Staff-pass-1")  # noqa: S106
    staff.groups.add(hr)
    audit_context.set_context(root, None)

    staff.groups.clear()

    entry = SystemLogEntry.objects.get(
        action="groups_changed", target_label="audit_clear_user", message__startswith="Хассан"
    )
    assert entry.message == f"Хассан: {EMPLOYEE}, {HR}"
