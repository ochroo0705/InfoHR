from datetime import date
from typing import Any

import pytest
from accounts.models import User

from employees import history_range
from employees.models import Employee, JobRecord
from employees.services import history
from employees.services.reporting_line import reporting_line
from employees.tests.helpers import next_order_number

from .conftest import hire_values

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)


def _person(actor: User, job_values: dict[str, Any], register_no: str, manager: Employee | None = None) -> Employee:
    job = {**job_values, "manager": manager}
    return history.hire(
        hire_values(register_no),
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=None,
        by=actor,
        order_number=next_order_number(),
    )


def test_chain_goes_up_in_order(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    assert [lvl.employee.pk for lvl in reporting_line(c.pk, DAY)] == [b.pk, a.pk]


def test_top_of_company_is_empty(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    assert reporting_line(a.pk, DAY) == []


def test_level_carries_the_managers_own_job(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    levels = reporting_line(c.pk, DAY)
    assert levels[0].job is not None
    assert levels[0].job.employee_id == b.pk
    assert levels[1].job is not None
    assert levels[1].job.employee_id == a.pk


def test_no_job_on_day_gives_empty(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    assert reporting_line(c.pk, date(2025, 1, 1)) == []  # hired 2026-01-05


def test_until_is_last_day_of_the_job_record(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    JobRecord.objects.filter(employee=c).update(**history_range.span_kwargs(date(2026, 1, 5), date(2026, 3, 1)))
    assert reporting_line(c.pk, date(2026, 2, 1))[0].until == date(2026, 2, 28)
    assert reporting_line(c.pk, DAY) == []  # c's record ends before DAY: no job in force, so no chain


def test_until_is_none_for_open_record(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    assert reporting_line(c.pk, DAY)[0].until is None


def test_until_for_a_level_above_the_first(actor: User, job_values: dict[str, Any]) -> None:
    """Level 1 (a) is bounded by b's record, the lower person for that level, not by c's record."""
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    JobRecord.objects.filter(employee=b).update(**history_range.span_kwargs(date(2026, 1, 5), date(2026, 3, 1)))
    levels = reporting_line(c.pk, date(2026, 2, 1))
    assert levels[0].until is None  # c's record is open
    assert levels[1].until == date(2026, 2, 28)  # b's record ends 2026-03-01 (first day after it)


def _split(employee: Employee, day: date, manager: Employee | None) -> None:
    """A job change on `day`: close the employee's record there and open a copy from `day` with `manager`."""
    first = JobRecord.objects.get(employee=employee)
    JobRecord.objects.filter(pk=first.pk).update(**history_range.span_kwargs(first.start_date, day))
    first.pk = None
    first.start_date = day
    first.end_date = None
    first.manager = manager
    first.save()


def test_split_with_same_manager_keeps_relation_open(actor: User, job_values: dict[str, Any]) -> None:
    """A position change under the same manager is not the end of the relation: until stays None."""
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    _split(c, date(2026, 3, 1), b)
    assert reporting_line(c.pk, date(2026, 2, 1))[0].until is None


def test_split_with_other_manager_ends_relation(actor: User, job_values: dict[str, Any]) -> None:
    """The next record names another manager, so the relation with b ends the day before that record starts."""
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    _split(c, date(2026, 3, 1), a)
    assert reporting_line(c.pk, date(2026, 2, 1))[0].until == date(2026, 2, 28)


def test_loop_in_data_stops(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    JobRecord.objects.filter(employee=a).update(manager=c)
    assert [lvl.employee.pk for lvl in reporting_line(c.pk, DAY)] == [b.pk, a.pk]


def test_manager_without_job_ends_the_chain(actor: User, job_values: dict[str, Any]) -> None:
    a = _person(actor, job_values, "УБ00000001")
    b = _person(actor, job_values, "УБ00000002", manager=a)
    c = _person(actor, job_values, "УБ00000003", manager=b)
    JobRecord.objects.filter(employee=b).update(**history_range.span_kwargs(date(2026, 1, 5), date(2026, 2, 1)))
    levels = reporting_line(c.pk, DAY)
    assert [lvl.employee.pk for lvl in levels] == [b.pk]
    assert levels[0].job is None
