"""Legacy MACS employees with no birth date or no hire date (QC 2a). Missing dates must not crash leave code."""

from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import Employee, ensure_ext
from employees.services import macs_writes
from macs.models import LeaveAssign, LeaveTypeRow

from leave.services import entitlement, ledger

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 16)
MISSING = "Ажилд орсон огноо бүртгэлгүй тул ээлжийн амралтыг тооцох боломжгүй."


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("leave.views.today", lambda: TODAY)
    monkeypatch.setattr("employees.views.leave_today", lambda: TODAY)
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)


def _legacy(actor: User, **columns: object) -> Employee:
    """A MACS-only employee: a row with no HR job or salary history, dates overridden by `columns`."""
    from employees.tests.conftest import hire_values

    emp = macs_writes.create_employee(hire_values(), {}, code=macs_writes.next_code(), by=actor)
    ensure_ext(emp)
    Employee.objects.filter(pk=emp.pk).update(**columns)
    return Employee.objects.get(pk=emp.pk)


def _hr() -> Client:
    u = User.objects.create_user("u_hr_missing", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name="HR"))
    c = Client()
    c.force_login(u)
    return c


def test_detail_page_loads_without_birthday(actor: User) -> None:
    emp = _legacy(actor, birth_date=None)
    r = _hr().get(reverse("employees:detail", args=[emp.pk]))
    assert r.status_code == 200
    assert "Ээлжийн амралт" in r.content.decode()
    assert MISSING not in r.content.decode()


def test_detail_page_without_hire_date_shows_notice(actor: User) -> None:
    emp = _legacy(actor, first_hire_date=None, contract_start=None)
    r = _hr().get(reverse("employees:detail", args=[emp.pk]))
    assert r.status_code == 200
    assert MISSING in r.content.decode()


def test_contract_start_is_not_used_when_first_hire_date_is_empty(actor: User) -> None:
    emp = _legacy(actor, first_hire_date=None, contract_start=date(2020, 2, 1))
    assert entitlement.employment_start(emp) is None


def test_leave_record_is_refused_without_start(actor: User, annual: LeaveTypeRow) -> None:
    emp = _legacy(actor, first_hire_date=None, contract_start=None)
    r = _hr().post(
        reverse("leave:add"),
        {"employee": emp.pk, "leave_type": annual.pk, "start_date": "2026-10-20", "end_date": "2026-10-21"},
    )
    assert r.status_code == 200
    assert MISSING in r.content.decode()
    assert not LeaveAssign.objects.filter(employee=emp).exists()


def test_carry_over_is_refused_without_start(actor: User, annual: LeaveTypeRow) -> None:
    emp = _legacy(actor, first_hire_date=None, contract_start=None)
    r = _hr().post(
        reverse("leave:carry", args=[emp.pk, "2026-01-05", "2026-12-31"]),
        {"days": "2", "reason": "x"},
    )
    assert r.status_code == 200
    assert MISSING in r.content.decode()


def test_entitlement_helpers_return_empty_without_start(actor: User, annual: LeaveTypeRow) -> None:
    emp = _legacy(actor, first_hire_date=None, contract_start=None)
    assert entitlement.employment_start(emp) is None
    assert entitlement.year_starts(emp, TODAY) == []
    assert entitlement.eligible_from(emp) is None
    assert ledger.periods(emp, TODAY) == ([], [])
    with pytest.raises(ValueError, match="бүртгэлгүй"):
        entitlement.next_year_start(emp, TODAY)


def test_missing_birthday_is_not_a_minor(actor: User) -> None:
    emp = _legacy(actor, birth_date=None, first_hire_date=date(2021, 10, 16))
    breakdown = entitlement.entitled(emp, date(2026, 10, 16)).breakdown
    assert "18-аас доош" not in breakdown


def test_service_months_for_legacy_without_job_records_counts_from_hire_date(actor: User) -> None:
    emp = _legacy(actor, first_hire_date=date(2021, 10, 16))
    assert emp.job_records.count() == 0
    assert entitlement.service_months(emp, date(2026, 10, 16)) == 60


def test_existing_employee_service_months_unchanged(employee: Employee) -> None:
    # hired 2024-03-01 with an HR hire job record: JobRecords exist, so the job-based count is kept
    assert entitlement.service_months(employee, date(2026, 3, 1)) == 24
    assert entitlement.employment_start(employee) == date(2024, 3, 1)


def test_macs_only_leaver_gets_no_leave_years(actor: User, annual: LeaveTypeRow, grants_on: None) -> None:
    emp = _legacy(actor, emptype=3, first_hire_date=date(2020, 1, 6))
    ledger.ensure_grants(emp, TODAY)
    assert ledger.periods(emp, TODAY) == ([], [])
