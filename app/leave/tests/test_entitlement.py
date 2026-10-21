from datetime import date

import pytest
from accounts.models import User
from employees.services import events

from leave.models import AnnualLeaveRule
from leave.services import entitlement
from leave.tests.conftest import make_employee

pytestmark = pytest.mark.django_db


def test_year_starts_are_anniversaries(actor: User) -> None:
    e = make_employee(actor, hired=date(2024, 3, 1))
    assert entitlement.year_starts(e, date(2026, 10, 14)) == [date(2024, 3, 1), date(2025, 3, 1), date(2026, 3, 1)]
    assert entitlement.year_start_for(e, date(2026, 2, 28)) == date(2025, 3, 1)


def test_feb_29_hire(actor: User) -> None:
    e = make_employee(actor, hired=date(2024, 2, 29))
    assert entitlement.year_starts(e, date(2025, 3, 1)) == [date(2024, 2, 29), date(2025, 2, 28)]


def test_not_yet_hired_has_no_years(actor: User) -> None:
    e = make_employee(actor, hired=date(2027, 1, 10))
    assert entitlement.year_starts(e, date(2026, 10, 14)) == []


def test_base_only_under_five_years(actor: User) -> None:
    e = make_employee(actor, hired=date(2024, 3, 1))
    ent = entitlement.entitled(e, date(2026, 3, 1))
    assert ent.days == 15
    assert type(ent.days) is int
    assert ent.breakdown == "15 (2 жил 0 сар ажилласан)"


@pytest.mark.parametrize(("prior", "expected"), [(36, 15), (37, 18), (96, 18), (97, 20), (349, 29)])
def test_brackets_with_prior_service(actor: User, prior: int, expected: int) -> None:
    # hired 2024-03-01, year starting 2026-03-01 adds 24 months at this company
    e = make_employee(actor, hired=date(2024, 3, 1), prior_months=prior)
    assert entitlement.entitled(e, date(2026, 3, 1)).days == expected


def test_breakdown_with_extra(actor: User) -> None:
    e = make_employee(actor, hired=date(2024, 3, 1), prior_months=60)
    assert entitlement.entitled(e, date(2026, 3, 1)).breakdown == "15 + 3 (7 жил 0 сар ажилласан)"


def test_childcare_leave_is_not_service(actor: User) -> None:
    e = make_employee(actor, hired=date(2020, 3, 1))
    events.record(
        e,
        type="leave_start",
        effective=date(2022, 3, 1),
        changes={},
        salary=None,
        reason="childcare",
        note="",
        by=actor,
    )
    events.record(
        e,
        type="leave_return",
        effective=date(2023, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert entitlement.service_months(e, date(2026, 3, 1)) == 72 - 12  # 6 years minus 1 year childcare


def test_rule_selected_by_effective_date(actor: User) -> None:
    AnnualLeaveRule.objects.create(
        effective_from=date(2027, 1, 1),
        base_days=16,
        base_days_minor_or_disabled=20,
        brackets=[{"from_month": 61, "extra_days": 3}],
    )
    e = make_employee(actor, hired=date(2024, 3, 1))
    assert entitlement.entitled(e, date(2026, 3, 1)).days == 15
    assert entitlement.entitled(e, date(2027, 3, 1)).days == 16


def test_eligible_from(actor: User) -> None:
    e = make_employee(actor, hired=date(2026, 1, 31))
    assert entitlement.eligible_from(e) == date(2026, 7, 31)


def test_rule_for_before_first_rule_uses_earliest() -> None:
    from datetime import date

    from leave.models import AnnualLeaveRule
    from leave.services import entitlement

    first = AnnualLeaveRule.objects.order_by("effective_from").first()
    assert first is not None
    assert entitlement.rule_for(date(2015, 1, 1)) == first
