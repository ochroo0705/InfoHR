from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from macs.models import LeaveTypeRow

from leave.models import AnnualLeaveRule, GrantKind
from leave.services import calendar, entitlement, ledger, records, rows
from leave.services.records import Draft
from leave.tests.conftest import make_employee
from leave.tests.test_views import _in_group, _post

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)


def d(e: Employee, t: LeaveTypeRow, s: date, end: date, **kw: Any) -> Draft:
    return Draft(employee=e, leave_type=t, start_date=s, end_date=end, **kw)


# 1. Feb 29 hire: the next leave year starts on the anniversary, not add_months(year_start, 12)
def test_next_year_start_follows_anniversary_for_feb_29(actor: User) -> None:
    e = make_employee(actor, hired=date(2024, 2, 29))
    assert entitlement.next_year_start(e, date(2027, 2, 28)) == date(2028, 2, 29)
    assert entitlement.next_year_start(e, date(2025, 2, 28)) == date(2026, 2, 28)


def test_carry_over_from_feb_28_lands_on_feb_29(
    actor: User, annual: LeaveTypeRow, grants_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: date(2027, 3, 1))
    e = make_employee(actor, hired=date(2024, 2, 29))
    ledger.ensure_grants(e, date(2027, 3, 1))
    ledger.carry_over(e, date(2027, 2, 28), date(2028, 2, 28), 2, "x", actor)
    carried = [g for g in rows.grants(e.pk) if g.kind == GrantKind.CARRY_OVER]
    assert [g.start for g in carried] == [date(2028, 2, 29)]
    assert ledger.periods(e, date(2027, 3, 1))[0][0].start == date(2028, 2, 29)


def test_year_boundary_check_uses_feb_29(
    actor: User, annual: LeaveTypeRow, grants_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2028-02-28 is still inside the 2027-02-28 leave year; add_months would have wrongly split it
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: date(2027, 3, 1))
    e = make_employee(actor, hired=date(2024, 2, 29))
    c = records.check(d(e, annual, date(2027, 2, 28), date(2028, 2, 28)), date(2027, 3, 1))
    assert not any("хил давсан" in err for err in c.errors)


# 2. under 18 or disabled: base_days_minor_or_disabled
def test_minor_gets_minor_base(actor: User) -> None:
    e = make_employee(actor, hired=date(2024, 3, 1))
    e.birth_date = date(2008, 3, 2)  # 17 on 2026-03-01 ... turns 18 after that
    e.save(update_fields=["birth_date"])
    ent = entitlement.entitled(e, date(2026, 3, 1))
    assert ent.days == 20
    assert "18-аас доош" in ent.breakdown


def test_adult_on_year_start_gets_base(actor: User) -> None:
    e = make_employee(actor, hired=date(2024, 3, 1))
    e.birth_date = date(2008, 3, 1)  # exactly 18 on the year start
    e.save(update_fields=["birth_date"])
    assert entitlement.entitled(e, date(2026, 3, 1)).days == 15


def test_disabled_employee_gets_minor_base(actor: User) -> None:
    e = make_employee(actor, hired=date(2024, 3, 1))
    e.has_disability = True
    e.save(update_fields=["has_disability"])
    ent = entitlement.entitled(e, date(2026, 3, 1))
    assert ent.days == 20
    assert "хөгжлийн бэрхшээлтэй" in ent.breakdown


# 3. annual overlapping annual is an error; other overlaps stay warnings
def test_annual_overlap_with_recorded_annual_is_error(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), actor, TODAY)
    c = records.check(d(employee, annual, date(2026, 11, 10), date(2026, 11, 11)), TODAY)
    assert any("өөр чөлөө" in err for err in c.errors)
    assert not any("өөр чөлөө" in w for w in c.warnings)


def test_non_annual_overlap_stays_warning(
    employee: Employee, annual: LeaveTypeRow, sick: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), actor, TODAY)
    c = records.check(d(employee, sick, date(2026, 11, 10), date(2026, 11, 11)), TODAY)
    assert any("өөр чөлөө" in w for w in c.warnings)
    assert not c.errors


# 5. eligibility text comes from the rule
def test_eligibility_warning_uses_rule_months(actor: User, annual: LeaveTypeRow) -> None:
    AnnualLeaveRule.objects.update(eligibility_months=3)
    e = make_employee(actor, hired=date(2026, 9, 1), register_no="УБ66112299")
    c = records.check(d(e, annual, date(2026, 11, 2), date(2026, 11, 3)), TODAY)
    assert any("3 сар болоогүй" in w for w in c.warnings)


# 6. leave_check uses the employee of the leave being edited
def test_check_uses_employee_of_edited_leave(
    actor: User, annual: LeaveTypeRow, grants_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = make_employee(actor, hired=date(2024, 3, 1))
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ77112233")
    leave = records.record(d(owner, annual, date(2026, 11, 2), date(2026, 11, 3)), actor, TODAY)
    seen: list[int] = []
    real = records.check

    def spy(draft: Draft, today: date) -> records.Check:
        seen.append(draft.employee.pk)
        return real(draft, today)

    monkeypatch.setattr("leave.services.records.check", spy)
    monkeypatch.setattr("leave.views.today", lambda: TODAY)
    c = Client()
    c.force_login(_in_group("HR"))
    c.post(reverse("leave:check"), _post(other, annual, leave_id=str(leave.pk)))
    assert seen == [owner.pk]


def test_check_ignores_unknown_leave_id(actor: User, annual: LeaveTypeRow, monkeypatch: pytest.MonkeyPatch) -> None:
    posted = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ77112244")
    seen: list[int] = []
    real = records.check

    def spy(draft: Draft, today: date) -> records.Check:
        seen.append(draft.employee.pk)
        return real(draft, today)

    monkeypatch.setattr("leave.services.records.check", spy)
    monkeypatch.setattr("leave.views.today", lambda: TODAY)
    c = Client()
    c.force_login(_in_group("HR"))
    resp = c.post(reverse("leave:check"), _post(posted, annual, leave_id="999999"))
    assert resp.status_code == 200
    assert seen == [posted.pk]


# 7. length cap runs before the working-day count
def test_leave_longer_than_a_year_is_refused(
    employee: Employee, annual: LeaveTypeRow, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> int:
        raise AssertionError("working_days must not run for an over-long leave")

    monkeypatch.setattr(calendar, "working_days", boom)
    c = records.check(d(employee, annual, date(2026, 1, 5), date(2027, 1, 7)), TODAY)  # 367 days
    assert c.errors == ["Чөлөө 1 жилээс урт байж болохгүй."]
    assert c.working_days == 0
