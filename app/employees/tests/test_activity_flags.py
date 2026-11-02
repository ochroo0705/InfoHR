"""Audit of the activity-log flags (audit-logs task 11).

Every writer of ActivityEntry must set the flags the visibility rules rely on:
- an entry that quotes a salary, bank, insurance or tax value is sensitive=True;
- an entry about personal-tab data is personal=True;
- leave and setup entries stay unflagged.
A wrongly unflagged entry would show salary data to users without macs.view_salary.
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.test import RequestFactory
from django.utils import timezone
from leave.models import LeaveSettings, LeaveTypeExt
from leave.services import ledger
from leave.services import records as leave_records
from leave.services.records import Draft
from macs.models import AcademicDegree, Bank, City, District, EducationLevel, FamilyRelation, LeaveTypeRow

from employees import views as employee_views
from employees.forms import EmployeeForm
from employees.models import PERSONAL_FIELDS, PERSONAL_LOG_FIELDS, ActivityEntry, Employee
from employees.services import events, history, logins, macs_writes, records, setup
from employees.services import personal_writes as pw
from employees.services.records import SALARY_FIELDS
from employees.staff_import.run import run_import
from employees.tests.helpers import record_signed
from employees.tests.test_staff_import_run import make_draft, person

from .conftest import hire_values, named

# Labels of the salary and insurance columns, as the activity log writes them (plus the salary line of events).
SALARY_LABELS = {
    str(Employee._meta.get_field(name).verbose_name)  # type: ignore[union-attr]
    for name in SALARY_FIELDS
} | {"Үндсэн цалин"}
# A salary figure as the log writes it: grouped (2,500,000) or a bare run of six or more digits.
FIGURE = re.compile(r"\d{1,3}(?:,\d{3})+|\d{6,}")


def quotes_salary(entry: ActivityEntry) -> bool:
    if any(change.get("field") in SALARY_LABELS for change in entry.changes):
        return True
    text = " ".join([entry.message] + [str(c.get(k, "")) for c in entry.changes for k in ("old", "new")])
    return FIGURE.search(text) is not None


def _last_id() -> int:
    return ActivityEntry.objects.order_by("-pk").values_list("pk", flat=True).first() or 0


def _since(last_id: int) -> list[ActivityEntry]:
    return list(ActivityEntry.objects.filter(pk__gt=last_id).order_by("pk"))


def _hire(actor: User, job_values: dict[str, Any], register_no: str, salary: Decimal | None) -> Employee:
    return history.hire(hire_values(register_no), {}, start=date(2026, 1, 5), job=job_values, salary=salary, by=actor)


# --- salary-bearing flows -------------------------------------------------------------------------------------------


def flow_hire_with_salary(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    mark = _last_id()
    _hire(actor, job_values, "УБ10000001", Decimal("2500000"))
    return _since(mark)


def flow_salary_change(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000002", Decimal("2500000"))
    mark = _last_id()
    events.record(
        emp,
        type="salary_change",
        effective=date(2026, 3, 1),
        changes={},
        salary=Decimal("2800000"),
        reason="",
        note="",
        by=actor,
    )
    return _since(mark)


def flow_cancel_salary_change(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000010", Decimal("2500000"))
    # Only a still-scheduled applied change can be cancelled (events.cancel), so it starts in the future.
    event = events.record(
        emp,
        type="salary_change",
        effective=timezone.localdate() + timedelta(days=30),
        changes={},
        salary=Decimal("2800000"),
        reason="",
        note="",
        by=actor,
    )
    mark = _last_id()
    events.cancel(event, reason="Алдаа гарсан", by=actor)
    return _since(mark)


def flow_correct_salary(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000011", Decimal("2500000"))
    record = emp.salary_records.get()  # the hire writes exactly one salary period
    mark = _last_id()
    history.correct_salary(record, amount=Decimal("2600000"), reason="Алдаа засав", by=actor)
    return _since(mark)


def flow_promotion_with_salary(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    """A job change that needs a signed order and carries a salary: the order and both log lines."""
    emp = _hire(actor, job_values, "УБ10000003", Decimal("2500000"))
    senior = macs_writes.save_position("Ахлах нягтлан")
    mark = _last_id()
    record_signed(
        emp,
        type="promotion",
        effective=date(2026, 4, 1),
        changes={"position": senior},
        salary=Decimal("3000000"),
        reason="",
        note="",
        by=actor,
    )
    return _since(mark)


def flow_salary_insurance_edit(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000004", None)
    mark = _last_id()
    records.update_salary_insurance(emp, {"social_insurance_no": "НД-1234", "taxpayer_no": "TX-77"}, actor)
    return _since(mark)


def flow_staff_import_with_salary(actor: User) -> list[ActivityEntry]:
    named(Bank, "Хаан банк")  # the import matches the bank by name; an unknown one rejects the row
    mark = _last_id()
    draft = make_draft([person(bank="Хаан банк", account_no="5001234567", taxpayer_no="TX1", base_salary=2500000)])
    run_import(draft, by=actor, allow_salary=True)
    return _since(mark)


# --- personal-tab flows ---------------------------------------------------------------------------------------------


def flow_personal_field_save(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000005", None)
    level = macs_writes.save_list_entry(EducationLevel, {"name": "Бакалавр боловсрол"})
    degree = macs_writes.save_list_entry(AcademicDegree, {"name": "Магистрын зэрэг"})
    mark = _last_id()
    records.update_employee(emp, {"clan_name": "Хонгор"}, actor)
    records.update_employee(emp, {"education_level": level, "academic_degree": degree}, actor)
    return _since(mark)


def flow_birth_place(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000006", None)
    city = macs_writes.save_list_entry(City, {"name": "Дархан-Уул"})
    district = macs_writes.save_list_entry(District, {"name": "Дархан", "city": city})
    mark = _last_id()
    records.set_birth_place(emp, city, district, "Сумын төв", actor)
    return _since(mark)


def flow_personal_list(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000007", None)
    relation = FamilyRelation.objects.create(name="Хүү", fm_type="son")
    values = {"relation_id": relation.pk, "given_name": "Болд", "surname": "Бат", "job": "Багш"}
    mark = _last_id()
    key = pw.add("family", emp, values, {}, actor)
    loaded = pw.load("family", emp, key)
    assert loaded is not None
    pw.update("family", emp, key, loaded, {**values, "surname": "Оюун"}, {}, actor)
    loaded = pw.load("family", emp, key)
    assert loaded is not None
    pw.delete("family", emp, key, loaded, actor)
    return _since(mark)


# --- leave and setup flows (unflagged) ------------------------------------------------------------------------------


def flow_leave(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000008", None)
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    annual = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=annual, uses_annual_balance=True, is_paid=True)
    mark = _last_id()
    ledger.manual_grant(emp, date(2026, 3, 1), date(2027, 2, 28), 20, "тест", actor)
    leave_records.record(Draft(emp, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, date(2026, 10, 14))
    return _since(mark)


def flow_setup_and_login(actor: User, job_values: dict[str, Any]) -> list[ActivityEntry]:
    emp = _hire(actor, job_values, "УБ10000009", None)
    mark = _last_id()
    setup.toggle(emp, "contract", actor)
    logins.create_login(emp, "saraa.b", by=actor)
    return _since(mark)


# --- tests ----------------------------------------------------------------------------------------------------------


def _assert_salary_quotes_flagged(entries: list[ActivityEntry]) -> None:
    quoting = [e for e in entries if quotes_salary(e)]
    assert quoting, "the flow was expected to log a salary figure"
    unflagged = [e.message for e in quoting if not e.sensitive]
    assert unflagged == []


@pytest.mark.django_db
def test_hire_with_salary_is_sensitive(actor: User, job_values: dict[str, Any]) -> None:
    _assert_salary_quotes_flagged(flow_hire_with_salary(actor, job_values))


@pytest.mark.django_db
def test_salary_change_is_sensitive(actor: User, job_values: dict[str, Any]) -> None:
    _assert_salary_quotes_flagged(flow_salary_change(actor, job_values))


@pytest.mark.django_db
def test_cancel_salary_change_is_sensitive(actor: User, job_values: dict[str, Any]) -> None:
    _assert_salary_quotes_flagged(flow_cancel_salary_change(actor, job_values))


@pytest.mark.django_db
def test_correct_salary_is_sensitive(actor: User, job_values: dict[str, Any]) -> None:
    _assert_salary_quotes_flagged(flow_correct_salary(actor, job_values))


@pytest.mark.django_db
def test_promotion_with_salary_flags_only_the_salary_line(actor: User, job_values: dict[str, Any]) -> None:
    entries = flow_promotion_with_salary(actor, job_values)
    _assert_salary_quotes_flagged(entries)
    job_only = [e for e in entries if not quotes_salary(e)]
    assert job_only and all(not e.sensitive and not e.personal for e in job_only)


@pytest.mark.django_db
def test_salary_insurance_edit_is_sensitive(actor: User, job_values: dict[str, Any]) -> None:
    _assert_salary_quotes_flagged(flow_salary_insurance_edit(actor, job_values))


@pytest.mark.django_db
def test_staff_import_with_salary_columns_is_sensitive(actor: User) -> None:
    _assert_salary_quotes_flagged(flow_staff_import_with_salary(actor))


@pytest.mark.django_db
def test_personal_field_save_is_personal(actor: User, job_values: dict[str, Any]) -> None:
    entries = flow_personal_field_save(actor, job_values)
    assert entries and all(e.personal for e in entries)


@pytest.mark.django_db
def test_birth_place_is_personal(actor: User, job_values: dict[str, Any]) -> None:
    entries = flow_birth_place(actor, job_values)
    assert entries and all(e.personal for e in entries)


@pytest.mark.django_db
def test_personal_list_add_edit_delete_is_personal(actor: User, job_values: dict[str, Any]) -> None:
    entries = flow_personal_list(actor, job_values)
    assert len(entries) == 3 and all(e.personal for e in entries)


@pytest.mark.django_db
def test_leave_and_setup_entries_stay_unflagged(actor: User, job_values: dict[str, Any]) -> None:
    entries = flow_leave(actor, job_values) + flow_setup_and_login(actor, job_values)
    assert entries
    assert all(not e.sensitive and not e.personal for e in entries)


@pytest.mark.django_db
def test_no_entry_quotes_salary_unflagged(actor: User, job_values: dict[str, Any]) -> None:
    """After every flow above, no entry that quotes a salary, bank or insurance value is unflagged."""
    flow_hire_with_salary(actor, job_values)
    flow_salary_change(actor, job_values)
    flow_promotion_with_salary(actor, job_values)
    flow_salary_insurance_edit(actor, job_values)
    flow_staff_import_with_salary(actor)
    flow_cancel_salary_change(actor, job_values)
    flow_correct_salary(actor, job_values)
    flow_personal_field_save(actor, job_values)
    flow_birth_place(actor, job_values)
    flow_personal_list(actor, job_values)
    flow_leave(actor, job_values)
    flow_setup_and_login(actor, job_values)
    leaked = [e.message for e in ActivityEntry.objects.all() if quotes_salary(e) and not e.sensitive]
    assert leaked == []


def test_personal_log_fields_do_not_change_permissions(actor: User, job_values: dict[str, Any]) -> None:
    """The education fields are logged as personal but are not hidden by the permission rules: a user without
    view_personal still sees them on the Ажил form, exactly as before PERSONAL_LOG_FIELDS existed."""
    assert "education_level" not in PERSONAL_FIELDS and "academic_degree" not in PERSONAL_FIELDS
    assert {"education_level", "academic_degree"} <= PERSONAL_LOG_FIELDS
    assert PERSONAL_FIELDS <= PERSONAL_LOG_FIELDS
    emp = _hire(actor, job_values, "УБ10000012", None)
    viewer = User.objects.create_user("no_personal_view", password="x-long-pass-123")  # noqa: S106
    request = RequestFactory().get("/")
    request.user = viewer
    form = employee_views._employee_form(request, emp)
    full = set(EmployeeForm(employee=emp).fields)
    assert set(form.fields) == full - PERSONAL_FIELDS
    assert {"education_level", "academic_degree"} <= set(form.fields)
