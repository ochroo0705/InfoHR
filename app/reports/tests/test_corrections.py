"""Corrections from a report cell (reports.corrections, D-080 phase 4): the service the cell editor saves through."""

from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.http import QueryDict
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, CompanySettings, Employee, JobRecord
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

from reports import corrections
from reports.cell_edit import CLASH

pytestmark = pytest.mark.django_db


def _user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return user


def _post(data: dict[str, str]) -> QueryDict:
    return QueryDict(urlencode(data))


def _job(employee: Employee) -> JobRecord:
    record = history.job_on(employee, timezone.localdate())
    assert record is not None
    return record


def test_correct_department_saves_with_reason(hired: Employee) -> None:
    hr = _user("HR", "corr_hr_dept")
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    old = corrections.shown_text(record, "department")
    result = corrections.save(
        hr,
        hired,
        "department",
        record,
        _post({"old": old, "reason": "Бичлэгийн алдаа", "department": str(dept.pk)}),
    )
    assert result.ok is True
    assert result.text == "Үйлдвэрлэл"
    assert _job(hired).department_id == dept.pk
    entry = ActivityEntry.objects.get(employee=hired, kind=ActivityKind.CORRECTION)
    assert entry.message == "Засвар: Бичлэгийн алдаа"


def test_blank_reason_is_refused_and_nothing_changes(hired: Employee) -> None:
    hr = _user("HR", "corr_hr_blank")
    dept = macs_writes.save_department("Захиргаа")
    record = _job(hired)
    before = record.department_id
    result = corrections.save(
        hr,
        hired,
        "department",
        record,
        _post({"old": corrections.shown_text(record, "department"), "reason": "   ", "department": str(dept.pk)}),
    )
    assert result.ok is False
    assert result.error == corrections.NEEDS_REASON
    assert _job(hired).department_id == before
    assert not ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CORRECTION).exists()


def test_salary_correction_needs_the_manage_salary_right(hired: Employee) -> None:
    hr = _user("HR", "corr_hr_salary")  # manages employees, but may not manage salary
    assert corrections.can_correct(hr, hired, "salary") is False
    assert corrections.can_correct(hr, hired, "department") is True


def test_salary_correction_by_admin_saves(hired: Employee) -> None:
    admin = _user("Admin", "corr_admin_salary")
    assert corrections.can_correct(admin, hired, "salary") is True
    record = corrections.record_for(hired, "salary", None)
    assert record is not None
    result = corrections.save(
        admin,
        hired,
        "salary",
        record,
        _post({"old": corrections.shown_text(record, "salary"), "reason": "Тохироо", "amount": "2,600,000"}),
    )
    assert result.ok is True
    assert result.text == "2,600,000₮"
    assert ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CORRECTION, sensitive=True).exists()


def test_setting_off_turns_corrections_off(hired: Employee) -> None:
    hr = _user("HR", "corr_hr_off")
    settings = CompanySettings.get()
    settings.report_corrections = False
    settings.save()
    assert corrections.enabled() is False
    assert corrections.can_correct(hr, hired, "department") is False


def test_job_record_of_another_employee_is_not_found(hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    other = history.hire(
        hire_values("УБ99112234"), {}, start=timezone.localdate(), job=job_values, salary=None, by=actor
    )
    other_record = _job(other)
    assert corrections.record_for(hired, "department", other_record.pk) is None
    assert corrections.record_for(hired, "department", None) is None
    assert corrections.record_for(hired, "department", _job(hired).pk) == _job(hired)


def test_stale_old_text_is_a_clash(hired: Employee) -> None:
    hr = _user("HR", "corr_hr_clash")
    dept = macs_writes.save_department("Худалдаа")
    record = _job(hired)
    before = record.department_id
    result = corrections.save(
        hr,
        hired,
        "department",
        record,
        _post({"old": "Хуучин хэлтэс", "reason": "Шалтгаан", "department": str(dept.pk)}),
    )
    assert result.ok is False
    assert result.error == CLASH
    assert _job(hired).department_id == before
