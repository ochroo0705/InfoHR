from datetime import date

import pytest
from accounts.models import User
from leave.services import writes
from leave.tests.conftest import make_employee, sick  # noqa: F401 (fixtures)
from macs.models import Absence, AbsenceType, LeaveTypeRow

from reports.absences import TOTALS
from reports.filters import Filters

pytestmark = pytest.mark.django_db

JULY = Filters(date_from=date(2026, 7, 1), date_to=date(2026, 7, 31))


def _absence(employee_pk: int, kind: AbsenceType, start: date, end: date | None = None) -> Absence:
    return Absence.objects.create(employee_id=employee_pk, absence_type=kind, from_date=start, to_date=end, note="")


def test_leave_days_are_clipped_to_the_period(hr_user: User, actor: User, sick: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    # 2026-06-29 .. 2026-07-03 crosses the period's first edge: only 07-01 (Wed) .. 07-03 (Fri) count, 3 days
    writes.record_assign(emp, sick, date(2026, 6, 29), date(2026, 7, 3), 5, "", actor)
    (row,) = TOTALS.rows(hr_user, JULY)
    assert row.person.employee.pk == emp.pk
    assert row.leave_days == 3


def test_leave_crossing_the_end_edge_is_clipped(hr_user: User, actor: User, sick: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    # 2026-07-29 .. 2026-08-03 crosses the period's last edge: only 07-29 (Wed) .. 07-31 (Fri) count, 3 days
    writes.record_assign(emp, sick, date(2026, 7, 29), date(2026, 8, 3), 5, "", actor)
    (row,) = TOTALS.rows(hr_user, JULY)
    assert row.leave_days == 3


def test_leave_wholly_inside_uses_its_own_days(hr_user: User, actor: User, sick: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    # the recorded days (2) differ from the working days in the range: the recorded days win
    writes.record_assign(emp, sick, date(2026, 7, 6), date(2026, 7, 10), 2, "", actor)
    (row,) = TOTALS.rows(hr_user, JULY)
    assert row.leave_days == 2


def test_cancelled_leave_is_ignored(hr_user: User, actor: User, sick: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    leave = writes.record_assign(emp, sick, date(2026, 7, 6), date(2026, 7, 10), 3, "", actor)
    (row,) = TOTALS.rows(hr_user, JULY)  # recorded: the row shows the leave days
    assert row.leave_days == 3
    writes.cancel_assign(leave, writes.snapshot(leave), "Цуцалсан", mistake=False, by=actor)
    assert TOTALS.rows(hr_user, JULY) == []


def test_log_row_ending_before_it_starts_counts_no_days(hr_user: User, actor: User) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    kind = AbsenceType.objects.create(name="Цалинтай чөлөө")
    _absence(emp.pk, kind, date(2026, 7, 10), date(2026, 7, 8))  # end before start: no days, never negative
    (row,) = TOTALS.rows(hr_user, JULY)
    assert (row.log_entries, row.log_days) == (1, 0)


def test_log_entries_and_days_are_counted(hr_user: User, actor: User) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    kind = AbsenceType.objects.create(name="Цалинтай чөлөө")
    _absence(emp.pk, kind, date(2026, 7, 10), date(2026, 7, 12))  # 3 calendar days
    _absence(emp.pk, kind, date(2026, 7, 20))  # no end date: 1 day
    (row,) = TOTALS.rows(hr_user, JULY)
    assert (row.log_entries, row.log_days, row.leave_days) == (2, 4, 0)


def test_person_with_nothing_has_no_row(hr_user: User, actor: User) -> None:
    make_employee(actor, hired=date(2024, 3, 1))
    assert TOTALS.rows(hr_user, JULY) == []


def test_note_says_lateness_is_missing() -> None:
    assert TOTALS.note is not None
    note = TOTALS.note(JULY)
    assert "Таслалт, хоцролт" in note
    assert "OQ-054" in note


def test_leave_crossing_an_edge_never_exceeds_its_own_days(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    # 2026-06-29 .. 2026-07-03 crosses the start edge; only 07-01 .. 07-03 (3 working days) lie inside, but the
    # leave records 2 days, so the clipped part is capped at 2
    writes.record_assign(emp, sick, date(2026, 6, 29), date(2026, 7, 3), 2, "", actor)
    (row,) = TOTALS.rows(hr_user, JULY)
    assert row.leave_days == 2
