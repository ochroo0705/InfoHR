"""The checklist actions the Django views and the API share (checklists/services/actions.py)."""

from datetime import date, timedelta

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.http import Http404
from django.utils import timezone
from employees.services import macs_writes
from macs.models import Employee

from checklists import access
from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask, ChecklistTemplate
from checklists.services import actions, lifecycle, owners

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
LAST_DAY = date(2026, 11, 30)
HAND_OVER = "Ажлаа хүлээлгэн өгөх"  # owner: direct manager
ASSETS = "Эд хөрөнгө, тоног төхөөрөмж буцаах"  # owner: HR
FINAL_PAY = "Эцсийн тооцоо шалгах"  # owner: Accountant
NO_TEMPLATE = "Ажлаас гарах жагсаалтын загвар байхгүй байна."
BAD_DATE = "Сүүлийн ажлын өдрийг оруулна уу."


@pytest.fixture
def day() -> date:
    return timezone.localdate()


def _user(name: str, role: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.clear()
    user.groups.add(Group.objects.get(name=role))
    return user


def _start(employee: Employee, actor: User) -> Checklist:
    checklist = lifecycle.start(employee, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    return checklist


def _task(checklist: Checklist, title: str) -> ChecklistTask:
    return checklist.tasks.get(title=title)


def _limited(name: str, role: str) -> User:
    """A user of `role` whose data scope admits only another department, so `hired` is not visible to them."""
    user = _user(name, role)
    other = macs_writes.save_department("Бусад хэлтэс")  # short: the department name column holds 25 characters
    AccessScope.objects.create(user=user, limited=True, department_ids=[other.pk])
    return user


# untick_for


def test_untick_for_without_manage_right_is_404(hired: Employee, actor: User, day: date) -> None:
    task = _task(_start(hired, actor), FINAL_PAY)
    lifecycle.tick(task, by=actor)
    accountant = _user("acc_untick_action", roles.ACCOUNTANT)  # owns the task, may not manage employees
    with pytest.raises(Http404):
        actions.untick_for(accountant, task.pk, day)
    task.refresh_from_db()
    assert task.done_at is not None


def test_untick_for_employee_outside_scope_is_404(hired: Employee, actor: User, day: date) -> None:
    task = _task(_start(hired, actor), FINAL_PAY)
    lifecycle.tick(task, by=actor)
    limited = _limited("limited_untick_action", roles.HR)
    with pytest.raises(Http404):
        actions.untick_for(limited, task.pk, day)
    task.refresh_from_db()
    assert task.done_at is not None


def test_untick_for_checklist_user_cannot_view_is_404(
    hired: Employee, actor: User, day: date, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(_start(hired, actor), FINAL_PAY)
    lifecycle.tick(task, by=actor)
    hr = _user("hr_untick_view", roles.HR)
    # HR may see the employee and untick, so only the view check is left to refuse: force that answer.
    monkeypatch.setattr(access, "can_view", lambda user, checklist, when: False)
    with pytest.raises(Http404):
        actions.untick_for(hr, task.pk, day)
    task.refresh_from_db()
    assert task.done_at is not None


def test_untick_for_manager_unticks(hired: Employee, actor: User, day: date) -> None:
    task = _task(_start(hired, actor), FINAL_PAY)
    lifecycle.tick(task, by=actor)
    hr = _user("hr_untick_ok", roles.HR)
    result = actions.untick_for(hr, task.pk, day)
    assert result.pk == task.pk
    task.refresh_from_db()
    assert task.done_at is None


def test_untick_for_refused_raises_checklist_error(
    hired: Employee, actor: User, day: date, termination: object
) -> None:
    checklist = _start(hired, actor)
    task = _task(checklist, FINAL_PAY)
    lifecycle.tick(task, by=actor)
    Checklist.objects.filter(pk=checklist.pk).update(event=termination, state=ChecklistState.COMPLETED)
    hr = _user("hr_untick_refused", roles.HR)
    with pytest.raises(lifecycle.ChecklistError):
        actions.untick_for(hr, task.pk, day)
    task.refresh_from_db()
    assert task.done_at is not None


# cancel_for


def test_cancel_for_without_manage_right_is_404(hired: Employee, actor: User, day: date) -> None:
    checklist = _start(hired, actor)
    accountant = _user("acc_cancel_action", roles.ACCOUNTANT)  # owns a task, may not manage employees
    with pytest.raises(Http404):
        actions.cancel_for(accountant, checklist.pk, day)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN


def test_cancel_for_checklist_user_cannot_view_is_404(
    hired: Employee, actor: User, day: date, monkeypatch: pytest.MonkeyPatch
) -> None:
    checklist = _start(hired, actor)
    hr = _user("hr_cancel_view", roles.HR)
    monkeypatch.setattr(access, "can_view", lambda user, checklist, when: False)
    with pytest.raises(Http404):
        actions.cancel_for(hr, checklist.pk, day)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN


def test_cancel_for_employee_outside_scope_is_404(hired: Employee, actor: User, day: date) -> None:
    checklist = _start(hired, actor)
    limited = _limited("limited_cancel_action", roles.HR)
    with pytest.raises(Http404):
        actions.cancel_for(limited, checklist.pk, day)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN


def test_cancel_for_manager_cancels(hired: Employee, actor: User, day: date) -> None:
    checklist = _start(hired, actor)
    hr = _user("hr_cancel_ok", roles.HR)
    result = actions.cancel_for(hr, checklist.pk, day)
    assert result.pk == checklist.pk
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.CANCELLED


def test_cancel_for_refused_raises_checklist_error(
    hired: Employee, actor: User, day: date, termination: object
) -> None:
    checklist = _start(hired, actor)
    Checklist.objects.filter(pk=checklist.pk).update(event=termination)
    hr = _user("hr_cancel_refused", roles.HR)
    with pytest.raises(lifecycle.ChecklistError):
        actions.cancel_for(hr, checklist.pk, day)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN


# start_offboarding


def test_start_offboarding_invisible_employee_is_404(hired: Employee) -> None:
    limited = _limited("limited_start_action", roles.HR)
    with pytest.raises(Http404):
        actions.start_offboarding(limited, hired.pk, LAST_DAY.isoformat())
    assert not Checklist.objects.exists()


def test_start_offboarding_without_start_right_is_404(hired: Employee) -> None:
    accountant = _user("acc_start_action", roles.ACCOUNTANT)  # may see the employee, may not record a termination
    with pytest.raises(Http404):
        actions.start_offboarding(accountant, hired.pk, LAST_DAY.isoformat())
    assert not Checklist.objects.exists()


@pytest.mark.parametrize("text", ["not-a-date", ""])
def test_start_offboarding_bad_date_is_action_error(hired: Employee, text: str) -> None:
    hr = _user("hr_start_bad_date", roles.HR)
    with pytest.raises(actions.ActionError) as error:
        actions.start_offboarding(hr, hired.pk, text)
    assert error.value.message == BAD_DATE
    assert not Checklist.objects.exists()


def test_start_offboarding_without_template_is_action_error(hired: Employee) -> None:
    ChecklistTemplate.objects.update(active=False)
    hr = _user("hr_start_no_template", roles.HR)
    with pytest.raises(actions.ActionError) as error:
        actions.start_offboarding(hr, hired.pk, LAST_DAY.isoformat())
    assert error.value.message == NO_TEMPLATE
    assert not Checklist.objects.exists()


def test_start_offboarding_returns_the_employee(hired: Employee) -> None:
    hr = _user("hr_start_ok", roles.HR)
    result = actions.start_offboarding(hr, hired.pk, LAST_DAY.isoformat())
    assert result.pk == hired.pk
    checklist = Checklist.objects.get(employee=hired)
    assert checklist.anchor_day == LAST_DAY and checklist.created_by == hr


# mine_rows


def test_mine_rows_empty_for_user_without_tasks(day: date) -> None:
    plain = _user("plain_mine_action", roles.EMPLOYEE)
    assert actions.mine_rows(plain, day) == []


def test_mine_rows_lists_owned_tasks_with_overdue(hired: Employee, actor: User, day: date) -> None:
    checklist = _start(hired, actor)
    assets = _task(checklist, ASSETS)
    ChecklistTask.objects.filter(pk=assets.pk).update(due_on=day - timedelta(days=2))
    hr = _user("hr_mine_action", roles.HR)  # HR members own the assets task
    rows = actions.mine_rows(hr, day)
    assert [row.task_id for row in rows] == [task.pk for task in owners.my_tasks(hr, day)]
    row = next(row for row in rows if row.task_id == assets.pk)
    assert row.title == ASSETS
    assert row.employee == hired.full_name
    assert row.kind_label == checklist.get_kind_display()
    assert row.due_on == day - timedelta(days=2)
    assert row.overdue is True


def test_mine_rows_not_overdue_when_due_later(hired: Employee, actor: User, day: date) -> None:
    assets = _task(_start(hired, actor), ASSETS)
    ChecklistTask.objects.filter(pk=assets.pk).update(due_on=day + timedelta(days=5))
    hr = _user("hr_mine_later", roles.HR)
    row = next(row for row in actions.mine_rows(hr, day) if row.task_id == assets.pk)
    assert row.overdue is False
