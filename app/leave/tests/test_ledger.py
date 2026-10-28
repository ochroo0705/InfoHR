from datetime import date

import pytest
from accounts.models import User
from employees.models import Employee
from macs.models import Entitlement, LeaveTypeRow

from leave.models import AnnualLeaveRule, GrantKind, LeaveSettings
from leave.services import ledger, rows, writes
from leave.services.rows import GrantRow, LeaveRow
from leave.tests.conftest import make_employee

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)


def _switch(on: bool) -> None:
    s = LeaveSettings.get()
    s.auto_annual_grant = on
    s.save()


def _old_grant(e: Employee, t: LeaveTypeRow, start: date, end: date, days: int) -> Entitlement:
    """A grant made by the old program: no ext row."""
    return Entitlement.objects.create(employee=e, leave_type=t, date1=start, date2=end, ent_days=days, comment="")


def _auto_starts(e: Employee) -> set[date]:
    return {g.start for g in rows.grants(e.pk) if g.kind == GrantKind.AUTO}


def _period(e: Employee, start: date) -> ledger.Period:
    found, _ = ledger.periods(e, TODAY)
    return next(p for p in found if p.start == start)


def _leave(e: Employee, t: LeaveTypeRow, start: date, end: date, days: int, actor: User) -> LeaveRow:
    assign = writes.record_assign(e, t, start, end, days, "", actor)
    return next(lv for lv in rows.leaves(employee_ids=[e.pk]) if lv.id == assign.pk)


def test_switch_off_creates_nothing(employee: Employee, annual: LeaveTypeRow) -> None:
    ledger.ensure_grants(employee, TODAY)
    assert not Entitlement.objects.filter(employee=employee).exists()


def test_switch_on_grants_current_year_only(employee: Employee, annual: LeaveTypeRow) -> None:
    _switch(True)
    ledger.ensure_grants(employee, TODAY)
    assert _auto_starts(employee) == {date(2026, 3, 1)}  # past years are never filled in
    assert {g.days for g in rows.grants(employee.pk)} == {15}


def test_switch_on_is_idempotent(employee: Employee, annual: LeaveTypeRow) -> None:
    _switch(True)
    ledger.ensure_grants(employee, TODAY)
    ledger.ensure_grants(employee, TODAY)
    assert len(rows.grants(employee.pk)) == 1


def test_switch_on_skips_year_covered_by_old_calendar_row(employee: Employee, annual: LeaveTypeRow) -> None:
    _old_grant(employee, annual, date(2025, 1, 1), date(2025, 12, 31), 15)
    _switch(True)
    ledger.ensure_grants(employee, date(2026, 6, 1))
    assert _auto_starts(employee) == {date(2026, 3, 1)}
    auto = next(g for g in rows.grants(employee.pk) if g.kind == GrantKind.AUTO)
    assert (auto.start, auto.end, auto.days) == (date(2026, 3, 1), date(2027, 2, 28), 15)


def test_negative_row_does_not_cover_year(employee: Employee, annual: LeaveTypeRow) -> None:
    _old_grant(employee, annual, date(2026, 1, 1), date(2026, 12, 31), -5)
    _switch(True)
    ledger.ensure_grants(employee, date(2026, 6, 1))
    assert _auto_starts(employee) == {date(2026, 3, 1)}


def test_grant_of_another_type_covers_year(employee: Employee, annual: LeaveTypeRow) -> None:
    """An old-program grant under a type not marked annual still counts: no duplicate next to it."""
    other = LeaveTypeRow.objects.create(name="Хуучин ээлжийн")
    _old_grant(employee, other, date(2026, 1, 1), date(2026, 12, 31), 15)
    _switch(True)
    ledger.ensure_grants(employee, date(2026, 6, 1))
    assert _auto_starts(employee) == set()


def test_switch_off_keeps_written_auto_rows(employee: Employee, annual: LeaveTypeRow) -> None:
    _switch(True)
    ledger.ensure_grants(employee, TODAY)
    _switch(False)
    assert _auto_starts(employee) == {date(2026, 3, 1)}


def test_no_annual_type_configured(employee: Employee) -> None:
    _switch(True)
    ledger.ensure_grants(employee, TODAY)
    assert not Entitlement.objects.filter(employee=employee).exists()
    assert ledger.periods(employee, TODAY) == ([], [])
    assert ledger.balance_on(employee, date(2025, 4, 1)) is None


def test_periods_newest_first_and_upcoming(employee: Employee, annual: LeaveTypeRow) -> None:
    _old_grant(employee, annual, date(2024, 3, 1), date(2025, 2, 28), 15)
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    _old_grant(employee, annual, date(2027, 3, 1), date(2028, 2, 29), 3)
    found, nowhere = ledger.periods(employee, TODAY)
    assert [p.start for p in found] == [date(2027, 3, 1), date(2025, 3, 1), date(2024, 3, 1)]
    assert [p.upcoming for p in found] == [True, False, False]
    assert nowhere == []


