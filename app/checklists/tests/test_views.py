"""The employee page's offboarding panel and the tick, untick and start views."""

from datetime import date, timedelta

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees.models import ActivityEntry, Employee, EmployeeExt
from employees.services import macs_writes

from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask, ChecklistTemplate
from checklists.services import lifecycle

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
LAST_DAY = date(2026, 11, 30)


def _login(client: Client, role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.clear()
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def _start(employee: Employee, actor: User) -> Checklist:
    checklist = lifecycle.start(employee, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    return checklist


def _task(checklist: Checklist, title: str) -> ChecklistTask:
    return checklist.tasks.get(title=title)


def _detail(employee: Employee) -> str:
    return reverse("employees:detail", args=[employee.pk])


def _body(client: Client, employee: Employee) -> str:
    response = client.get(_detail(employee))
    assert response.status_code == 200
    return response.content.decode()


HAND_OVER = "Ажлаа хүлээлгэн өгөх"  # owner: direct manager
ASSETS = "Эд хөрөнгө, тоног төхөөрөмж буцаах"  # owner: HR
FINAL_PAY = "Эцсийн тооцоо шалгах"  # owner: Accountant


def test_panel_shows_progress_owners_and_buttons_to_hr(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    lifecycle.tick(_task(checklist, HAND_OVER), by=actor)
    _login(client, roles.HR, "hr1")
    body = _body(client, hired)
    assert "Ажлаас гарах жагсаалт" in body
    assert "1 / 5" in body
    assert ASSETS in body
    assert "Шууд удирдлага" in body
    assert reverse("checklists:tick", args=[_task(checklist, ASSETS).pk]) in body  # HR owns the assets task
    assert reverse("checklists:untick", args=[_task(checklist, HAND_OVER).pk]) in body  # HR manages employees
    assert reverse("checklists:tick", args=[_task(checklist, FINAL_PAY).pk]) not in body  # Accountant's task
    assert "Жагсаалт эхлүүлэх" not in body  # already started


def test_panel_marks_admin_fallback_when_no_owner_is_found(client: Client, hired: Employee, actor: User) -> None:
    _start(hired, actor)  # the hired employee has no manager, so the hand-over task has no owner
    _login(client, roles.HR, "hr1")
    assert "Админ (эзэн олдсонгүй)" in _body(client, hired)


def test_start_button_when_none_started(client: Client, hired: Employee) -> None:
    _login(client, roles.HR, "hr1")
    body = _body(client, hired)
    assert "Жагсаалт эхлүүлэх" in body
    assert 'name="anchor_day"' in body
    assert reverse("checklists:start", args=[hired.pk]) in body


def test_no_panel_without_template_or_checklist(client: Client, hired: Employee) -> None:
    ChecklistTemplate.objects.update(active=False)
    _login(client, roles.HR, "hr1")
    assert "Ажлаас гарах жагсаалт" not in _body(client, hired)


def test_no_start_button_without_manage_right(client: Client, hired: Employee) -> None:
    _login(client, roles.ACCOUNTANT, "acc1")
    body = _body(client, hired)
    assert "Жагсаалт эхлүүлэх" not in body
    assert "Ажлаас гарах жагсаалт" not in body  # nothing started and nothing to start


def test_tick_by_owner_marks_done_logs_and_redirects_back(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    task = _task(checklist, ASSETS)
    hr = _login(client, roles.HR, "hr1")
    response = client.post(reverse("checklists:tick", args=[task.pk]))
    assert response.status_code == 302
    assert response["Location"] == _detail(hired) + "#work"
    task.refresh_from_db()
    assert task.done_at is not None and task.done_by == hr
    assert ActivityEntry.objects.filter(employee=hired, message__contains=ASSETS).exists()


def test_tick_follows_a_local_next_address_only(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    _login(client, roles.HR, "hr1")
    first = client.post(reverse("checklists:tick", args=[_task(checklist, ASSETS).pk]), {"next": "/me/"})
    assert first["Location"] == "/me/"
    other = _task(checklist, "Ажлаас гарах ярилцлага")
    second = client.post(reverse("checklists:tick", args=[other.pk]), {"next": "https://evil.example/x"})
    assert second["Location"] == _detail(hired) + "#work"


def test_tick_by_non_owner_is_404(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    task = _task(checklist, ASSETS)  # HR task
    _login(client, roles.ACCOUNTANT, "acc1")
    assert client.post(reverse("checklists:tick", args=[task.pk])).status_code == 404
    task.refresh_from_db()
    assert task.done_at is None


def test_tick_needs_post(client: Client, hired: Employee, actor: User) -> None:
    task = _task(_start(hired, actor), ASSETS)
    _login(client, roles.HR, "hr1")
    assert client.get(reverse("checklists:tick", args=[task.pk])).status_code == 405


def test_own_login_cannot_tick_own_task(client: Client, hired: Employee, actor: User) -> None:
    task = _task(_start(hired, actor), ASSETS)
    me = _login(client, roles.HR, "self_hr")
    EmployeeExt.objects.update_or_create(employee=hired, defaults={"user": me})
    assert client.post(reverse("checklists:tick", args=[task.pk])).status_code == 404
    task.refresh_from_db()
    assert task.done_at is None


def test_untick_needs_manage_right(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    task = _task(checklist, FINAL_PAY)
    lifecycle.tick(task, by=actor)
    _login(client, roles.ACCOUNTANT, "acc1")  # owns the task, may not manage employees
    assert client.post(reverse("checklists:untick", args=[task.pk])).status_code == 404
    task.refresh_from_db()
    assert task.done_at is not None
    _login(client, roles.HR, "hr1")
    response = client.post(reverse("checklists:untick", args=[task.pk]))
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.done_at is None


def test_untick_refused_after_the_termination(
    client: Client, hired: Employee, actor: User, termination: object
) -> None:
    checklist = _start(hired, actor)
    task = _task(checklist, FINAL_PAY)
    lifecycle.tick(task, by=actor)
    checklist.event = termination  # type: ignore[assignment]
    checklist.state = ChecklistState.COMPLETED
    checklist.save()
    _login(client, roles.HR, "hr1")
    response = client.post(reverse("checklists:untick", args=[task.pk]))
    assert response.status_code == 409
    task.refresh_from_db()
    assert task.done_at is not None


def test_start_creates_the_checklist(client: Client, hired: Employee) -> None:
    hr = _login(client, roles.HR, "hr1")
    response = client.post(reverse("checklists:start", args=[hired.pk]), {"anchor_day": LAST_DAY.isoformat()})
    assert response.status_code == 302
    assert response["Location"] == _detail(hired) + "#work"
    checklist = Checklist.objects.get(employee=hired)
    assert checklist.anchor_day == LAST_DAY and checklist.created_by == hr
    assert checklist.tasks.count() == 5


def test_start_needs_manage_right_and_a_valid_date(client: Client, hired: Employee) -> None:
    url = reverse("checklists:start", args=[hired.pk])
    _login(client, roles.ACCOUNTANT, "acc1")
    assert client.post(url, {"anchor_day": LAST_DAY.isoformat()}).status_code == 404
    _login(client, roles.HR, "hr1")
    assert client.post(url, {"anchor_day": "not-a-date"}).status_code == 400
    assert client.post(url, {}).status_code == 400
    assert client.get(url).status_code == 405
    assert not Checklist.objects.exists()


def test_start_again_returns_the_open_checklist(client: Client, hired: Employee) -> None:
    _login(client, roles.HR, "hr1")
    url = reverse("checklists:start", args=[hired.pk])
    client.post(url, {"anchor_day": LAST_DAY.isoformat()})
    later = LAST_DAY + timedelta(days=3)
    client.post(url, {"anchor_day": later.isoformat()})
    assert Checklist.objects.filter(employee=hired).count() == 1
    assert Checklist.objects.get(employee=hired).anchor_day == later


def test_start_without_template_is_400(client: Client, hired: Employee) -> None:
    ChecklistTemplate.objects.update(active=False)
    _login(client, roles.HR, "hr1")
    response = client.post(reverse("checklists:start", args=[hired.pk]), {"anchor_day": LAST_DAY.isoformat()})
    assert response.status_code == 400


def test_limited_scope_user_never_sees_another_branch(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    other = macs_writes.save_department("Бусад")
    limited = _login(client, roles.HR, "limited_hr")
    AccessScope.objects.create(user=limited, limited=True, department_ids=[other.pk])
    assert client.get(_detail(hired)).status_code == 404
    for name in ("tick", "untick"):
        task = _task(checklist, ASSETS)
        assert client.post(reverse(f"checklists:{name}", args=[task.pk])).status_code == 404
    assert client.post(reverse("checklists:start", args=[hired.pk]), {"anchor_day": "2026-12-01"}).status_code == 404
    assert _task(checklist, ASSETS).done_at is None


def test_task_owner_without_employee_visibility_sees_nothing(client: Client, hired: Employee, actor: User) -> None:
    """A user who owns a task but may not see the employee gets the employee page as a 404 (nothing leaks)."""
    _start(hired, actor)
    group = Group.objects.get_or_create(name="Хяналт")[0]
    user = User.objects.create_user("plain_owner", password=PASSWORD)
    user.groups.clear()
    user.groups.add(Group.objects.get(name=roles.EMPLOYEE), group)
    client.force_login(user)
    assert client.get(_detail(hired)).status_code == 404


def test_completed_checklist_has_no_buttons(client: Client, hired: Employee, actor: User, termination: object) -> None:
    checklist = _start(hired, actor)
    for task in checklist.tasks.all():
        lifecycle.tick(task, by=actor)
    checklist.event = termination  # type: ignore[assignment]
    checklist.state = ChecklistState.COMPLETED
    checklist.completed_at = timezone.now()
    checklist.save()
    _login(client, roles.HR, "hr1")
    body = _body(client, hired)
    assert "5 / 5" in body
    assert reverse("checklists:untick", args=[checklist.tasks.first().pk]) not in body  # type: ignore[union-attr]


def test_cancel_button_and_view_for_managers_only(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    url = reverse("checklists:cancel", args=[checklist.pk])
    _login(client, roles.ACCOUNTANT, "acc2")  # owns a task, may not manage employees
    assert client.post(url).status_code == 404
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN
    _login(client, roles.HR, "hr2")
    assert client.get(url).status_code == 405
    assert url in _body(client, hired) and "Цуцлах" in _body(client, hired)
    response = client.post(url, {"next": "https://evil.example/x"})
    assert response.status_code == 302 and response["Location"] == _detail(hired) + "#work"
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.CANCELLED
    # The panel is gone, the start form is back, and a new checklist can start.
    body = _body(client, hired)
    assert "Жагсаалт эхлүүлэх" in body and url not in body
    assert _start(hired, actor).pk != checklist.pk


def test_cancel_refused_after_the_termination(
    client: Client, hired: Employee, actor: User, termination: object
) -> None:
    checklist = _start(hired, actor)
    checklist.event = termination  # type: ignore[assignment]
    checklist.save()
    _login(client, roles.HR, "hr3")
    assert reverse("checklists:cancel", args=[checklist.pk]) not in _body(client, hired)
    assert client.post(reverse("checklists:cancel", args=[checklist.pk])).status_code == 409
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN


def test_cancel_outside_data_scope_is_404(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    other = macs_writes.save_department("Бусад2")
    limited = _login(client, roles.HR, "limited_hr2")
    AccessScope.objects.create(user=limited, limited=True, department_ids=[other.pk])
    assert client.post(reverse("checklists:cancel", args=[checklist.pk])).status_code == 404
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN


def test_task_with_deleted_group_shows_admin_label(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    task = _task(checklist, ASSETS)
    ChecklistTask.objects.filter(pk=task.pk).update(group=None, manager=False)
    _login(client, roles.HR, "hr4")
    body = _body(client, hired)
    assert "Шууд удирдлага" not in body.split(ASSETS, 1)[1].split("</tr>", 1)[0]
    assert "Админ (эзэн олдсонгүй)" in body.split(ASSETS, 1)[1].split("</tr>", 1)[0]


def _member(role: str, name: str) -> User:
    """A login in `role` that is not signed in, so it can own tasks without being the client's user."""
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return user


def test_admin_ticks_a_role_task_it_does_not_own(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    _member(roles.HR, "hr_owner_for_admin")  # HR members own the assets task
    task = _task(checklist, ASSETS)
    admin = _login(client, roles.ADMIN, "admin_tick")
    response = client.post(reverse("checklists:tick", args=[task.pk]))
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.done_at is not None and task.done_by == admin


def test_admin_sees_tick_button_on_every_open_task(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    _member(roles.HR, "hr_owner_panel")
    _member(roles.ACCOUNTANT, "acc_owner_panel")
    _login(client, roles.ADMIN, "admin_panel")
    body = _body(client, hired)
    for task in checklist.tasks.all():
        assert reverse("checklists:tick", args=[task.pk]) in body


def test_hr_who_does_not_own_the_task_gets_404(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    _member(roles.ACCOUNTANT, "acc_owner_for_hr")  # the final-pay task belongs to Accountants
    task = _task(checklist, FINAL_PAY)
    _login(client, roles.HR, "hr_non_owner")
    assert reverse("checklists:tick", args=[task.pk]) not in _body(client, hired)
    assert client.post(reverse("checklists:tick", args=[task.pk])).status_code == 404
    task.refresh_from_db()
    assert task.done_at is None


def test_admin_leaver_cannot_tick_own_task(client: Client, hired: Employee, actor: User) -> None:
    checklist = _start(hired, actor)
    _member(roles.HR, "hr_owner_for_leaver")
    task = _task(checklist, ASSETS)
    me = _login(client, roles.ADMIN, "admin_leaver")
    EmployeeExt.objects.update_or_create(employee=hired, defaults={"user": me})
    assert reverse("checklists:tick", args=[task.pk]) not in _body(client, hired)
    assert client.post(reverse("checklists:tick", args=[task.pk])).status_code == 404
    task.refresh_from_db()
    assert task.done_at is None
