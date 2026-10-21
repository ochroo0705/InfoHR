from datetime import date
from typing import Any

import pytest
from accounts.models import User
from employees.models import ActivityEntry, Employee
from macs.models import LeaveAssign, LeaveTypeRow

from leave.models import LeaveExt
from leave.services import ledger, records, rows, writes
from leave.services.records import Draft
from leave.services.rows import State
from leave.services.writes import DUPLICATE, STALE

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def d(e: Employee, t: LeaveTypeRow, s: date, end: date, **kw: Any) -> Draft:
    return Draft(employee=e, leave_type=t, start_date=s, end_date=end, **kw)


def _record(draft: Draft, actor: User) -> LeaveAssign:
    return records.record(draft, actor, TODAY)


def test_check_counts_days_and_period(employee: Employee, annual: LeaveTypeRow, grants_on: None) -> None:
    c = records.check(d(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), TODAY)
    assert c.working_days == 10
    assert c.period is not None and c.period.start == date(2026, 3, 1)
    assert c.balance_after == 5 and not c.errors and not c.needs_override


def test_weekend_only_is_an_error(employee: Employee, annual: LeaveTypeRow) -> None:
    c = records.check(d(employee, annual, date(2026, 11, 7), date(2026, 11, 8)), TODAY)
    assert c.errors == ["Сонгосон хугацаанд ажлын өдөр алга."]


def test_year_boundary_refused(employee: Employee, annual: LeaveTypeRow) -> None:
    c = records.check(d(employee, annual, date(2027, 2, 22), date(2027, 3, 5)), TODAY)
    assert c.errors and "хоёр хуваан" in c.errors[0]


def test_negative_balance_needs_override(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    draft = d(employee, annual, date(2026, 11, 2), date(2026, 11, 27))  # 20 working days > 15
    c = records.check(draft, TODAY)
    assert c.needs_override and c.balance_after == -5
    assert any("-5 хоног" in w for w in c.warnings)
    with pytest.raises(records.LeaveError):
        _record(draft, actor)
    draft.override_reason = "Захирал зөвшөөрсөн"
    assert _record(draft, actor).adays == 20


def test_annual_overlap_is_error_except_with_itself(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    leave = _record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), actor)
    again = records.check(d(employee, annual, date(2026, 11, 10), date(2026, 11, 11)), TODAY)
    assert any("өөр чөлөө" in err for err in again.errors)
    edit = records.check(d(employee, annual, date(2026, 11, 2), date(2026, 11, 12), leave_id=leave.pk), TODAY)
    assert not any("өөр чөлөө" in w for w in edit.warnings)
    assert edit.balance_after == 6  # its own old 10 days are not counted


def test_duplicate_active_leave_refused(employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None) -> None:
    draft = d(employee, annual, date(2026, 11, 2), date(2026, 11, 6))
    _record(draft, actor)
    assert records.check(draft, TODAY).errors == [DUPLICATE]
    with pytest.raises(records.LeaveError, match=DUPLICATE):
        _record(draft, actor)


def test_ten_day_rule_warning(employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None) -> None:
    _record(d(employee, annual, date(2026, 4, 6), date(2026, 4, 10)), actor)  # 5 days
    c = records.check(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), TODAY)  # 5 more, 5 left
    assert any("10-аас доошгүй" in w for w in c.warnings)


def test_eligibility_warning(actor: User, annual: LeaveTypeRow) -> None:
    from leave.tests.conftest import make_employee

    e = make_employee(actor, hired=date(2026, 9, 1), register_no="УБ66112233")
    c = records.check(d(e, annual, date(2026, 11, 2), date(2026, 11, 3)), TODAY)
    assert any("6 сар" in w for w in c.warnings)


def test_no_grant_period_warns_and_needs_reason(employee: Employee, annual: LeaveTypeRow, grants_on: None) -> None:
    c = records.check(d(employee, annual, date(2027, 6, 7), date(2027, 6, 8)), TODAY)
    assert c.period is None and c.needs_override and c.balance_after == -2
    assert any("амралтын эрх олдсонгүй" in w for w in c.warnings)


def test_sick_leave_has_no_balance(employee: Employee, sick: LeaveTypeRow) -> None:
    c = records.check(d(employee, sick, date(2026, 11, 2), date(2026, 11, 3)), TODAY)
    assert c.period is None and c.balance_after is None and c.working_days == 2


