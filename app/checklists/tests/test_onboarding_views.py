"""Employee-page panels, My tasks and labels per checklist kind (onboarding plan Task 3)."""

from datetime import date, timedelta
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from employees.models import EmployeeExt, JobRecord
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, link_login
from macs.models import Employee

from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask, ChecklistTemplate
from checklists.services import lifecycle

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
START = date(2026, 12, 1)
ON_HEADING = "Ажилд орох жагсаалт"
OFF_HEADING = "Ажлаас гарах жагсаалт"


def _login(client: Client, role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.clear()
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def _member(role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return user


def _onboard(employee: Employee, actor: User) -> Checklist:
    checklist = lifecycle.start(employee, ChecklistKind.ONBOARDING, reason="full_time", anchor_day=START, by=actor)
    assert checklist is not None
    return checklist


def _offboard(employee: Employee, actor: User) -> Checklist:
    checklist = lifecycle.start(employee, ChecklistKind.OFFBOARDING, reason=None, anchor_day=START, by=actor)
    assert checklist is not None
    return checklist


def _detail(employee: Employee) -> str:
    return reverse("employees:detail", args=[employee.pk])


def _body(client: Client, employee: Employee) -> str:
    response = client.get(_detail(employee))
    assert response.status_code == 200
    return response.content.decode()


def _section(body: str, kind: str) -> str:
    """The HTML of one panel (they carry data-checklist-kind)."""
    return body.split(f'data-checklist-kind="{kind}"', 1)[1].split("</section>", 1)[0]


def test_onboarding_panel_has_heading_progress_caption_and_no_start_button(
    client: Client, hired: Employee, actor: User
) -> None:
    ChecklistTemplate.objects.filter(kind=ChecklistKind.OFFBOARDING).update(active=False)
    checklist = _onboard(hired, actor)
    lifecycle.tick(checklist.tasks.first(), by=actor)  # type: ignore[arg-type]
    _login(client, roles.HR, "hr_on")
    body = _body(client, hired)
    section = _section(body, "onboarding")
    total = checklist.tasks.count()
    assert ON_HEADING in section and OFF_HEADING not in body
    assert f"1 / {total}" in section
    assert "эхлэх огноо 2026-12-01" in section and "сүүлийн ажлын өдөр" not in section
    assert "Жагсаалт эхлүүлэх" not in body and 'name="anchor_day"' not in body


def test_both_panels_show_with_their_own_wording(client: Client, hired: Employee, actor: User) -> None:
    on = _onboard(hired, actor)
    off = _offboard(hired, actor)
    _login(client, roles.HR, "hr_both")
    body = _body(client, hired)
    assert body.index(ON_HEADING) < body.index(OFF_HEADING) or body.index(OFF_HEADING) < body.index(ON_HEADING)
    on_section = _section(body, "onboarding")
    off_section = _section(body, "offboarding")
    assert reverse("checklists:cancel", args=[on.pk]) in on_section
    assert reverse("checklists:cancel", args=[off.pk]) in off_section
    assert "эхлэх огноо" in on_section and "сүүлийн ажлын өдөр" in off_section
    assert on.tasks.first().title in on_section  # type: ignore[union-attr]
    assert off.tasks.first().title in off_section  # type: ignore[union-attr]


def test_finished_onboarding_stays_while_a_new_offboarding_can_start(
    client: Client, hired: Employee, actor: User
) -> None:
    on = _onboard(hired, actor)
    Checklist.objects.filter(pk=on.pk).update(state=ChecklistState.COMPLETED)
    _login(client, roles.HR, "hr_done")
    body = _body(client, hired)
    assert ON_HEADING in body and "Дууссан" in _section(body, "onboarding")
    assert "Жагсаалт эхлүүлэх" in _section(body, "offboarding")  # the start button is offboarding only


def test_manager_owner_sees_onboarding_task_with_kind_on_my_page_and_mine_and_ticks_it(
    client: Client, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    manager_emp = history.hire(
        hire_values("УБ99000012"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor
    )
    login = _member(roles.EMPLOYEE, "mgr_onboarding")
    link_login(manager_emp, login)
    JobRecord.objects.filter(employee=hired).update(manager=manager_emp)
    checklist = _onboard(hired, actor)
    task = ChecklistTask.objects.create(
        checklist=checklist, title="Удирдлагын тест даалгавар", manager=True, due_on=timezone.localdate(), position=99
    )
    client.force_login(login)
    for url in (reverse("me"), reverse("checklists:mine")):
        body = client.get(url).content.decode()
        assert task.title in body and hired.full_name in body
        assert "Ажилд орох" in body
        assert reverse("checklists:tick", args=[task.pk]) in body
    assert client.post(reverse("checklists:tick", args=[task.pk])).status_code == 302
    task.refresh_from_db()
    assert task.done_at is not None and task.done_by == login


def test_my_tasks_label_says_offboarding_for_offboarding(client: Client, hired: Employee, actor: User) -> None:
    off = _offboard(hired, actor)
    hr = _login(client, roles.HR, "hr_label")
    task = ChecklistTask.objects.create(
        checklist=off, title="HR тест даалгавар", group=Group.objects.get(name=roles.HR), due_on=START, position=99
    )
    body = client.get(reverse("checklists:mine")).content.decode()
    assert task.title in body and "Ажлаас гарах" in body and "Ажилд орох" not in body
    assert hr.pk


def test_admin_ticks_any_onboarding_task_and_leaver_never(client: Client, hired: Employee, actor: User) -> None:
    checklist = _onboard(hired, actor)
    _member(roles.HR, "hr_owner_on")
    admin = _login(client, roles.ADMIN, "admin_on")
    body = _body(client, hired)
    for task in checklist.tasks.all():
        assert reverse("checklists:tick", args=[task.pk]) in body
    first = checklist.tasks.first()
    assert first is not None
    assert client.post(reverse("checklists:tick", args=[first.pk])).status_code == 302
    first.refresh_from_db()
    assert first.done_by == admin
    EmployeeExt.objects.update_or_create(employee=hired, defaults={"user": admin})
    second = checklist.tasks.filter(done_at__isnull=True).first()
    assert second is not None
    assert reverse("checklists:tick", args=[second.pk]) not in _body(client, hired)
    assert client.post(reverse("checklists:tick", args=[second.pk])).status_code == 404


def test_untick_and_cancel_work_for_onboarding(client: Client, hired: Employee, actor: User) -> None:
    checklist = _onboard(hired, actor)
    first = checklist.tasks.first()
    assert first is not None
    lifecycle.tick(first, by=actor)
    _login(client, roles.HR, "hr_untick_on")
    assert reverse("checklists:untick", args=[first.pk]) in _body(client, hired)
    assert client.post(reverse("checklists:untick", args=[first.pk])).status_code == 302
    first.refresh_from_db()
    assert first.done_at is None
    assert client.post(reverse("checklists:cancel", args=[checklist.pk])).status_code == 302
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.CANCELLED
    assert 'data-checklist-kind="onboarding"' not in _body(client, hired)


def test_employee_outside_data_scope_sees_nothing(client: Client, hired: Employee, actor: User) -> None:
    checklist = _onboard(hired, actor)
    other = macs_writes.save_department("Бусад")
    limited = _login(client, roles.HR, "limited_on")
    AccessScope.objects.create(user=limited, limited=True, department_ids=[other.pk])
    assert client.get(_detail(hired)).status_code == 404
    task = checklist.tasks.first()
    assert task is not None
    assert client.post(reverse("checklists:tick", args=[task.pk])).status_code == 404
    assert client.post(reverse("checklists:cancel", args=[checklist.pk])).status_code == 404


@pytest.mark.parametrize("role", [roles.HR, roles.ADMIN])
def test_employee_page_query_count_does_not_grow_with_open_tasks(
    client: Client, hired: Employee, actor: User, role: str
) -> None:
    on = _onboard(hired, actor)
    _offboard(hired, actor)
    group = Group.objects.get(name=roles.HR)
    _login(client, role, f"hr_count_{role}")
    client.get(_detail(hired))  # warm-up: once-per-process work
    with CaptureQueriesContext(connection) as few:
        assert client.get(_detail(hired)).status_code == 200
    base = ChecklistTask.objects.filter(checklist=on).count()
    for n in range(12):
        ChecklistTask.objects.create(
            checklist=on,
            title=f"Нэмэлт {n}",
            group=group if n % 2 else None,
            manager=n % 2 == 0,
            due_on=START + timedelta(days=n),
            position=100 + n,
        )
    with CaptureQueriesContext(connection) as many:
        response = client.get(_detail(hired))
    assert response.status_code == 200 and f"0 / {base + 12}" in response.content.decode()
    assert len(few) == len(many)
