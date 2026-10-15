from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from employees.models import Employee

from leave.models import LeaveStatus, LeaveType
from leave.services import ledger, records
from leave.services.records import Draft

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def d(e: Employee, t: LeaveType, s: date, end: date, **kw: object) -> Draft:
    return Draft(employee=e, leave_type=t, start_date=s, end_date=end, **kw)  # type: ignore[arg-type]


def test_check_counts_days_and_balance(employee: Employee, annual: LeaveType) -> None:
    c = records.check(d(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), TODAY)
    assert c.working_days == Decimal(10) and c.year_start == date(2026, 3, 1)
    assert c.balance_after == Decimal(5) and not c.errors and not c.needs_override


def test_weekend_only_is_an_error(employee: Employee, annual: LeaveType) -> None:
    c = records.check(d(employee, annual, date(2026, 11, 7), date(2026, 11, 8)), TODAY)
    assert c.errors == ["Сонгосон хугацаанд ажлын өдөр алга."]


def test_year_boundary_refused(employee: Employee, annual: LeaveType) -> None:
    c = records.check(d(employee, annual, date(2027, 2, 22), date(2027, 3, 5)), TODAY)
    assert c.errors and "хоёр хуваан" in c.errors[0]


def test_negative_balance_needs_override(employee: Employee, annual: LeaveType, actor: User) -> None:
    draft = d(employee, annual, date(2026, 11, 2), date(2026, 11, 27))  # 20 days > 15
    c = records.check(draft, TODAY)
    assert c.needs_override and c.balance_after == Decimal(-5)
    assert any("-5 хоног" in w and ".0" not in w for w in c.warnings)
    with pytest.raises(records.LeaveError):
        records.record(draft, actor, TODAY)
    draft.override_reason = "Захирал зөвшөөрсөн"
    assert records.record(draft, actor, TODAY).working_days == Decimal(20)


def test_overlap_warning_but_not_with_itself(employee: Employee, annual: LeaveType, actor: User) -> None:
    leave = records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), actor, TODAY)
    again = records.check(d(employee, annual, date(2026, 11, 10), date(2026, 11, 11)), TODAY)
    assert any("өөр чөлөө" in err for err in again.errors)  # annual vs annual is an error now
    edit = records.check(d(employee, annual, date(2026, 11, 2), date(2026, 11, 12), leave_id=leave.pk), TODAY)
    assert not any("өөр чөлөө" in w for w in edit.warnings)
    assert edit.balance_after == Decimal(6)  # its own old 10 days are not counted


def test_ten_day_rule_warning(employee: Employee, annual: LeaveType, actor: User) -> None:
    records.record(d(employee, annual, date(2026, 4, 6), date(2026, 4, 10)), actor, TODAY)  # 5
    c = records.check(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), TODAY)  # 5 → left 5
    assert any("10-аас доошгүй" in w for w in c.warnings)


def test_eligibility_warning(actor: User, annual: LeaveType) -> None:
    from leave.tests.conftest import make_employee

    e = make_employee(actor, hired=date(2026, 9, 1), register_no="УБ66112233")
    c = records.check(d(e, annual, date(2026, 11, 2), date(2026, 11, 3)), TODAY)
    assert any("6 сар" in w for w in c.warnings)


def test_sick_leave_has_no_balance(employee: Employee) -> None:
    sick = LeaveType.objects.get(code="sick")
    c = records.check(d(employee, sick, date(2026, 11, 2), date(2026, 11, 3)), TODAY)
    assert c.year_start is None and c.balance_after is None and c.working_days == Decimal(2)


