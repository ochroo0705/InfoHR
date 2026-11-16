"""The correction editor of a report cell: the reports:correct view (reports.corrections, D-080 phase 4)."""

from collections.abc import Callable
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, CompanySettings, Employee, JobRecord
from employees.services import history, macs_writes, report_corrections

from reports import corrections
from reports.cell_edit import CLASH

pytestmark = pytest.mark.django_db


def _url(person: int, key: str, record: int | None = None) -> str:
    query = {"person": person, "key": key}
    if record is not None:
        query["record"] = record
    return "/reports/correct/?" + urlencode(query)


def _job(employee: Employee) -> JobRecord:
    record = history.job_on(employee, timezone.localdate())
    assert record is not None
    return record


def test_hr_gets_the_department_editor_with_the_reason_box(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    response = client.get(_url(hired.pk, "department", _job(hired).pk))
    assert response.status_code == 200
    page = response.content.decode()
    assert "data-cell-form" in page
    assert 'name="department"' in page
    assert 'name="old" value="Санхүү"' in page
    assert 'name="reason"' in page
    assert "Анхны утгыг засна." in page


def test_accountant_gets_the_salary_editor(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant")  # may manage salary, not employees
    response = client.get(_url(hired.pk, "salary"))
    assert response.status_code == 200
    page = response.content.decode()
    assert 'name="amount"' in page
    assert 'name="reason"' in page


def test_hr_without_salary_right_gets_403_for_salary(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    assert client.get(_url(hired.pk, "salary")).status_code == 403


def test_viewer_gets_403_for_a_job_field(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant")  # may not manage employees
    assert client.get(_url(hired.pk, "department", _job(hired).pk)).status_code == 403


def test_setting_off_gets_403(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    settings = CompanySettings.get()
    settings.report_corrections = False
    settings.save()
    assert client.get(_url(hired.pk, "department", _job(hired).pk)).status_code == 403


def test_unknown_key_and_foreign_record_are_404(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    assert client.get(_url(hired.pk, "register_no", _job(hired).pk)).status_code == 404
    assert client.get(_url(hired.pk, "department", 999_999)).status_code == 404
    assert client.get(_url(hired.pk, "department")).status_code == 404  # a job key needs its record


def test_post_saves_and_returns_the_new_text(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    response = client.post(
        _url(hired.pk, "department", record.pk),
        {"old": "Санхүү", "reason": "Бичлэгийн алдаа", "department": str(dept.pk)},
    )
    assert response.status_code == 200
    assert "<span data-cell-value>Үйлдвэрлэл</span>" in response.content.decode()
    assert _job(hired).department_id == dept.pk
    assert ActivityEntry.objects.filter(
        employee=hired, kind=ActivityKind.CORRECTION, message="Засвар: Бичлэгийн алдаа"
    ).exists()


def test_blank_reason_returns_the_editor_with_an_error(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    dept = macs_writes.save_department("Захиргаа")
    record = _job(hired)
    response = client.post(
        _url(hired.pk, "department", record.pk),
        {"old": "Санхүү", "reason": "  ", "department": str(dept.pk)},
    )
    assert response.status_code == 200
    page = response.content.decode()
    assert "data-cell-error" in page
    assert corrections.NEEDS_REASON in page
    assert _job(hired).department_id != dept.pk
    assert not ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CORRECTION).exists()


def test_clash_returns_the_current_text_in_a_fresh_editor(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    dept = macs_writes.save_department("Худалдаа")
    record = _job(hired)
    response = client.post(
        _url(hired.pk, "department", record.pk),
        {"old": "Хуучин хэлтэс", "reason": "Шалтгаан", "department": str(dept.pk)},
    )
    assert response.status_code == 200
    page = response.content.decode()
    assert CLASH in page
    assert 'name="old" value="Санхүү"' in page  # the text stored now
    assert _job(hired).department_id != dept.pk


def test_staff_list_department_cell_opens_the_correction(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    page = client.get("/reports/staff-list/?cols=name&cols=department").content.decode()
    job = _job(hired)
    assert (
        f'data-correct data-edit="/reports/correct/?person={hired.pk}&amp;key=department&amp;record={job.pk}"' in page
    )


def test_staff_list_shows_no_correction_when_the_setting_is_off(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    settings = CompanySettings.get()
    settings.report_corrections = False
    settings.save()
    login_as(client, "HR")
    page = client.get("/reports/staff-list/?cols=name&cols=department&cols=position").content.decode()
    assert "data-correct" not in page


def test_salary_cell_is_correctable_only_with_the_manage_salary_right(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "Admin")  # manages employees and salary
    page = client.get("/reports/staff-list/?cols=name&cols=salary").content.decode()
    assert f'data-correct data-edit="/reports/correct/?person={hired.pk}&amp;key=salary"' in page


def test_hr_who_sees_salary_but_may_not_manage_it_gets_no_salary_correction(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    hr = login_as(client, "HR")  # manages employees, not salary
    hr.user_permissions.add(Permission.objects.get(codename="view_salary", content_type__app_label="macs"))
    page = client.get("/reports/staff-list/?cols=name&cols=department&cols=salary").content.decode()
    assert "Үндсэн цалин" in page  # the salary column is shown, so the absence below is real
    assert "key=department&amp;record=" in page  # the department cell is still correctable
    assert "key=salary" not in page


def test_403_comes_before_the_record_lookup(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant")  # may not manage employees: a missing record is still a 403
    assert client.get(_url(hired.pk, "department", 999_999)).status_code == 403


def test_a_record_not_in_force_today_gets_only_the_message(
    client: Client, login_as: Callable[..., User], hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(client, "HR")
    record = _job(hired)
    other_row = SimpleNamespace(pk=record.pk + 1)  # another row is today's
    monkeypatch.setattr(history, "job_on", lambda employee, day: other_row)
    page = client.get(_url(hired.pk, "department", record.pk)).content.decode()
    assert report_corrections.NOT_CURRENT in page
    assert "data-cell-error" in page
    assert 'name="reason"' not in page
    assert 'name="department"' not in page


def test_a_not_current_record_is_not_written_on_post(
    client: Client, login_as: Callable[..., User], hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(client, "HR")
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    before = record.department_id
    monkeypatch.setattr(history, "job_on", lambda employee, day: SimpleNamespace(pk=record.pk + 1))
    response = client.post(
        _url(hired.pk, "department", record.pk),
        {"old": "Санхүү", "reason": "Шалтгаан", "department": str(dept.pk)},
    )
    assert response.status_code == 200
    assert report_corrections.NOT_CURRENT in response.content.decode()
    assert JobRecord.objects.get(pk=record.pk).department_id == before
    assert not ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CORRECTION).exists()


def test_a_scheduled_change_gets_only_the_message_and_nothing_is_written(
    client: Client, login_as: Callable[..., User], hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(client, "HR")
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    before = record.department_id
    monkeypatch.setattr(report_corrections, "_scheduled", lambda event, today: True)
    page = client.get(_url(hired.pk, "department", record.pk)).content.decode()
    assert report_corrections.SCHEDULED in page
    assert 'name="reason"' not in page
    response = client.post(
        _url(hired.pk, "department", record.pk),
        {"old": "Санхүү", "reason": "Шалтгаан", "department": str(dept.pk)},
    )
    assert report_corrections.SCHEDULED in response.content.decode()
    assert _job(hired).department_id == before
    assert not ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CORRECTION).exists()