def test_leave_charged_to_latest_overlapping_period(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 1, 1), date(2025, 12, 31), 15)
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    _leave(employee, annual, date(2025, 4, 1), date(2025, 4, 3), 3, actor)
    found, _ = ledger.periods(employee, TODAY)
    assert (found[0].start, found[0].taken, found[0].left) == (date(2025, 3, 1), 3, 12)
    assert (found[1].start, found[1].taken, found[1].left) == (date(2025, 1, 1), 0, 15)


def test_leave_without_period_listed_apart(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    stray = _leave(employee, annual, date(2020, 5, 4), date(2020, 5, 5), 2, actor)
    found, nowhere = ledger.periods(employee, TODAY)
    assert [lv.id for lv in nowhere] == [stray.id]
    assert found[0].taken == 0


def test_doubled_flag(employee: Employee, annual: LeaveTypeRow) -> None:
    _old_grant(employee, annual, date(2025, 1, 1), date(2025, 12, 31), 15)
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    _old_grant(employee, annual, date(2027, 3, 1), date(2028, 2, 29), 15)
    found, _ = ledger.periods(employee, TODAY)
    flags = {p.start: p.doubled for p in found}
    assert flags == {date(2027, 3, 1): False, date(2025, 3, 1): True, date(2025, 1, 1): True}


def test_doubled_ignores_net_negative_period(employee: Employee, annual: LeaveTypeRow) -> None:
    _old_grant(employee, annual, date(2025, 1, 1), date(2025, 12, 31), 15)
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), -4)
    found, _ = ledger.periods(employee, TODAY)
    assert {p.start: p.doubled for p in found} == {date(2025, 1, 1): False, date(2025, 3, 1): False}


