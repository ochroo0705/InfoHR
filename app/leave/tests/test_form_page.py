"""The leave pop-ups' rules as service calls: the prefill cases of test_leave_prefill.py, the edit and cancel rules,
and the live check, without the pop-up views."""

from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from employees import access as employee_access
from employees import palette as employee_palette
from employees.models import Employee
from macs.models import LeaveAssign, LeaveTypeRow

from leave.forms import LeaveForm
from leave.models import LeaveTypeExt
from leave.services import form_page, records, rows
from leave.services.records import Draft
from leave.tests.conftest import make_employee

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]

T = date(2026, 10, 14)


def _leave_only_user() -> User:
    """May record leave but sees no employee (no employee view right, no own record): all are out of scope."""
    group = Group.objects.create(name="Чөлөө бүртгэгч тест")
    codenames = ("record_leave", "view_leave")
    group.permissions.set(Permission.objects.filter(content_type__app_label="leave", codename__in=codenames))
    u = User.objects.create_user("leave_only", password="x-long-pass-123")  # noqa: S106
    u.groups.add(group)
    return User.objects.get(pk=u.pk)


def _form_data(employee: Employee, leave_type: LeaveTypeRow, start: str, end: str) -> dict[str, str]:
    return {
        "employee": str(employee.pk),
        "leave_type": str(leave_type.pk),
        "start_date": start,
        "end_date": end,
        "note": "",
        "override_reason": "",
    }


def _record(actor: User, employee: Employee, leave_type: LeaveTypeRow, start: date, end: date) -> LeaveAssign:
    return records.record(Draft(employee, leave_type, start, end), actor, T)


def test_employee_outside_scope_is_dropped(actor: User, employee: Employee, annual: LeaveTypeRow) -> None:
    user = _leave_only_user()
    query = {"employee": str(employee.pk), "type": str(annual.pk), "from": "assistant"}
    initial, filled = form_page.add_initial(query, employee_access.visible_employees(user), T)
    assert "employee" not in initial
    assert initial["leave_type"] == annual.pk
    assert filled == ["Төрөл"]


def test_inactive_type_is_dropped(actor: User, employee: Employee) -> None:
    old = LeaveTypeRow.objects.create(name="Хуучин төрөл")
    LeaveTypeExt.objects.create(leave_type=old, uses_annual_balance=False, is_paid=True, is_active=False)
    initial, filled = form_page.add_initial(
        {"type": str(old.pk), "from": "assistant"}, employee_access.visible_employees(actor), T
    )
    assert "leave_type" not in initial
    assert filled == []


def test_date_far_from_today_is_dropped(actor: User) -> None:
    initial, filled = form_page.add_initial(
        {"start": "2046-01-01", "end": "2046-01-03"}, employee_access.visible_employees(actor), T
    )
    assert initial["start_date"] is None
    assert initial["end_date"] is None
    assert filled == []


def test_end_before_start_drops_end(actor: User) -> None:
    initial, filled = form_page.add_initial(
        {"start": "2026-11-06", "end": "2026-11-02"}, employee_access.visible_employees(actor), T
    )
    assert initial["start_date"] == date(2026, 11, 6)
    assert initial["end_date"] is None
    assert filled == ["Эхлэх"]


def test_bad_date_stays_empty_and_is_not_filled(actor: User) -> None:
    initial, filled = form_page.add_initial(
        {"from": "assistant", "start": "2026-13-45"}, employee_access.visible_employees(actor), T
    )
    assert initial["start_date"] is None
    assert filled == []


def test_assisted_lines_for_nothing_filled(actor: User) -> None:
    lines = form_page.assisted_lines(actor, None, [], T)
    assert lines == {
        "person_line": "",
        "filled_line": "Асуултаас юу ч бөглөгдөөгүй. Мэдээллээ өөрөө оруулна уу.",
    }


def test_assisted_lines_name_the_person_and_the_filled_parts(actor: User, employee: Employee) -> None:
    lines = form_page.assisted_lines(actor, employee.pk, ["Ажилтан", "Төрөл"], T)
    assert lines["person_line"].startswith(employee.full_name)
    assert lines["filled_line"] == "Асуултаас бөглөсөн: Ажилтан, Төрөл"


def test_edit_initial_has_the_six_keys(actor: User, employee: Employee, annual: LeaveTypeRow) -> None:
    a = _record(actor, employee, annual, date(2026, 11, 2), date(2026, 11, 3))
    a.comment = "Гэр бүл"
    a.save()
    initial = form_page.edit_initial(a, rows.leave(a.pk))
    assert set(initial) == {"employee", "leave_type", "start_date", "end_date", "note", "override_reason"}
    assert initial["employee"] == employee.pk
    assert initial["leave_type"] == annual.pk
    assert initial["start_date"] == date(2026, 11, 2)
    assert initial["end_date"] == date(2026, 11, 3)
    assert initial["note"] == "Гэр бүл"


