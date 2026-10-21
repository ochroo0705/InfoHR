import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from macs.models import LeaveTypeRow

from leave.models import AnnualLeaveRule, LeaveSettings, LeaveTypeExt, type_ext

pytestmark = pytest.mark.django_db


def test_type_ext_defaults_when_missing() -> None:
    row = LeaveTypeRow.objects.create(name="Өвчний чөлөө")
    ext = type_ext(row)
    assert ext.uses_annual_balance is False
    assert not LeaveTypeExt.objects.exists()


def test_settings_default_off() -> None:
    assert LeaveSettings.get().auto_annual_grant is False
    assert LeaveSettings.objects.count() == 1


def test_permissions_kept() -> None:
    user = User.objects.create_user("hr_user", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    user = User.objects.get(pk=user.pk)
    assert user.has_perm("leave.record_leave")
    assert user.has_perm("leave.view_leave")
    assert not user.has_perm("leave.manage_leave_settings")  # leave settings are Admin only (user, 2026-10-19)


def test_rule_whole_days() -> None:
    rule = AnnualLeaveRule.objects.get()
    assert rule.base_days == 15
    assert rule.base_days_minor_or_disabled == 20


def test_seeded_rule_matches_law() -> None:
    rule = AnnualLeaveRule.objects.get()
    assert str(rule.effective_from) == "2022-01-01"
    assert rule.brackets == [
        {"from_month": 61, "extra_days": 3},
        {"from_month": 121, "extra_days": 5},
        {"from_month": 181, "extra_days": 7},
        {"from_month": 241, "extra_days": 9},
        {"from_month": 301, "extra_days": 11},
        {"from_month": 373, "extra_days": 14},
    ]
    assert rule.min_continuous_part == 10 and rule.eligibility_months == 6


def test_role_permissions() -> None:
    def codes(name: str) -> set[str]:
        return set(
            Group.objects.get(name=name)
            .permissions.filter(content_type__app_label="leave")
            .values_list("codename", flat=True)
        )

    full = {"view_leave", "record_leave", "manage_leave_settings"}
    assert codes("Admin") == full
    assert codes("HR") == {"view_leave", "record_leave"}
    assert codes("Accountant") == {"view_leave"}
