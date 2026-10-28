from datetime import date, timedelta
from typing import Any

import pytest
from accounts.models import User
from django.utils import timezone
from employees.models import Employee
from leave.services import writes
from leave.tests.conftest import annual, make_employee, sick  # noqa: F401 (fixtures)
from macs.models import Absence, AbsenceType, Branch, LeaveAssign, LeaveTypeRow

from reports.absences import ABSENCES, AWAY, OLD_LOG_SOURCE, Entry, old_log
from reports.filters import Filters
from reports.leave_common import Person, people

pytestmark = pytest.mark.django_db

NOTE_DAY = date(2026, 5, 10)


def _year(**values: Any) -> Filters:
    return Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), **values)


def _absence(employee: Employee, kind: AbsenceType, start: date, end: date | None = None, note: str = "") -> Absence:
    return Absence.objects.create(employee_id=employee.pk, absence_type=kind, from_date=start, to_date=end, note=note)


def _old_entries(user: User, f: Filters) -> list[Entry]:
    return ABSENCES.rows(user, f)


def _away(user: User, f: Filters) -> list[Entry]:
    return AWAY.rows(user, f)


# C3: the old «Амралт» log


def test_old_log_row_in_period_is_listed_with_its_type(hr_user: User, actor: User) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    kind = AbsenceType.objects.create(name="Цалинтай чөлөө")
    _absence(emp, kind, date(2026, 3, 3), date(2026, 3, 5), "Хурим")
    (entry,) = _old_entries(hr_user, _year())
    assert entry.person.employee.pk == emp.pk
    assert entry.kind == "Цалинтай чөлөө"
    assert (entry.start, entry.end, entry.comment) == (date(2026, 3, 3), date(2026, 3, 5), "Хурим")
    assert entry.source == OLD_LOG_SOURCE


def test_row_without_end_date_is_one_day(hr_user: User, actor: User) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    kind = AbsenceType.objects.create(name="Өвчний")
    _absence(emp, kind, NOTE_DAY)
    (entry,) = _old_entries(hr_user, Filters(date_from=NOTE_DAY, date_to=NOTE_DAY))
    assert (entry.start, entry.end) == (NOTE_DAY, NOTE_DAY)
    assert _old_entries(hr_user, Filters(date_from=date(2026, 5, 11), date_to=date(2026, 5, 20))) == []


def test_absence_type_filter(hr_user: User, actor: User) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    first = AbsenceType.objects.create(name="Цалинтай чөлөө")
    second = AbsenceType.objects.create(name="Өвчний")
    _absence(emp, first, date(2026, 3, 3), date(2026, 3, 5))
    _absence(emp, second, date(2026, 4, 6), date(2026, 4, 7))
    (entry,) = _old_entries(hr_user, _year(absence_type=second.pk))
    assert entry.kind == "Өвчний"


def test_row_of_an_invisible_employee_is_dropped(hr_user: User, actor: User) -> None:
    emp_a = make_employee(actor, hired=date(2024, 3, 1))
    emp_b = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ88112233")
    kind = AbsenceType.objects.create(name="Өвчний")
    _absence(emp_a, kind, NOTE_DAY, NOTE_DAY)  # the row belongs to A only
    whole_year = (date(2026, 1, 1), date(2026, 12, 31), None)
    # the people map holds B alone: A's row is dropped
    assert old_log({emp_b.pk: _person(hr_user, emp_b)}, *whole_year) == []
    # the people map holds A: the row is there
    (entry,) = old_log({emp_a.pk: _person(hr_user, emp_a)}, *whole_year)
    assert entry.person.employee.pk == emp_a.pk