def test_record_update_cancel_log(employee: Employee, annual: LeaveType, actor: User) -> None:
    leave = records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor, TODAY)
    records.update(leave, d(employee, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, TODAY)
    leave.refresh_from_db()
    assert leave.working_days == Decimal(3)
    with pytest.raises(records.LeaveError):
        records.cancel(leave, "", actor, TODAY)
    records.cancel(leave, "Төлөвлөгөө өөрчлөгдсөн", actor, TODAY)
    leave.refresh_from_db()
    assert leave.status == LeaveStatus.CANCELLED
    assert ledger.balance(employee, date(2026, 3, 1)) == Decimal(15)
    assert employee.activity.count() >= 3


def test_end_before_start_is_error(employee: Employee, annual: LeaveType) -> None:
    c = records.check(d(employee, annual, date(2026, 11, 6), date(2026, 11, 2)), TODAY)
    assert c.errors == ["Дуусах огноо эхлэхээс өмнө байна."]


def test_annual_leave_before_employment_start_is_error(employee: Employee, annual: LeaveType) -> None:
    c = records.check(d(employee, annual, date(2024, 2, 5), date(2024, 2, 6)), TODAY)
    assert c.errors == ["Ажилд орохоос өмнөх огноо байна."]


def test_update_of_cancelled_leave_refused(employee: Employee, annual: LeaveType, actor: User) -> None:
    leave = records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor, TODAY)
    records.cancel(leave, "Шалтгаан", actor, TODAY)
    with pytest.raises(records.LeaveError):
        records.update(leave, d(employee, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, TODAY)


def test_cancel_twice_refused(employee: Employee, annual: LeaveType, actor: User) -> None:
    leave = records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor, TODAY)
    records.cancel(leave, "Шалтгаан", actor, TODAY)
    with pytest.raises(records.LeaveError):
        records.cancel(leave, "Дахин", actor, TODAY)


def test_update_keeps_original_employee(employee: Employee, annual: LeaveType, actor: User) -> None:
    from leave.tests.conftest import make_employee

    other = make_employee(actor, hired=date(2020, 6, 1), register_no="УБ55112233")
    leave = records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor, TODAY)
    records.update(leave, d(other, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, TODAY)
    leave.refresh_from_db()
    assert leave.employee_id == employee.pk and leave.year_start == date(2026, 3, 1)
    assert leave.working_days == Decimal(3)


def test_check_for_future_year_writes_no_grants(employee: Employee, annual: LeaveType) -> None:
    from leave.models import GrantKind, LeaveGrant

    c = records.check(d(employee, annual, date(2031, 3, 3), date(2031, 3, 7)), TODAY)
    assert not c.errors and c.year_start == date(2031, 3, 1)
    assert c.balance_after == Decimal(13)  # the 2031 auto grant (15 + 3 service) is counted, not written
    starts = set(LeaveGrant.objects.filter(employee=employee, kind=GrantKind.AUTO).values_list("year_start", flat=True))
    assert max(starts) == date(2026, 3, 1)


def test_holiday_added_later_recounts_leave(employee: Employee, annual: LeaveType, actor: User) -> None:
    leave = records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), actor, TODAY)
    assert leave.working_days == Decimal(10)
    from leave.models import Holiday

    Holiday.objects.create(date=date(2026, 11, 4), name="x")
    assert records.recount({date(2026, 11, 4)}, actor) == 1
    leave.refresh_from_db()
    assert leave.working_days == Decimal(9)
    assert ledger.balance(employee, date(2026, 3, 1)) == Decimal(6)
    assert records.recount({date(2026, 12, 25)}, actor) == 0


def test_started_leave_is_marked_mistake_not_cancelled(employee: Employee, annual: LeaveType, actor: User) -> None:
    from employees.models import ActivityEntry

    leave = records.record(d(employee, annual, date(2026, 10, 12), date(2026, 10, 16)), actor, TODAY)
    before = ledger.balance(employee, date(2026, 3, 1))
    records.cancel(leave, "Өөр хүнд бүртгэсэн", actor, TODAY)
    leave.refresh_from_db()
    assert leave.status == LeaveStatus.MISTAKE
    assert ledger.balance(employee, date(2026, 3, 1)) == before + leave.working_days
    assert ActivityEntry.objects.filter(employee=employee, message__startswith="Буруу бүртгэсэн тул хассан").exists()


def test_future_leave_is_cancelled(employee: Employee, annual: LeaveType, actor: User) -> None:
    leave = records.record(d(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor, TODAY)
    records.cancel(leave, "Төлөвлөгөө өөрчлөгдсөн", actor, TODAY)
    leave.refresh_from_db()
    assert leave.status == LeaveStatus.CANCELLED
