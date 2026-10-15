from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from employees.models import Employee

from leave.models import GrantKind, Leave, LeaveGrant, LeaveType
from leave.services import ledger
from leave.tests.conftest import make_employee

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)


def _leave(e: Employee, t: LeaveType, start: date, end: date, days: str, year: date | None) -> Leave:
    return Leave.objects.create(
        employee=e, leave_type=t, start_date=start, end_date=end, working_days=Decimal(days), year_start=year
    )


def test_ensure_grants_creates_one_per_year_and_is_idempotent(employee: Employee) -> None:
    ledger.ensure_grants(employee, TODAY)
    ledger.ensure_grants(employee, TODAY)
    years = list(LeaveGrant.objects.filter(employee=employee, kind=GrantKind.AUTO).values_list("year_start", flat=True))
    assert sorted(years) == [date(2024, 3, 1), date(2025, 3, 1), date(2026, 3, 1)]


def test_new_hire_gets_current_year_only(actor: User) -> None:
    e = make_employee(actor, hired=date(2026, 9, 1), register_no="УБ88112233")
    ledger.ensure_grants(e, TODAY)
    assert LeaveGrant.objects.filter(employee=e).count() == 1


def test_future_hire_gets_nothing(actor: User) -> None:
    e = make_employee(actor, hired=date(2027, 1, 1), register_no="УБ77112233")
    ledger.ensure_grants(e, TODAY)
    assert not LeaveGrant.objects.filter(employee=e).exists()


def test_balance_counts_recorded_annual_only(employee: Employee, annual: LeaveType) -> None:
    ledger.ensure_grants(employee, TODAY)
    y = date(2026, 3, 1)
    _leave(employee, annual, date(2026, 4, 6), date(2026, 4, 10), "5", y)
    cancelled = _leave(employee, annual, date(2026, 5, 4), date(2026, 5, 4), "1", y)
    cancelled.status = "cancelled"
    cancelled.save()
    _leave(employee, LeaveType.objects.get(code="sick"), date(2026, 6, 1), date(2026, 6, 2), "2", None)
    assert ledger.balance(employee, y) == Decimal(10)


def test_summaries_newest_first(employee: Employee, annual: LeaveType) -> None:
    _leave(employee, annual, date(2026, 4, 6), date(2026, 4, 10), "5", date(2026, 3, 1))
    s = ledger.summaries(employee, TODAY)
    assert [x.year_start for x in s] == [date(2026, 3, 1), date(2025, 3, 1), date(2024, 3, 1)]
    assert (s[0].granted, s[0].taken, s[0].left, s[0].year_end) == (
        Decimal(15),
        Decimal(5),
        Decimal(10),
        date(2027, 2, 28),
    )


def test_adjust_requires_reason_and_logs(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    with pytest.raises(ledger.LedgerError):
        ledger.adjust(employee, date(2026, 3, 1), Decimal(2), " ", actor)
    ledger.adjust(employee, date(2026, 3, 1), Decimal(-2), "Өмнө авсан", actor)
    assert ledger.balance(employee, date(2026, 3, 1)) == Decimal(13)
    assert employee.activity.filter(message__contains="Амралтын эрх").exists()


def test_carry_over_moves_days(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    ledger.carry_over(employee, date(2025, 3, 1), Decimal(4), "Ажлын шаардлагаар", actor)
    assert ledger.balance(employee, date(2025, 3, 1)) == Decimal(11)
    assert ledger.balance(employee, date(2026, 3, 1)) == Decimal(19)


def test_carry_over_cannot_exceed_balance(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    with pytest.raises(ledger.LedgerError):
        ledger.carry_over(employee, date(2025, 3, 1), Decimal(16), "x", actor)


def test_existing_auto_grant_not_rewritten_by_new_rule(employee: Employee) -> None:
    from leave.models import AnnualLeaveRule

    ledger.ensure_grants(employee, TODAY)
    AnnualLeaveRule.objects.create(
        effective_from=date(2026, 1, 1), base_days=Decimal(20), base_days_minor_or_disabled=Decimal(20), brackets=[]
    )
    ledger.ensure_grants(employee, TODAY)
    assert ledger.balance(employee, date(2026, 3, 1)) == Decimal(15)


def test_carry_over_logs_activity(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    ledger.carry_over(employee, date(2025, 3, 1), Decimal(4), "Шалтгаан", actor)
    assert employee.activity.filter(message__contains="шилжүүлсэн").exists()


def test_adjust_rejects_non_leave_year(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    with pytest.raises(ledger.LedgerError):
        ledger.adjust(employee, date(2025, 6, 1), Decimal(1), "x", actor)


def test_adjust_zero_days_raises(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    with pytest.raises(ledger.LedgerError):
        ledger.adjust(employee, date(2026, 3, 1), Decimal(0), "x", actor)


def test_carry_over_rejects_non_leave_year(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    with pytest.raises(ledger.LedgerError):
        ledger.carry_over(employee, date(2023, 3, 1), Decimal(1), "x", actor)


def test_carry_from_current_year_shows_next_year(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    ledger.carry_over(employee, date(2026, 3, 1), Decimal(3), "x", actor)
    s = ledger.summaries(employee, TODAY)
    assert s[0].year_start == date(2027, 3, 1)
    assert s[0].granted == Decimal(3)
    assert s[0].year_end == date(2028, 2, 29)
    assert s[1].year_start == date(2026, 3, 1)


def test_leaver_gets_no_grant_for_year_after_leaving(actor: User) -> None:
    from employees.services import events

    from leave.tests.conftest import make_employee

    e = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ44112233")
    events.record(
        e,
        type="termination",
        effective=date(2025, 6, 1),
        changes={},
        salary=None,
        reason="resignation",
        note="",
        by=actor,
    )
    ledger.ensure_grants(e, date(2026, 10, 14))
    starts = sorted(LeaveGrant.objects.filter(employee=e).values_list("year_start", flat=True))
    assert starts == [date(2024, 3, 1), date(2025, 3, 1)]
    assert [s.year_start for s in ledger.summaries(e, date(2026, 10, 14))] == [date(2025, 3, 1), date(2024, 3, 1)]


def test_upcoming_year_can_be_adjusted_but_not_carried(employee: Employee, actor: User) -> None:
    ledger.ensure_grants(employee, TODAY)
    ledger.carry_over(employee, date(2026, 3, 1), Decimal(3), "x", actor)
    s = ledger.summaries(employee, TODAY)
    assert s[0].upcoming and not s[1].upcoming
    ledger.adjust(employee, date(2027, 3, 1), Decimal(-1), "буруу шилжүүлсэн", actor)
    assert ledger.summaries(employee, TODAY)[0].granted == Decimal(2)
    with pytest.raises(ledger.LedgerError):
        ledger.adjust(employee, date(2028, 3, 1), Decimal(1), "x", actor)
