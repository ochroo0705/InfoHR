"""The My page API: GET /api/v1/me, POST /api/v1/me/notice, POST /api/v1/me/requests/{pk}/withdraw and
POST /api/v1/checklists/tasks/{pk}/tick, as the React My page calls them."""

import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask
from checklists.services import owners
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import Employee, JobRecord
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, link_login
from employees.tests.helpers import next_order_number
from leave.models import ActionKind, LeaveRequest, LeaveRequestAction, LeaveTypeExt, RequestStatus
from leave.services import ledger
from macs.models import LeaveAssign, LeaveTypeRow

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
TODAY = date(2026, 10, 30)
LEAVE_TYPE = "Өвчний амралт"
CLOSED_MESSAGE = "Жагсаалт аль хэдийн дууссан байна."


@pytest.fixture(autouse=True)
def _frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """The My page reads timezone.localdate(); freeze it so the fixed dates sit in the window."""
    monkeypatch.setattr(timezone, "localdate", lambda *a, **k: TODAY)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("hr_actor_me", password=PASSWORD)


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
    """A working employee hired on 2026-01-05, with a login linked by each test that needs one."""
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


@pytest.fixture
def sick() -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name=LEAVE_TYPE)
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True)
    return row


def _login(employee: Employee | None, name: str) -> Client:
    """A login in the Employee role, linked to `employee` when given."""
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.EMPLOYEE)[0])
    if employee is not None:
        link_login(employee, user)
    client = Client()
    client.force_login(user)
    return client


def _hire(actor: User, job: dict[str, Any], register_no: str, given: str) -> Employee:
    return history.hire(
        hire_values(register_no) | {"given_name": given},
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=actor,
        order_number=next_order_number(),
    )


def _request(
    employee: Employee, leave_type: LeaveTypeRow, actor: User, status: str, start: date | None = None
) -> LeaveRequest:
    day = start or date(2027, 3, 1)
    return LeaveRequest.objects.create(
        employee=employee,
        leave_type=leave_type,
        start_date=day,
        end_date=day,
        working_days=1,
        status=status,
        reason="Тохирохгүй" if status == RequestStatus.REJECTED else "",
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )


def test_user_without_employee_record_gets_404(db: None) -> None:
    assert _login(None, "no_record_me").get("/api/v1/me").status_code == 404


def test_own_me_has_employee_name(hired: Employee) -> None:
    body = _login(hired, "own_me").get("/api/v1/me").json()
    assert body["employee"]["full_name"] == hired.full_name
    assert body["employee"]["id"] == hired.pk
    assert body["has_team"] is False
    assert body["team_away"] == []


def test_team_member_leave_has_no_leave_type(
    actor: User, hired: Employee, sick: LeaveTypeRow, job_values: dict[str, Any]
) -> None:
    member = _hire(actor, job_values, "УБ99000030", "Бат")
    JobRecord.objects.filter(employee=member).update(manager=hired)
    start, end = TODAY + timedelta(days=2), TODAY + timedelta(days=3)
    LeaveAssign.objects.create(employee=member, leave_type=sick, date1=start, date2=end, status=None)
    body = _login(hired, "boss_me").get("/api/v1/me").json()
    assert body["has_team"] is True
    assert body["team_away"] == [{"full_name": member.full_name, "start": start.isoformat(), "end": end.isoformat()}]


def test_notice_dismissal_hides_it_on_next_read(actor: User, hired: Employee, sick: LeaveTypeRow) -> None:
    client = _login(hired, "notice_me")
    _request(hired, sick, actor, RequestStatus.REJECTED)
    notices = client.get("/api/v1/me").json()["notices"]
    assert len(notices) == 1
    assert notices[0]["approved"] is False
    resp = client.post("/api/v1/me/notice", json.dumps({"key": notices[0]["key"]}), content_type="application/json")
    assert resp.status_code == 204
    assert client.get("/api/v1/me").json()["notices"] == []


def test_notice_dismiss_refuses_unknown_key(hired: Employee) -> None:
    resp = _login(hired, "notice_unknown").post(
        "/api/v1/me/notice", json.dumps({"key": "leave_request_result:1:1:x"}), content_type="application/json"
    )
    assert resp.status_code == 404


def test_waiting_request_shows_tone_label_and_withdraw_flag(actor: User, hired: Employee, sick: LeaveTypeRow) -> None:
    _request(hired, sick, actor, RequestStatus.WAITING)
    item = _login(hired, "waiting_me").get("/api/v1/me").json()["requests"][0]
    assert item["status"] == RequestStatus.WAITING
    assert item["tone"] == "waiting"
    assert item["status_label"].endswith("шат 1/1")
    assert item["step"] == "1/1"
    assert item["can_withdraw"] is True
    assert item["reason"] == ""


def test_rejected_request_shows_reason_and_no_withdraw(actor: User, hired: Employee, sick: LeaveTypeRow) -> None:
    _request(hired, sick, actor, RequestStatus.REJECTED)
    item = _login(hired, "rejected_me").get("/api/v1/me").json()["requests"][0]
    assert item["tone"] == "rejected"
    assert item["reason"] == "Тохирохгүй"
    assert item["rule"] == ""
    assert item["can_withdraw"] is False