def test_adjust_reversed_range_refused(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    with pytest.raises(ledger.LedgerError):
        ledger.adjust(employee, date(2026, 2, 28), date(2025, 3, 1), 2, "x", actor)
    assert not Entitlement.objects.filter(employee=employee).exists()


def test_manual_grant_reversed_range_refused(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    with pytest.raises(ledger.LedgerError):
        ledger.manual_grant(employee, date(2026, 2, 28), date(2025, 3, 1), 2, "x", actor)
    assert not Entitlement.objects.filter(employee=employee).exists()


def test_balance_on_and_exclude_leave(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    lv = _leave(employee, annual, date(2025, 4, 1), date(2025, 4, 3), 3, actor)
    assert ledger.balance_on(employee, date(2025, 4, 1)) == 12
    assert ledger.balance_on(employee, date(2025, 4, 1), exclude_leave_id=lv.id) == 15
    assert ledger.balance_on(employee, date(2020, 1, 1)) is None


def test_adjust_requires_reason_and_logs(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    with pytest.raises(ledger.LedgerError):
        ledger.adjust(employee, date(2025, 3, 1), date(2026, 2, 28), -2, " ", actor)
    ledger.adjust(employee, date(2025, 3, 1), date(2026, 2, 28), -2, "Өмнө авсан", actor)
    assert _period(employee, date(2025, 3, 1)).left == 13
    assert employee.activity.filter(message__contains="Амралтын эрх").exists()


def test_adjust_zero_days_raises(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    with pytest.raises(ledger.LedgerError):
        ledger.adjust(employee, date(2025, 3, 1), date(2026, 2, 28), 0, "x", actor)


def test_manual_grant_needs_annual_type(employee: Employee, actor: User) -> None:
    with pytest.raises(ledger.LedgerError) as exc:
        ledger.manual_grant(employee, date(2025, 3, 1), date(2026, 2, 28), 15, "x", actor)
    assert str(exc.value) == ledger.NOT_CONFIGURED


def test_manual_grant_creates_manual_row(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    grant = ledger.manual_grant(employee, date(2025, 3, 1), date(2026, 2, 28), 15, "Гэрээгээр", actor)
    assert isinstance(grant, GrantRow)
    assert (grant.kind, grant.days) == (GrantKind.MANUAL, 15)


def test_manual_grant_zero_days_raises(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    with pytest.raises(ledger.LedgerError):
        ledger.manual_grant(employee, date(2025, 3, 1), date(2026, 2, 28), 0, "x", actor)


def test_carry_over_whole_days(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    _switch(True)
    ledger.ensure_grants(employee, TODAY)
    out, inn = ledger.carry_over(employee, date(2025, 3, 1), date(2026, 2, 28), 4, "Ажлын шаардлагаар", actor)
    assert (out.days, out.kind) == (-4, GrantKind.ADJUSTMENT)
    assert (inn.days, inn.kind, inn.start) == (4, GrantKind.CARRY_OVER, date(2026, 3, 1))
    assert _period(employee, date(2025, 3, 1)).left == 11
    assert _period(employee, date(2026, 3, 1)).left == 19


def test_carry_over_cannot_exceed_balance(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    with pytest.raises(ledger.LedgerError):
        ledger.carry_over(employee, date(2025, 3, 1), date(2026, 2, 28), 16, "x", actor)


def test_carry_over_zero_or_negative_raises(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    with pytest.raises(ledger.LedgerError):
        ledger.carry_over(employee, date(2025, 3, 1), date(2026, 2, 28), 0, "x", actor)


def test_carry_over_unknown_period_raises(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    with pytest.raises(ledger.LedgerError):
        ledger.carry_over(employee, date(2023, 3, 1), date(2024, 2, 29), 1, "x", actor)


def test_carry_from_calendar_year_goes_to_same_length_period(
    employee: Employee, annual: LeaveTypeRow, actor: User
) -> None:
    _old_grant(employee, annual, date(2025, 1, 1), date(2025, 12, 31), 15)
    ledger.carry_over(employee, date(2025, 1, 1), date(2025, 12, 31), 5, "x", actor)
    assert _period(employee, date(2025, 1, 1)).left == 10
    target = _period(employee, date(2026, 1, 1))
    assert (target.end, target.granted) == (date(2026, 12, 31), 5)


def test_carry_from_current_year_shows_next_year_as_upcoming(
    employee: Employee, annual: LeaveTypeRow, actor: User
) -> None:
    _switch(True)
    ledger.ensure_grants(employee, TODAY)
    ledger.carry_over(employee, date(2026, 3, 1), date(2027, 2, 28), 3, "x", actor)
    nxt = _period(employee, date(2027, 3, 1))
    assert (nxt.end, nxt.granted, nxt.upcoming) == (date(2028, 2, 29), 3, True)


def test_carry_over_logs_activity(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _old_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15)
    ledger.carry_over(employee, date(2025, 3, 1), date(2026, 2, 28), 4, "Шалтгаан", actor)
    assert employee.activity.filter(message__contains="шилжүүлсэн").exists()


def test_existing_auto_grant_not_rewritten_by_new_rule(employee: Employee, annual: LeaveTypeRow) -> None:
    _switch(True)
    ledger.ensure_grants(employee, TODAY)
    AnnualLeaveRule.objects.create(
        effective_from=date(2026, 1, 1), base_days=20, base_days_minor_or_disabled=20, brackets=[]
    )
    ledger.ensure_grants(employee, TODAY)
    assert _period(employee, date(2026, 3, 1)).granted == 15


def test_leaver_gets_no_grant_for_year_after_leaving(actor: User, annual: LeaveTypeRow) -> None:
    from employees.tests.helpers import record_signed
    from macs.models import FiredReason

    e = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ44112233")
    record_signed(
        e,
        type="termination",
        effective=date(2025, 6, 1),
        changes={},
        salary=None,
        reason="",
        fired_reason=FiredReason.objects.get_or_create(name="Өөрийн хүсэлтээр")[0],
        note="",
        by=actor,
    )
    _switch(True)
    ledger.ensure_grants(e, date(2026, 10, 14))
    assert _auto_starts(e) == set()  # the last year ended with the job; nothing is back-filled


def _same_period(employee: Employee, annual: LeaveTypeRow, kinds_days: list[tuple[GrantKind, int]]) -> ledger.Period:
    start, end = date(2025, 3, 1), date(2026, 2, 28)
    for kind, days in kinds_days:
        writes.add_grant(employee, annual, start, end, days, "", kind, None)
    return _period(employee, start)


def test_same_period_auto_plus_adjustment_not_doubled(employee: Employee, annual: LeaveTypeRow) -> None:
    assert not _same_period(employee, annual, [(GrantKind.AUTO, 15), (GrantKind.ADJUSTMENT, 3)]).doubled


def test_same_period_auto_plus_carry_in_not_doubled(employee: Employee, annual: LeaveTypeRow) -> None:
    assert not _same_period(employee, annual, [(GrantKind.AUTO, 15), (GrantKind.CARRY_OVER, 2)]).doubled


def test_same_period_auto_plus_manual_doubled(employee: Employee, annual: LeaveTypeRow) -> None:
    assert _same_period(employee, annual, [(GrantKind.AUTO, 15), (GrantKind.MANUAL, 5)]).doubled


def test_same_period_two_auto_doubled(employee: Employee, annual: LeaveTypeRow) -> None:
    assert _same_period(employee, annual, [(GrantKind.AUTO, 15), (GrantKind.AUTO, 15)]).doubled


def test_daily_sync_adds_current_year_grant(employee: Employee, annual: LeaveTypeRow) -> None:
    from employees.daily_sync import sync_all_employees

    _switch(True)
    sync_all_employees(TODAY)
    assert _auto_starts(employee) == {date(2026, 3, 1)}
