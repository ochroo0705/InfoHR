import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from macs.models import LeaveTypeRow

from leave.models import LeaveSettings, LeaveTypeExt, Step

pytestmark = pytest.mark.django_db


def test_staff_may_request_defaults_on() -> None:
    row = LeaveTypeRow.objects.create(name="Хувийн чөлөө")
    ext = LeaveTypeExt.objects.create(leave_type=row)
    ext.refresh_from_db()
    assert ext.staff_may_request is True


def test_settings_steps() -> None:
    settings_row = LeaveSettings.get()
    assert settings_row.approval_on is False
    assert settings_row.steps() == []

    group = Group.objects.create(name="Нягтлан бодогч")
    settings_row.approval1_group = group
    settings_row.save()
    assert settings_row.approval_on is True
    assert settings_row.steps() == [Step(group.pk, False)]

    settings_row.approval2_manager = True
    settings_row.save()
    assert settings_row.steps() == [Step(group.pk, False), Step(None, True)]


def test_step2_without_step1_gives_no_steps() -> None:
    settings_row = LeaveSettings.get()
    settings_row.approval2_manager = True
    settings_row.save()
    assert settings_row.approval_on is False
    assert settings_row.steps() == []


def test_deleting_group_nulls_step() -> None:
    group = Group.objects.create(name="Захирал")
    settings_row = LeaveSettings.get()
    settings_row.approval1_group = group
    settings_row.save()

    group.delete()
    settings_row.refresh_from_db()
    assert settings_row.approval1_group is None


def test_employee_group_has_request_right() -> None:
    employee_group = Group.objects.get(name="Employee")
    assert employee_group.permissions.filter(content_type__app_label="leave", codename="request_own_leave").exists()
    user = User.objects.create_user("plain_staff", password="x-long-pass-123")  # noqa: S106
    user.groups.add(employee_group)
    user = User.objects.get(pk=user.pk)
    assert user.has_perm("leave.request_own_leave")
    assert Permission.objects.filter(codename="request_own_leave").count() == 1
