"""The request-free correction editor service (cell_editors.open_correct, save_correct) behind the React correction
editors. It runs the same checks in the same order as the reports:correct view."""

from types import SimpleNamespace

import pytest
from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, CompanySettings, Employee, JobRecord
from employees.services import history, macs_writes, report_corrections

from reports import corrections
from reports.services import cell_editors as svc

pytestmark = pytest.mark.django_db

NOTE = "Анхны утгыг засна. Шилжүүлэх, цалин нэмэх бол тушаалаар."


def _job(employee: Employee) -> JobRecord:
    record = history.job_on(employee, timezone.localdate())
    assert record is not None
    return record


def _shown(employee: Employee, key: str) -> str:
    return corrections.shown_text(
        _job(employee) if key != "salary" else history.salary_on(employee, timezone.localdate()), key
    )


def _not_current(monkeypatch: pytest.MonkeyPatch, record: JobRecord) -> None:
    """Another job row is today's, so this one may not be corrected now."""
    monkeypatch.setattr(history, "job_on", lambda employee, day: SimpleNamespace(pk=record.pk + 1))


def test_department_position_manager_are_choice_editors(hr_user: User, hired: Employee) -> None:
    macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    for key in ("department", "position", "manager"):
        model = svc.open_correct(hr_user, hired.pk, key, record.pk)
        assert model.kind == "choice"
        assert model.name == key
        assert model.reason is True
        assert model.note == NOTE
        assert model.old == corrections.shown_text(record, key)
        assert model.blocked == ""
        assert svc.EditorChoice(value="", label=model.choices[0].label) in model.choices
    department = svc.open_correct(hr_user, hired.pk, "department", record.pk)
    assert "Үйлдвэрлэл" in [option.label for option in department.choices]
    assert len(department.choices) > 1


def test_salary_editor_is_a_number_with_the_note(accountant_user: User, hired: Employee) -> None:
    model = svc.open_correct(accountant_user, hired.pk, "salary", None)
    assert model.kind == "number"
    assert model.name == "amount"
    assert model.reason is True
    assert model.note == NOTE
    assert model.old == _shown(hired, "salary")
    assert model.blocked == ""


def test_note_is_the_template_text(hr_user: User, hired: Employee) -> None:
    model = svc.open_correct(hr_user, hired.pk, "position", _job(hired).pk)
    assert model.note == "Анхны утгыг засна. Шилжүүлэх, цалин нэмэх бол тушаалаар."


def test_record_not_in_force_today_is_blocked_with_no_inputs(
    hr_user: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _job(hired)
    _not_current(monkeypatch, record)
    model = svc.open_correct(hr_user, hired.pk, "department", record.pk)
    assert model.blocked == report_corrections.NOT_CURRENT
    assert model.choices == []
    assert model.kind == "choice"
    assert model.reason is False
    assert model.note == ""


def test_scheduled_change_is_blocked_with_no_inputs(
    hr_user: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_corrections, "_scheduled", lambda event, today: True)
    model = svc.open_correct(hr_user, hired.pk, "department", _job(hired).pk)
    assert model.blocked == report_corrections.SCHEDULED
    assert model.choices == []
    assert model.reason is False
    assert model.note == ""


def test_setting_off_is_403(hr_user: User, hired: Employee) -> None:
    settings = CompanySettings.get()
    settings.report_corrections = False
    settings.save()
    with pytest.raises(PermissionDenied):
        svc.open_correct(hr_user, hired.pk, "department", _job(hired).pk)


def test_salary_without_the_salary_right_is_403(hr_user: User, hired: Employee) -> None:
    with pytest.raises(PermissionDenied):
        svc.open_correct(hr_user, hired.pk, "salary", None)


def test_job_key_without_a_record_is_404(hr_user: User, hired: Employee) -> None:
    with pytest.raises(Http404):
        svc.open_correct(hr_user, hired.pk, "department", None)


def test_unknown_key_unknown_record_and_unseen_person_are_404(hr_user: User, hired: Employee) -> None:
    with pytest.raises(Http404):
        svc.open_correct(hr_user, hired.pk, "register_no", _job(hired).pk)
    with pytest.raises(Http404):
        svc.open_correct(hr_user, hired.pk, "department", 999_999)
    with pytest.raises(Http404):
        svc.open_correct(hr_user, 999_999, "department", _job(hired).pk)


def test_403_comes_before_the_record_lookup(accountant_user: User, hired: Employee) -> None:
    # the accountant may not manage employees: a missing record is still a 403, as in the view
    with pytest.raises(PermissionDenied):
        svc.open_correct(accountant_user, hired.pk, "department", 999_999)


def test_save_with_a_blank_reason_needs_a_reason_and_writes_nothing(hr_user: User, hired: Employee) -> None:
    dept = macs_writes.save_department("Захиргаа")
    record = _job(hired)
    before = record.department_id
    result = svc.save_correct(
        hr_user, hired.pk, "department", record.pk, str(dept.pk), _shown(hired, "department"), "  "
    )
    assert result.ok is False
    assert result.error == corrections.NEEDS_REASON
    assert result.editor is not None
    assert result.editor.error == corrections.NEEDS_REASON
    assert _job(hired).department_id == before
    assert not ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CORRECTION).exists()


