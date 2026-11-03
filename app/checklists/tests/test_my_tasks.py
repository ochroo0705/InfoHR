"""My page («Миний хуудас») and Today show the open offboarding tasks the user owns (plan Task 6)."""

from datetime import date, timedelta
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees import attention
from employees.models import JobRecord
from employees.services import history
from employees.tests.conftest import hire_values, link_login
from macs.models import Employee

from checklists.models import Checklist, ChecklistKind, ChecklistTask
from checklists.services import owners

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
TASK = "Ажил хүлээлгэн өгөх тест"
TODAY_ITEM = "1 даалгавар таныг хүлээж байна"


@pytest.fixture
def day() -> date:
    return timezone.localdate()


def _staff_login(name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.EMPLOYEE)[0])
    return user


@pytest.fixture
def manager(hired: Employee, actor: User, job_values: dict[str, Any]) -> User:
    """A staff member with a login who is the direct manager of the leaver `hired`."""
    manager_emp = history.hire(
        hire_values("УБ99000011"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor
    )
    login = _staff_login("line_manager_my_page")
    link_login(manager_emp, login)
    JobRecord.objects.filter(employee=hired).update(manager=manager_emp)
    return login


@pytest.fixture
def leaver_task(hired: Employee, manager: User, day: date) -> ChecklistTask:
    """An open checklist of the leaver with one manager task, due in five days."""
    checklist = Checklist.objects.create(
        employee=hired,
        kind=ChecklistKind.OFFBOARDING,
        template_name="Загвар",
        anchor_day=day + timedelta(days=28),
    )
    return ChecklistTask.objects.create(
        checklist=checklist, title=TASK, manager=True, due_on=day + timedelta(days=5), required=True
    )


def test_manager_sees_leaver_task_on_my_page(client: Client, manager: User, leaver_task: ChecklistTask) -> None:
    client.force_login(manager)
    body = client.get(reverse("me")).content.decode()
    assert "Миний даалгавар" in body
    assert TASK in body
    assert leaver_task.checklist.employee.full_name in body
    assert f'action="{reverse("checklists:tick", args=[leaver_task.pk])}"' in body
    assert f'name="next" value="{reverse("me")}"' in body


def test_manager_sees_today_item_linking_to_my_page(client: Client, manager: User, leaver_task: ChecklistTask) -> None:
    items = [a for a in attention.items(manager, [], timezone.localdate()) if a.kind == "checklist_tasks"]
    assert [(a.text, a.url) for a in items] == [(TODAY_ITEM, reverse("checklists:mine"))]
    client.force_login(manager)
    html = client.get(reverse("employees:today")).content.decode()
    # A system item shows as a chip: its group label (with the count) is what the box prints.
    assert "Даалгавар таныг хүлээж байна · 1" in html


def test_overdue_task_due_date_is_red(client: Client, manager: User, leaver_task: ChecklistTask, day: date) -> None:
    overdue = ChecklistTask.objects.create(
        checklist=leaver_task.checklist,
        title="Хугацаа өнгөрсөн",
        manager=True,
        due_on=day - timedelta(days=2),
        required=True,
        position=1,
    )
    client.force_login(manager)
    body = client.get(reverse("me")).content.decode()
    assert f'font-medium text-red-700">Хугацаа {overdue.due_on:%Y-%m-%d}</span>' in body
    assert f'text-slate-500">Хугацаа {leaver_task.due_on:%Y-%m-%d}</span>' in body


def test_user_without_tasks_sees_neither_section_nor_item(
    client: Client,
    actor: User,
    job_values: dict[str, Any],
    leaver_task: ChecklistTask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain_emp = history.hire(
        hire_values("УБ99000012"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor
    )
    plain = _staff_login("plain_no_tasks")
    link_login(plain_emp, plain)

    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("the task list was worked out for a user who owns no task")

    monkeypatch.setattr(owners, "my_tasks", must_not_run)
    assert not any(a.kind == "checklist_tasks" for a in attention.items(plain, [], timezone.localdate()))
    client.force_login(plain)
    body = client.get(reverse("me")).content.decode()
    assert "Миний даалгавар" not in body
    assert TASK not in body


def test_ticking_from_my_page_removes_the_task(client: Client, manager: User, leaver_task: ChecklistTask) -> None:
    client.force_login(manager)
    response = client.post(reverse("checklists:tick", args=[leaver_task.pk]), {"next": reverse("me")})
    assert response.status_code == 302
    assert response["Location"] == reverse("me")
    leaver_task.refresh_from_db()
    assert leaver_task.done_at is not None
    body = client.get(reverse("me")).content.decode()
    assert TASK not in body
    assert "Миний даалгавар" not in body
    assert not any(a.kind == "checklist_tasks" for a in attention.items(manager, [], timezone.localdate()))


def test_admin_without_employee_record_gets_mine_page_and_today_link(
    client: Client, leaver_task: ChecklistTask
) -> None:
    admin = User.objects.create_superuser("root_no_emp", password=PASSWORD)
    # The leaver's manager task has no manager owner here, so it falls to Admin.
    JobRecord.objects.filter(employee=leaver_task.checklist.employee).update(manager=None)
    client.force_login(admin)
    assert client.get(reverse("me")).status_code == 404  # no employee record: no My page
    response = client.get(reverse("checklists:mine"))
    assert response.status_code == 200
    body = response.content.decode()
    assert TASK in body
    assert f'action="{reverse("checklists:tick", args=[leaver_task.pk])}"' in body
    assert f'name="next" value="{reverse("checklists:mine")}"' in body
    items = [a for a in attention.items(admin, [], timezone.localdate()) if a.kind == "checklist_tasks"]
    assert [a.url for a in items] == [reverse("checklists:mine")]


def test_mine_page_needs_login_and_is_empty_for_non_owner(client: Client) -> None:
    assert client.get(reverse("checklists:mine")).status_code == 302
    client.force_login(User.objects.create_user("nobody_mine", password=PASSWORD))
    response = client.get(reverse("checklists:mine"))
    assert response.status_code == 200 and TASK not in response.content.decode()


def test_my_page_heading_links_to_mine_page(client: Client, manager: User, leaver_task: ChecklistTask) -> None:
    client.force_login(manager)
    assert f'href="{reverse("checklists:mine")}"' in client.get(reverse("me")).content.decode()
