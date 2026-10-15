from decimal import Decimal

import pytest
from django.contrib.auth.models import Group

from leave.models import AnnualLeaveRule, LeaveType

pytestmark = pytest.mark.django_db


def test_seeded_leave_types() -> None:
    codes = list(LeaveType.objects.order_by("order").values_list("code", flat=True))
    assert codes == ["annual", "sick", "unpaid", "personal", "other"]
    annual = LeaveType.objects.get(code=LeaveType.ANNUAL)
    assert annual.uses_annual_balance and annual.is_paid
    assert not LeaveType.objects.get(code="sick").uses_annual_balance


def test_seeded_rule_matches_law() -> None:
    rule = AnnualLeaveRule.objects.get()
    assert str(rule.effective_from) == "2022-01-01"
    assert rule.base_days == Decimal("15")
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
    assert codes("HR") == full
    assert codes("Accountant") == {"view_leave"}
