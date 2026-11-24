"""The checklist routes the React pages call: untick, cancel, start offboarding and «mine» (the tick route is in
test_me_api.py). The rules come from checklists.services.actions and lifecycle; these tests pin the status codes, the
bodies and the 404s (a user without the right gets 404 here, not 403)."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask, ChecklistTemplate
from checklists.services import actions, lifecycle
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import Event
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values
from employees.tests.helpers import next_order_number
from macs.models import Employee, FiredReason

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
LAST_DAY = date(2026, 11, 30)
ASSETS = "Эд хөрөнгө, тоног төхөөрөмж буцаах"  # owner: HR
FINAL_PAY = "Эцсийн тооцоо шалгах"  # owner: Accountant
NO_TEMPLATE = "Ажлаас гарах жагсаалтын загвар байхгүй байна."
BAD_DATE = "Сүүлийн ажлын өдрийг оруулна уу."
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"]}


def _login(role: str, name: str) -> Client:
    """A signed-in client in `role`. Without an employee record unless the test links one."""
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    client = Client()
    client.force_login(User.objects.get(pk=user.pk))  # fresh permission cache
    return client


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("hr_actor_checklists", password=PASSWORD)


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(actor: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
        order_number=next_order_number(),
    )


@pytest.fixture
def started(hired: Employee, actor: User) -> Checklist:
    """An open offboarding checklist of `hired`, anchored on LAST_DAY."""
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    return checklist


@pytest.fixture
def fired_reason(db: None) -> FiredReason:
    return FiredReason.objects.get_or_create(name="Нас барсан")[0]


@pytest.fixture
def termination(hired: Employee, actor: User, fired_reason: FiredReason) -> Event:
    """A bare termination row: a checklist linked to it can no longer be unticked or cancelled."""
    return Event.objects.create(
        employee=hired, type="termination", effective=LAST_DAY, fired_reason=fired_reason, created_by=actor
    )


def _task(checklist: Checklist, title: str) -> ChecklistTask:
    return checklist.tasks.get(title=title)


def _ticked(checklist: Checklist, actor: User, title: str = FINAL_PAY) -> ChecklistTask:
    task = _task(checklist, title)
    lifecycle.tick(task, by=actor)
    task.refresh_from_db()
    assert task.done_at is not None
    return task


# 401 without a login


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/checklists/tasks/1/untick"),
        ("post", "/api/v1/checklists/1/cancel"),
        ("post", "/api/v1/checklists/employees/1/start"),
        ("get", "/api/v1/checklists/mine"),
    ],
)
def test_checklist_routes_need_a_login(method: str, path: str) -> None:
    response = getattr(Client(), method)(path)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


# 404 without the right, and nothing changes


def test_untick_without_manage_right_is_404_and_changes_nothing(started: Checklist, actor: User) -> None:
    task = _ticked(started, actor)
    response = _login(roles.ACCOUNTANT, "acc_untick_api").post(f"/api/v1/checklists/tasks/{task.pk}/untick")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    task.refresh_from_db()
    assert task.done_at is not None


def test_cancel_without_manage_right_is_404_and_changes_nothing(started: Checklist) -> None:
    response = _login(roles.ACCOUNTANT, "acc_cancel_api").post(f"/api/v1/checklists/{started.pk}/cancel")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    started.refresh_from_db()
    assert started.state == ChecklistState.OPEN


def test_start_without_start_right_is_404_and_creates_nothing(hired: Employee) -> None:
    body = json.dumps({"anchor_day": LAST_DAY.isoformat()})
    response = _login(roles.ACCOUNTANT, "acc_start_api").post(
        f"/api/v1/checklists/employees/{hired.pk}/start", data=body, content_type="application/json"
    )
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert not Checklist.objects.filter(employee=hired).exists()


# success


def test_untick_gives_204_and_unticks_the_task(started: Checklist, actor: User) -> None:
    task = _ticked(started, actor)
    response = _login(roles.HR, "hr_untick_api").post(f"/api/v1/checklists/tasks/{task.pk}/untick")
    assert response.status_code == 204
    task.refresh_from_db()
    assert task.done_at is None


def test_cancel_gives_204_and_cancels_the_checklist(started: Checklist) -> None:
    response = _login(roles.HR, "hr_cancel_api").post(f"/api/v1/checklists/{started.pk}/cancel")
    assert response.status_code == 204
    started.refresh_from_db()
    assert started.state == ChecklistState.CANCELLED


def test_start_gives_204_and_starts_offboarding_on_the_given_day(hired: Employee) -> None:
    body = json.dumps({"anchor_day": LAST_DAY.isoformat()})
    response = _login(roles.HR, "hr_start_api").post(
        f"/api/v1/checklists/employees/{hired.pk}/start", data=body, content_type="application/json"
    )
    assert response.status_code == 204
    checklist = Checklist.objects.get(employee=hired)
    assert checklist.kind == ChecklistKind.OFFBOARDING
    assert checklist.anchor_day == LAST_DAY


# 409 for a refused change


def test_untick_refused_gives_409_with_the_service_message(started: Checklist, actor: User, termination: Event) -> None:
    task = _ticked(started, actor)
    Checklist.objects.filter(pk=started.pk).update(event=termination, state=ChecklistState.COMPLETED)
    response = _login(roles.HR, "hr_untick_refused_api").post(f"/api/v1/checklists/tasks/{task.pk}/untick")
    assert response.status_code == 409
    assert len(response.json()["form_errors"]) == 1
    task.refresh_from_db()
    assert task.done_at is not None


def test_cancel_refused_gives_409_with_the_service_message(started: Checklist, termination: Event) -> None:
    Checklist.objects.filter(pk=started.pk).update(event=termination)
    response = _login(roles.HR, "hr_cancel_refused_api").post(f"/api/v1/checklists/{started.pk}/cancel")
    assert response.status_code == 409
    assert len(response.json()["form_errors"]) == 1
    started.refresh_from_db()
    assert started.state == ChecklistState.OPEN


# 400 for a bad input


@pytest.mark.parametrize("text", ["not-a-date", ""])
def test_start_with_a_bad_anchor_day_gives_400(hired: Employee, text: str) -> None:
    body = json.dumps({"anchor_day": text})
    response = _login(roles.HR, "hr_start_bad_api").post(
        f"/api/v1/checklists/employees/{hired.pk}/start", data=body, content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["form_errors"] == [BAD_DATE]
    assert not Checklist.objects.filter(employee=hired).exists()


def test_start_without_a_template_gives_400(hired: Employee) -> None:
    ChecklistTemplate.objects.update(active=False)
    body = json.dumps({"anchor_day": LAST_DAY.isoformat()})
    response = _login(roles.HR, "hr_start_notpl_api").post(
        f"/api/v1/checklists/employees/{hired.pk}/start", data=body, content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["form_errors"] == [NO_TEMPLATE]
    assert not Checklist.objects.filter(employee=hired).exists()


# GET /checklists/mine


def test_mine_lists_an_overdue_task_with_due_as_iso_date(started: Checklist) -> None:
    day = timezone.localdate()
    assets = _task(started, ASSETS)
    ChecklistTask.objects.filter(pk=assets.pk).update(due_on=day - timedelta(days=2))
    response = _login(roles.HR, "hr_mine_overdue_api").get("/api/v1/checklists/mine")
    assert response.status_code == 200
    row = next(item for item in response.json()["items"] if item["id"] == assets.pk)
    assert row == {
        "id": assets.pk,
        "title": ASSETS,
        "employee": started.employee.full_name,
        "kind_label": started.get_kind_display(),
        "due": (day - timedelta(days=2)).isoformat(),
        "overdue": True,
    }


def test_mine_lists_a_task_not_yet_due_as_not_overdue(started: Checklist) -> None:
    day = timezone.localdate()
    assets = _task(started, ASSETS)
    ChecklistTask.objects.filter(pk=assets.pk).update(due_on=day + timedelta(days=5))
    response = _login(roles.HR, "hr_mine_later_api").get("/api/v1/checklists/mine")
    row = next(item for item in response.json()["items"] if item["id"] == assets.pk)
    assert row["due"] == (day + timedelta(days=5)).isoformat()
    assert row["overdue"] is False


def test_mine_is_empty_for_a_user_with_no_tasks(started: Checklist) -> None:
    response = _login(roles.EMPLOYEE, "plain_mine_api").get("/api/v1/checklists/mine")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_mine_works_for_a_user_without_an_employee_record(started: Checklist) -> None:
    """An Admin has no employee record; Admin may own any open task, so the rows are the same as actions.mine_rows."""
    admin = User.objects.create_user("admin_mine_api", password=PASSWORD)
    admin.groups.add(Group.objects.get_or_create(name=roles.ADMIN)[0])
    client = Client()
    client.force_login(User.objects.get(pk=admin.pk))
    response = client.get("/api/v1/checklists/mine")
    assert response.status_code == 200
    expected = actions.mine_rows(User.objects.get(pk=admin.pk), timezone.localdate())
    assert [item["id"] for item in response.json()["items"]] == [row.task_id for row in expected]
    assert len(response.json()["items"]) > 0