def test_absence_with_missing_type_row_shows_dash(hr_user: User, actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    kind = AbsenceType.objects.create(name="Өвчний")
    _absence(emp, kind, NOTE_DAY, NOTE_DAY)
    # the database enforces the type foreign key, so a missing type row cannot be stored; simulate the lookup miss
    monkeypatch.setattr(AbsenceType.objects, "in_bulk", lambda ids: {})
    (entry,) = _old_entries(hr_user, Filters(date_from=NOTE_DAY, date_to=NOTE_DAY))
    assert entry.kind == "—"


def _person(user: User, emp: Employee) -> Person:
    (found,) = [p for p in people(user, Filters(), timezone.localdate()) if p.employee.pk == emp.pk]
    return found


# C5: who is away on a date


def test_counted_leave_covers_the_date(hr_user: User, actor: User, sick: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2026, 6, 10), date(2026, 6, 12), 3, "", actor)
    assert _away(hr_user, Filters(as_of=date(2026, 6, 9))) == []
    (entry,) = _away(hr_user, Filters(as_of=date(2026, 6, 10)))
    assert (entry.kind, entry.start, entry.end, entry.source) == (
        "Өвчний амралт",
        date(2026, 6, 10),
        date(2026, 6, 12),
        "Чөлөө",
    )
    assert len(_away(hr_user, Filters(as_of=date(2026, 6, 12)))) == 1
    assert _away(hr_user, Filters(as_of=date(2026, 6, 13))) == []


def test_cancelled_leave_does_not_cover(hr_user: User, actor: User, sick: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    leave = writes.record_assign(emp, sick, date(2026, 6, 10), date(2026, 6, 12), 3, "", actor)
    writes.cancel_assign(leave, writes.snapshot(leave), "Цуцалсан", mistake=False, by=actor)
    assert _away(hr_user, Filters(as_of=date(2026, 6, 11))) == []


def test_mistake_and_rejected_leave_do_not_cover(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    mistake = writes.record_assign(emp, sick, date(2026, 6, 10), date(2026, 6, 12), 3, "", actor)
    writes.cancel_assign(mistake, writes.snapshot(mistake), "Алдаа", mistake=True, by=actor)
    # a second person, so the same dates do not hit the unique key of (employee, type, dates)
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ77112233")
    writes.write_old_style_assign(
        other, sick, date(2026, 6, 10), date(2026, 6, 12), status=LeaveAssign.REJECTED, adays=3, comment=""
    )
    assert _away(hr_user, Filters(as_of=date(2026, 6, 11))) == []


def test_old_log_row_without_end_covers_only_its_day(hr_user: User, actor: User) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    kind = AbsenceType.objects.create(name="Өвчний")
    _absence(emp, kind, date(2026, 6, 10))  # no end date: one day
    assert len(_away(hr_user, Filters(as_of=date(2026, 6, 10)))) == 1
    assert _away(hr_user, Filters(as_of=date(2026, 6, 9))) == []
    assert _away(hr_user, Filters(as_of=date(2026, 6, 11))) == []


def test_old_log_row_covers_the_date(hr_user: User, actor: User) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    kind = AbsenceType.objects.create(name="Өвчний")
    _absence(emp, kind, date(2026, 6, 10), date(2026, 6, 11))
    (entry,) = _away(hr_user, Filters(as_of=date(2026, 6, 11)))
    assert (entry.source, entry.kind) == (OLD_LOG_SOURCE, "Өвчний")
    assert _away(hr_user, Filters(as_of=date(2026, 6, 12))) == []


def test_person_who_left_is_still_listed_for_a_leave_row(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
    left_employee: Employee,
) -> None:
    # left_employee was dismissed on 2026-03-01; a leave row on a later date still shows
    writes.record_assign(left_employee, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    (entry,) = _away(hr_user, Filters(as_of=date(2026, 3, 3)))
    assert entry.person.employee.pk == left_employee.pk
    assert entry.person.state == "left"


def test_default_date_is_today(hr_user: User, actor: User, sick: LeaveTypeRow) -> None:  # noqa: F811
    today = timezone.localdate()
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, today - timedelta(days=1), today + timedelta(days=1), 3, "", actor)
    assert len(_away(hr_user, Filters())) == 1


def test_branch_filter(hr_user: User, actor: User, sick: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    branch = Branch.objects.create(name="Төв")
    other = Branch.objects.create(name="Салбар хоёр")
    Employee.objects.filter(pk=emp.pk).update(branch=branch)
    writes.record_assign(emp, sick, date(2026, 6, 10), date(2026, 6, 12), 3, "", actor)
    assert len(_away(hr_user, Filters(as_of=date(2026, 6, 11), branch=branch.pk))) == 1
    assert _away(hr_user, Filters(as_of=date(2026, 6, 11), branch=other.pk)) == []