def test_balance_shows_only_current_and_upcoming_periods(monkeypatch: pytest.MonkeyPatch, hired: Employee) -> None:
    def period(start: date, current: bool, upcoming: bool, granted: float, taken: float) -> SimpleNamespace:
        return SimpleNamespace(
            start=start,
            end=start.replace(year=start.year + 1) - timedelta(days=1),
            current=current,
            upcoming=upcoming,
            granted=granted,
            taken=taken,
            left=granted - taken,
        )

    past = period(date(2024, 1, 5), False, False, 15, 15)
    current = period(date(2026, 1, 5), True, False, 15, 15.5)
    upcoming = period(date(2027, 1, 5), False, True, 15, 0)
    monkeypatch.setattr(ledger, "annual_configured", lambda: True)
    monkeypatch.setattr(ledger, "periods", lambda employee, day: ([past, current, upcoming], []))
    body = _login(hired, "balance_me").get("/api/v1/me").json()
    periods = body["balance"]["periods"]
    assert [p["start"] for p in periods] == ["2026-01-05", "2027-01-05"]
    assert periods[0] == {
        "start": "2026-01-05",
        "end": "2027-01-04",
        "current": True,
        "granted": "15",
        "taken": "15.5",
        "left": "-0.5",
        "negative": True,
    }
    assert periods[1]["granted"] == "15" and periods[1]["negative"] is False
    assert body["balance"]["configured"] is True
    assert body["balance"]["started"] is True


def test_withdraw_waiting_request_gives_204_and_withdraws(actor: User, hired: Employee, sick: LeaveTypeRow) -> None:
    req = _request(hired, sick, actor, RequestStatus.WAITING)
    resp = _login(hired, "withdraw_ok").post(f"/api/v1/me/requests/{req.pk}/withdraw")
    assert resp.status_code == 204
    req.refresh_from_db()
    assert req.status == RequestStatus.WITHDRAWN
    assert LeaveRequestAction.objects.filter(request=req, action=ActionKind.WITHDRAWN).exists()


def test_withdraw_approved_request_gives_409(actor: User, hired: Employee, sick: LeaveTypeRow) -> None:
    req = _request(hired, sick, actor, RequestStatus.APPROVED)
    resp = _login(hired, "withdraw_own").post(f"/api/v1/me/requests/{req.pk}/withdraw")
    assert resp.status_code == 409
    body = resp.json()
    assert body["form_errors"]
    assert all(isinstance(m, str) and m for m in body["form_errors"])


def test_withdraw_another_persons_request_gives_404(
    actor: User, hired: Employee, sick: LeaveTypeRow, job_values: dict[str, Any]
) -> None:
    other = _hire(actor, job_values, "УБ99000031", "Өөр")
    req = _request(other, sick, actor, RequestStatus.WAITING)
    resp = _login(hired, "withdraw_foreign").post(f"/api/v1/me/requests/{req.pk}/withdraw")
    assert resp.status_code == 404
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


@pytest.fixture
def line_manager(actor: User, job_values: dict[str, Any], hired: Employee) -> Employee:
    """The direct manager of `hired`, who owns the manager tasks of `hired`'s offboarding checklist."""
    manager = _hire(actor, job_values, "УБ99000032", "Удирдагч")
    JobRecord.objects.filter(employee=hired).update(manager=manager)
    return manager


@pytest.fixture
def leaver_task(hired: Employee, line_manager: Employee) -> ChecklistTask:
    checklist = Checklist.objects.create(
        employee=hired,
        kind=ChecklistKind.OFFBOARDING,
        template_name="Загвар",
        anchor_day=TODAY + timedelta(days=28),
    )
    return ChecklistTask.objects.create(
        checklist=checklist, title="Ажил хүлээлгэн өгөх", manager=True, due_on=TODAY + timedelta(days=5), required=True
    )


def test_tick_task_the_user_does_not_own_gives_404(leaver_task: ChecklistTask) -> None:
    resp = _login(None, "stranger_tick").post(f"/api/v1/checklists/tasks/{leaver_task.pk}/tick")
    assert resp.status_code == 404


def test_tick_own_task_gives_204_and_marks_it_done(leaver_task: ChecklistTask, line_manager: Employee) -> None:
    resp = _login(line_manager, "manager_tick").post(f"/api/v1/checklists/tasks/{leaver_task.pk}/tick")
    assert resp.status_code == 204
    leaver_task.refresh_from_db()
    assert leaver_task.done_at is not None


def test_tick_on_a_closed_checklist_gives_404_from_the_gate(leaver_task: ChecklistTask, line_manager: Employee) -> None:
    Checklist.objects.filter(pk=leaver_task.checklist_id).update(state=ChecklistState.COMPLETED)
    resp = _login(line_manager, "closed_tick").post(f"/api/v1/checklists/tasks/{leaver_task.pk}/tick")
    assert resp.status_code == 404
    leaver_task.refresh_from_db()
    assert leaver_task.done_at is None


def test_refused_tick_maps_to_409_with_the_service_message(
    leaver_task: ChecklistTask, line_manager: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate (owners.can_tick) refuses a closed checklist first, so a 409 needs the gate to pass: here it is
    widened on purpose, to check that a refused lifecycle.tick is answered as 409 with the service's message."""
    Checklist.objects.filter(pk=leaver_task.checklist_id).update(state=ChecklistState.COMPLETED)
    monkeypatch.setattr(owners, "can_tick", lambda *a, **k: True)
    resp = _login(line_manager, "refused_tick").post(f"/api/v1/checklists/tasks/{leaver_task.pk}/tick")
    assert resp.status_code == 409
    assert resp.json()["form_errors"] == [CLOSED_MESSAGE]
    leaver_task.refresh_from_db()
    assert leaver_task.done_at is None