def test_record_update_cancel_log(employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None) -> None:
    leave = _record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor)
    records.update(
        leave, d(employee, annual, date(2026, 11, 2), date(2026, 11, 4), loaded=writes.snapshot(leave)), actor, TODAY
    )
    leave = LeaveAssign.objects.get(pk=leave.pk)
    assert leave.adays == 3
    with pytest.raises(records.LeaveError):
        records.cancel(leave, writes.snapshot(leave), "", actor, TODAY)
    records.cancel(leave, writes.snapshot(leave), "Төлөвлөгөө өөрчлөгдсөн", actor, TODAY)
    leave = LeaveAssign.objects.get(pk=leave.pk)
    assert leave.status == LeaveAssign.CANCELLED
    assert ledger.balance_on(employee, date(2026, 3, 1)) == 15
    assert employee.activity.count() >= 3


def test_end_before_start_is_error(employee: Employee, annual: LeaveTypeRow) -> None:
    c = records.check(d(employee, annual, date(2026, 11, 6), date(2026, 11, 2)), TODAY)
    assert c.errors == ["Дуусах огноо эхлэхээс өмнө байна."]


def test_annual_leave_before_employment_start_is_error(employee: Employee, annual: LeaveTypeRow) -> None:
    c = records.check(d(employee, annual, date(2024, 2, 5), date(2024, 2, 6)), TODAY)
    assert c.errors == ["Ажилд орохоос өмнөх огноо байна."]


def test_update_without_loaded_row_is_refused(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    leave = _record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor)
    with pytest.raises(records.LeaveError, match=STALE):
        records.update(leave, d(employee, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, TODAY)


def test_update_of_cancelled_leave_refused(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    leave = _record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor)
    records.cancel(leave, writes.snapshot(leave), "Шалтгаан", actor, TODAY)
    leave = LeaveAssign.objects.get(pk=leave.pk)
    with pytest.raises(records.LeaveError):
        records.update(
            leave,
            d(employee, annual, date(2026, 11, 2), date(2026, 11, 4), loaded=writes.snapshot(leave)),
            actor,
            TODAY,
        )


def test_cancel_twice_refused(employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None) -> None:
    leave = _record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor)
    records.cancel(leave, writes.snapshot(leave), "Шалтгаан", actor, TODAY)
    leave = LeaveAssign.objects.get(pk=leave.pk)
    with pytest.raises(records.LeaveError):
        records.cancel(leave, writes.snapshot(leave), "Дахин", actor, TODAY)


def test_update_keeps_original_employee(employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None) -> None:
    from leave.tests.conftest import make_employee

    other = make_employee(actor, hired=date(2020, 6, 1), register_no="УБ55112233")
    leave = _record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor)
    records.update(
        leave, d(other, annual, date(2026, 11, 2), date(2026, 11, 4), loaded=writes.snapshot(leave)), actor, TODAY
    )
    leave = LeaveAssign.objects.get(pk=leave.pk)
    assert leave.employee_id == employee.pk and leave.adays == 3


def test_check_for_future_year_writes_no_grants(employee: Employee, annual: LeaveTypeRow, grants_on: None) -> None:
    from macs.models import Entitlement

    c = records.check(d(employee, annual, date(2031, 3, 3), date(2031, 3, 7)), TODAY)
    assert not c.errors and c.period is None
    assert not Entitlement.objects.filter(employee=employee, date1__year=2031).exists()


def test_started_leave_is_marked_mistake_not_cancelled(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    leave = _record(d(employee, annual, date(2026, 10, 12), date(2026, 10, 16)), actor)
    before = ledger.balance_on(employee, date(2026, 3, 1))
    assert before is not None
    records.cancel(leave, writes.snapshot(leave), "Өөр хүнд бүртгэсэн", actor, TODAY)
    leave = LeaveAssign.objects.get(pk=leave.pk)
    assert leave.status == LeaveAssign.CANCELLED
    assert LeaveExt.objects.get(assign=leave).mistake is True
    assert rows.leave(leave.pk).state is State.MISTAKE
    assert ledger.balance_on(employee, date(2026, 3, 1)) == before + 5
    assert ActivityEntry.objects.filter(employee=employee, message__startswith="Буруу бүртгэсэн тул хассан").exists()


def test_future_leave_is_cancelled(employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None) -> None:
    leave = _record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor)
    records.cancel(leave, writes.snapshot(leave), "Төлөвлөгөө өөрчлөгдсөн", actor, TODAY)
    assert rows.leave(leave.pk).state is State.CANCELLED


def test_record_rechecks_under_lock(employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None) -> None:
    _record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), actor)

    with pytest.raises(records.LeaveError):
        _record(d(employee, annual, date(2026, 11, 10), date(2026, 11, 16)), actor)
    assert LeaveAssign.objects.filter(employee=employee, leave_type=annual).count() == 1