def test_save_with_a_201_character_reason_is_too_long(hr_user: User, hired: Employee) -> None:
    dept = macs_writes.save_department("Захиргаа")
    record = _job(hired)
    before = record.department_id
    result = svc.save_correct(
        hr_user, hired.pk, "department", record.pk, str(dept.pk), _shown(hired, "department"), "x" * 201
    )
    assert result.ok is False
    assert result.error == corrections.TOO_LONG_REASON
    assert _job(hired).department_id == before


def test_save_with_a_changed_old_text_is_a_clash_with_the_current_text(hr_user: User, hired: Employee) -> None:
    dept = macs_writes.save_department("Худалдаа")
    record = _job(hired)
    before = record.department_id
    result = svc.save_correct(hr_user, hired.pk, "department", record.pk, str(dept.pk), "Хуучин хэлтэс", "Шалтгаан")
    assert result.ok is False
    assert result.error == svc.CLASH
    assert result.editor is not None
    assert result.editor.old == "Санхүү"
    assert result.editor.error == svc.CLASH
    assert _job(hired).department_id == before


def test_retry_after_a_clash_with_the_fresh_text_succeeds(hr_user: User, hired: Employee) -> None:
    dept = macs_writes.save_department("Худалдаа")
    record = _job(hired)
    clash = svc.save_correct(hr_user, hired.pk, "department", record.pk, str(dept.pk), "Хуучин", "Шалтгаан")
    assert clash.editor is not None
    retry = svc.save_correct(hr_user, hired.pk, "department", record.pk, str(dept.pk), clash.editor.old, "Шалтгаан")
    assert retry.ok is True
    assert retry.text == "Худалдаа"


def test_save_ok_returns_the_new_text_and_logs_the_correction(hr_user: User, hired: Employee) -> None:
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    result = svc.save_correct(
        hr_user, hired.pk, "department", record.pk, str(dept.pk), _shown(hired, "department"), "Бичлэгийн алдаа"
    )
    assert result.ok is True
    assert result.text == "Үйлдвэрлэл"
    assert result.editor is None
    assert _job(hired).department_id == dept.pk
    assert ActivityEntry.objects.filter(
        employee=hired, kind=ActivityKind.CORRECTION, message="Засвар: Бичлэгийн алдаа"
    ).exists()


def test_save_salary_ok_writes_the_new_amount(accountant_user: User, hired: Employee) -> None:
    result = svc.save_correct(
        accountant_user, hired.pk, "salary", None, "2600000", _shown(hired, "salary"), "Бичлэгийн алдаа"
    )
    assert result.ok is True
    salary = history.salary_on(hired, timezone.localdate())
    assert salary is not None
    assert result.text == corrections.shown_text(salary, "salary")
    assert salary.base_salary == 2_600_000


def test_blocked_save_returns_the_message_and_writes_nothing(
    hr_user: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    before = record.department_id
    old = _shown(hired, "department")
    _not_current(monkeypatch, record)
    result = svc.save_correct(hr_user, hired.pk, "department", record.pk, str(dept.pk), old, "Шалтгаан")
    assert result.ok is False
    assert result.error == report_corrections.NOT_CURRENT
    assert result.editor is not None
    assert result.editor.blocked == report_corrections.NOT_CURRENT
    assert result.editor.choices == []
    monkeypatch.undo()
    assert JobRecord.objects.get(pk=record.pk).department_id == before
    assert not ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CORRECTION).exists()


def test_forged_key_or_missing_permission_writes_nothing(hr_user: User, accountant_user: User, hired: Employee) -> None:
    record = _job(hired)
    before = record.department_id
    with pytest.raises(Http404):
        svc.save_correct(hr_user, hired.pk, "register_no", record.pk, "1", "", "Шалтгаан")
    with pytest.raises(PermissionDenied):
        svc.save_correct(accountant_user, hired.pk, "department", record.pk, "1", "", "Шалтгаан")
    with pytest.raises(PermissionDenied):
        svc.save_correct(hr_user, hired.pk, "salary", None, "1", "", "Шалтгаан")
    assert JobRecord.objects.get(pk=record.pk).department_id == before
    assert not ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CORRECTION).exists()
