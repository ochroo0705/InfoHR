from datetime import date

from accounts.models import User
from employees.listing import row_for
from employees.services import macs_writes
from macs.models import Department, Employee

from reports.filters import Filters
from reports.leave_common import people
from reports.tests.conftest import _make_user, transfer


def test_people_limits_to_visible_and_filters_department(db: None, hr_user: User, hired: Employee) -> None:
    today = date(2026, 5, 1)
    job = row_for(hired, today).job
    assert job is not None
    own_dept = job.department_id
    assert own_dept is not None
    assert [p.employee.pk for p in people(hr_user, Filters(), today)] == [hired.pk]
    other = macs_writes.save_department("Бусад хэлтэс")
    assert people(hr_user, Filters(department=other.pk), today) == []
    assert [p.employee.pk for p in people(hr_user, Filters(department=own_dept), today)] == [hired.pk]
    assert people(hr_user, Filters(branch=999999), today) == []
    # an Employee-role user with no login link on any employee sees nobody
    assert people(_make_user("Employee", "leave-self"), Filters(), today) == []


def test_people_reads_department_on_the_given_day(db: None, hr_user: User, hired: Employee, actor: User) -> None:
    transfer(hired, "Маркетинг", date(2026, 6, 1), actor)
    new = Department.objects.get(name="Маркетинг")
    assert people(hr_user, Filters(department=new.pk), date(2026, 5, 1)) == []
    assert [p.employee.pk for p in people(hr_user, Filters(department=new.pk), date(2026, 7, 1))] == [hired.pk]