def test_check_for_uses_the_leave_own_employee(
    monkeypatch: pytest.MonkeyPatch, actor: User, employee: Employee, annual: LeaveTypeRow
) -> None:
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ22112233")
    a = _record(actor, employee, annual, date(2026, 11, 2), date(2026, 11, 3))
    seen: list[Draft] = []
    monkeypatch.setattr(records, "check", lambda draft, today: seen.append(draft) or records.Check())
    form = LeaveForm(
        _form_data(other, annual, "2026-11-09", "2026-11-10"),
        employees=employee_access.visible_employees(actor),
    )
    assert form_page.check_for(actor, form, a.pk, T) is not None
    assert seen[0].employee.pk == employee.pk  # the leave's employee, not the posted one
    assert seen[0].leave_id == a.pk


def test_check_for_unknown_leave_keeps_the_posted_employee(
    monkeypatch: pytest.MonkeyPatch, actor: User, employee: Employee, annual: LeaveTypeRow
) -> None:
    seen: list[Draft] = []
    monkeypatch.setattr(records, "check", lambda draft, today: seen.append(draft) or records.Check())
    form = LeaveForm(
        _form_data(employee, annual, "2026-11-02", "2026-11-03"),
        employees=employee_access.visible_employees(actor),
    )
    form_page.check_for(actor, form, 99_999_999, T)
    assert seen[0].employee.pk == employee.pk
    assert seen[0].leave_id is None


def test_check_for_invalid_form_is_none(actor: User, employee: Employee, annual: LeaveTypeRow) -> None:
    form = LeaveForm(
        {**_form_data(employee, annual, "2026-11-02", "2026-11-03"), "leave_type": ""},  # no type: the form is invalid
        employees=employee_access.visible_employees(actor),
    )
    assert form_page.check_for(actor, form, None, T) is None


def test_cancel_info_marks_a_started_leave_and_restores_annual(
    actor: User, employee: Employee, annual: LeaveTypeRow, sick: LeaveTypeRow
) -> None:
    started = _record(actor, employee, annual, date(2026, 10, 1), date(2026, 10, 2))
    info = form_page.cancel_info(started, rows.leave(started.pk), T)
    assert info.mistake is True
    assert info.restores_balance is True

    future = _record(actor, employee, sick, date(2026, 11, 2), date(2026, 11, 3))
    info = form_page.cancel_info(future, rows.leave(future.pk), T)
    assert info.mistake is False
    assert info.restores_balance is False


def test_cancel_info_leave_starting_today_is_a_mistake(actor: User, employee: Employee, annual: LeaveTypeRow) -> None:
    a = _record(actor, employee, annual, T, date(2026, 10, 15))
    info = form_page.cancel_info(a, rows.leave(a.pk), T)
    assert info.mistake is True
    assert info.start == T
    assert info.end == date(2026, 10, 15)
    assert info.label == str(annual)


def test_check_for_leave_outside_scope_uses_the_posted_employee(
    monkeypatch: pytest.MonkeyPatch, actor: User, employee: Employee, annual: LeaveTypeRow
) -> None:
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ22112233")
    a = _record(actor, employee, annual, date(2026, 11, 2), date(2026, 11, 3))  # the leave is of `employee`
    visible = Employee.objects.filter(pk=other.pk)  # the asker may see only `other`
    monkeypatch.setattr(employee_access, "visible_employees", lambda user: visible)
    seen: list[Draft] = []
    monkeypatch.setattr(records, "check", lambda draft, today: seen.append(draft) or records.Check())
    form = LeaveForm(_form_data(other, annual, "2026-11-09", "2026-11-10"), employees=visible)
    assert form_page.check_for(actor, form, a.pk, T) is not None
    assert seen[0].employee.pk == other.pk  # nothing about the hidden leave's employee is used
    assert seen[0].leave_id is None


def test_assisted_lines_include_position_and_department(
    monkeypatch: pytest.MonkeyPatch, actor: User, employee: Employee
) -> None:
    hit = employee_palette.PersonHit(employee=employee, left=False, position="Нягтлан", department="Санхүү")
    monkeypatch.setattr(employee_palette, "current", lambda user, pk, today: hit)
    lines = form_page.assisted_lines(actor, employee.pk, ["Ажилтан"], T)
    assert lines["person_line"] == f"{employee.full_name} · Нягтлан · Санхүү"


@pytest.mark.parametrize("pk", [2**31, 10**30, -1])
def test_an_id_outside_the_32_bit_range_is_no_leave(
    actor: User, employee: Employee, annual: LeaveTypeRow, pk: int
) -> None:
    _record(actor, employee, annual, date(2026, 11, 2), date(2026, 11, 3))
    assert form_page.visible_assign(actor, pk) is None


def test_a_huge_leave_id_checks_as_a_new_leave(actor: User, employee: Employee, annual: LeaveTypeRow) -> None:
    form = LeaveForm(
        _form_data(employee, annual, "2026-11-02", "2026-11-03"), employees=employee_access.visible_employees(actor)
    )
    huge = form_page.check_for(actor, form, 10**30, T)
    plain = form_page.check_for(actor, form, None, T)
    assert huge is not None and plain is not None
    assert huge.working_days == plain.working_days
