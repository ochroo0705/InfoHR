from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from employees.models import Employee, JobRecord
from employees.services import history
from employees.tests.conftest import hire_values, named
from employees.tests.helpers import record_signed
from macs.models import FiredReason

from reports.filters import Filters
from reports.staff_list import rows
from reports.survey_common import people

from .conftest import legacy

pytestmark = pytest.mark.django_db


def _ids(user: User, f: Filters) -> set[int]:
    return {s.row.employee.pk for s in rows(user, f)}


def test_type_2_listed_only_when_chosen(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    reserve = legacy(actor, job_values, emptype=2)
    assert reserve.pk not in _ids(hr_user, Filters())
    assert reserve.pk not in _ids(hr_user, Filters(state="all"))
    assert reserve.pk in _ids(hr_user, Filters(emptype=2))


def test_type_4_listed_only_when_chosen(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    applicant = legacy(actor, job_values, emptype=4, register_no="УБ00000044")
    assert applicant.pk not in _ids(hr_user, Filters())
    assert applicant.pk not in _ids(hr_user, Filters(state="all"))
    assert applicant.pk in _ids(hr_user, Filters(emptype=4))


def test_type_6_hidden_by_default_shown_when_chosen(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    elder = legacy(actor, job_values, emptype=6)
    assert elder.pk not in _ids(hr_user, Filters())
    assert elder.pk in _ids(hr_user, Filters(emptype=6))


def test_type_filter_exact(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    worker = legacy(actor, job_values, emptype=1, register_no="УБ00000001")
    contract = legacy(actor, job_values, emptype=5, register_no="УБ00000005")
    trial = legacy(actor, job_values, emptype=9, register_no="УБ00000009")
    assert _ids(hr_user, Filters(emptype=1)) == {worker.pk}
    assert _ids(hr_user, Filters(emptype=5)) == {contract.pk}
    assert _ids(hr_user, Filters(emptype=9)) == {trial.pk}


def test_job_emptype_empty_falls_back_to_macs_row(hr_user: User, hired: Employee) -> None:
    JobRecord.objects.filter(employee=hired).update(emptype=None)
    Employee.objects.filter(pk=hired.pk).update(emptype=6)
    assert hired.pk in _ids(hr_user, Filters(emptype=6))
    assert hired.pk not in _ids(hr_user, Filters())


def test_survey_counts_unchanged_by_type_6(
    hr_user: User, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    elder = legacy(actor, job_values, emptype=6)
    reserve = legacy(actor, job_values, emptype=2)  # a type the survey does not count by default
    counted = {p.row.employee.pk for p in people(hr_user, Filters())}
    assert counted == {hired.pk, elder.pk}
    assert reserve.pk not in counted


def _pension_exit(actor: User, job_values: dict[str, Any], register_no: str) -> Employee:
    """A person hired in January 2026 and terminated with a pension exit on 2026-03-01."""
    pensioner = history.hire(
        hire_values(register_no=register_no),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("1500000"),
        by=actor,
    )
    record_signed(
        pensioner,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        pension=True,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    return pensioner


def test_pension_exit_is_type_6_not_1(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    # A pension exit saves a LEFT job whose stored type is a copy of the previous one (1): the type is 6 all the same.
    pensioner = _pension_exit(actor, job_values, "УБ55500006")
    assert pensioner.pk in _ids(hr_user, Filters(emptype=6))
    assert pensioner.pk not in _ids(hr_user, Filters(emptype=1))
    assert pensioner.pk not in _ids(hr_user, Filters())


def test_query_count_does_not_grow_with_pension_exits(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    _pension_exit(actor, job_values, "УБ55500011")
    rows(hr_user, Filters(emptype=6))  # warm the user's permission cache so the first count is not inflated
    with CaptureQueriesContext(connection) as one:
        assert len(rows(hr_user, Filters(emptype=6))) == 1
    for number in (12, 13):
        _pension_exit(actor, job_values, f"УБ555000{number}")
    with CaptureQueriesContext(connection) as three:
        assert len(rows(hr_user, Filters(emptype=6))) == 3
    assert len(three.captured_queries) == len(one.captured_queries)


def test_termination_without_pension_is_type_3(hr_user: User, left_employee: Employee) -> None:
    assert left_employee.pk in _ids(hr_user, Filters(emptype=3))
    assert left_employee.pk not in _ids(hr_user, Filters(emptype=6))
