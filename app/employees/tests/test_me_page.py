"""My page («Миний хуудас»), home routing and the own-result notices (spec 5.6, Task 6)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from leave.models import LeaveRequest, LeaveSettings, LeaveTypeExt, RequestStatus
from leave.services import requests as request_service
from macs.models import LeaveTypeRow

from employees import attention
from employees.models import Employee, JobRecord
from employees.services import history
from employees.tests.conftest import hire_values, link_login

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105


def _client(user: User) -> Client:
    c = Client()
    c.force_login(user)
    return c


def _staff(name: str, employee: Employee | None = None) -> User:
    """A login in the Employee role (may request leave, no employee rights), linked to `employee` when given."""
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.EMPLOYEE)[0])
    if employee is not None:
        link_login(employee, user)
    return user


def _perm(user: User, codename: str, app: str) -> None:
    user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label=app))


def _approval(on: bool) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": on})


@pytest.fixture
def sick() -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Өвчний амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True)
    return row


@pytest.fixture
def staff_employee(actor: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(
        hire_values("УБ99000002"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("1500000"),
        by=actor,
    )


def test_employee_lands_on_me_page(hired: Employee) -> None:
    user = _staff("staff", hired)
    resp = _client(user).get(reverse("home"))
    assert resp.status_code == 302
    assert resp["Location"] == reverse("me")


def test_hr_still_lands_on_today(hired: Employee) -> None:
    user = _staff("hr", hired)
    _perm(user, "view_employees", "macs")
    assert _client(user).get(reverse("home"))["Location"] == reverse("employees:today")


def test_hr_without_employee_link_lands_on_today() -> None:
    user = User.objects.create_user("hr_plain", password=PASSWORD)
    _perm(user, "view_employees", "macs")
    assert _client(user).get(reverse("home"))["Location"] == reverse("employees:today")


def test_auditor_still_lands_on_log(hired: Employee) -> None:
    user = _staff("auditor", hired)
    _perm(user, "view_audit", "accounts")
    assert _client(user).get(reverse("home"))["Location"] == reverse("logs:system")


def test_plain_user_without_link_still_lands_on_today() -> None:
    user = User.objects.create_user("nobody", password=PASSWORD)
    assert _client(user).get(reverse("home"))["Location"] == reverse("employees:today")


def test_me_without_employee_link_404() -> None:
    user = User.objects.create_user("nobody2", password=PASSWORD)
    assert _client(user).get(reverse("me")).status_code == 404


def test_me_shows_name_and_position(hired: Employee) -> None:
    body = _client(_staff("staff", hired)).get(reverse("me")).content.decode()
    assert "Сараа" in body
    assert "Нягтлан" in body


def test_request_button_hidden_when_approval_off(hired: Employee) -> None:
    _approval(False)
    body = _client(_staff("staff", hired)).get(reverse("me")).content.decode()
    assert reverse("leave:request_new") not in body


def test_request_button_shown_when_approval_on(hired: Employee) -> None:
    _approval(True)
    body = _client(_staff("staff", hired)).get(reverse("me")).content.decode()
    assert reverse("leave:request_new") in body


def test_request_button_hidden_without_right(hired: Employee) -> None:
    _approval(True)
    user = User.objects.create_user("noright", password=PASSWORD)
    user.groups.clear()  # every new user gets the Employee role (accounts/signals.py): remove it for this case
    link_login(hired, user)
    body = _client(user).get(reverse("me")).content.decode()
    assert reverse("leave:request_new") not in body


def test_nav_hides_today_without_view_employees(hired: Employee) -> None:
    body = _client(_staff("staff", hired)).get(reverse("me")).content.decode()
    assert f'href="{reverse("employees:today")}"' not in body
    assert f'href="{reverse("me")}"' in body  # «Миний хуудас» for a user with an employee record


def test_nav_has_no_my_page_link_without_employee_record() -> None:
    user = User.objects.create_user("nobody3", password=PASSWORD)
    _perm(user, "view_employees", "macs")
    body = _client(user).get(reverse("employees:today")).content.decode()
    assert f'href="{reverse("me")}"' not in body


def test_manager_sees_waiting_for_me_block(
    actor: User, hired: Employee, staff_employee: Employee, sick: LeaveTypeRow
) -> None:
    _approval(True)
    boss_user = _staff("boss", hired)
    JobRecord.objects.filter(employee=staff_employee).update(manager=hired)
    request_service.submit(staff_employee, sick, date(2027, 1, 11), date(2027, 1, 12), "", actor, TODAY)
    body = _client(boss_user).get(reverse("me")).content.decode()
    assert "Надад ирсэн хүсэлт" in body
    assert "Сараа" in body
    assert reverse("leave:request_detail", args=[LeaveRequest.objects.get().pk]) in body


def test_non_manager_has_no_waiting_for_me_block(
    actor: User, hired: Employee, staff_employee: Employee, sick: LeaveTypeRow
) -> None:
    _approval(True)
    JobRecord.objects.filter(employee=staff_employee).update(manager=hired)
    request_service.submit(staff_employee, sick, date(2027, 1, 11), date(2027, 1, 12), "", actor, TODAY)
    body = _client(_staff("stranger", staff_employee)).get(reverse("me")).content.decode()
    assert "Надад ирсэн хүсэлт" not in body


def test_me_page_lists_own_requests_with_state_and_reason(actor: User, hired: Employee, sick: LeaveTypeRow) -> None:
    _approval(True)
    LeaveRequest.objects.create(
        employee=hired,
        leave_type=sick,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 1),
        working_days=1,
        status=RequestStatus.REJECTED,
        reason="Ачаалал их байна",
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )
    body = _client(_staff("staff", hired)).get(reverse("me")).content.decode()
    assert "2027-02-01" in body
    assert "Ачаалал их байна" in body


def test_me_page_fixed_queries(actor: User, hired: Employee, sick: LeaveTypeRow) -> None:
    _approval(True)
    user = _staff("staff", hired)

    def add(n: int, first: int) -> None:
        for i in range(n):
            start = date(2027, 3, 1) + timedelta(days=(first + i) * 3)
            LeaveRequest.objects.create(
                employee=hired,
                leave_type=sick,
                start_date=start,
                end_date=start,
                working_days=1,
                step1_manager=True,
                step_count=1,
                created_by=actor,
            )

    def count() -> int:
        with CaptureQueriesContext(connection) as ctx:
            assert _client(user).get(reverse("me")).status_code == 200
        return len(ctx.captured_queries)

    add(5, 0)
    _client(user).get(reverse("me"))  # warm-up: one-time work of the test transaction is not per page
    few = count()
    add(35, 5)
    assert count() == few


def test_result_notice_shown_and_dismissed(actor: User, hired: Employee, sick: LeaveTypeRow) -> None:
    from employees.views_me import own_notices

    _approval(True)
    user = _staff("staff", hired)
    LeaveRequest.objects.create(
        employee=hired,
        leave_type=sick,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 1),
        working_days=1,
        status=RequestStatus.REJECTED,
        reason="Тохирохгүй",
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )
    notices = own_notices(user, hired)
    assert len(notices) == 1
    assert "Чөлөөний хүсэлт татгалзсан" in _client(user).get(reverse("me")).content.decode()
    assert notices[0].approved is False
    resp = _client(user).post(reverse("me_notice"), {"key": notices[0].item.key})
    assert resp.status_code == 200
    assert "Чөлөөний хүсэлт татгалзсан" not in _client(user).get(reverse("me")).content.decode()


def test_notice_dismiss_refuses_foreign_key(hired: Employee) -> None:
    user = _staff("staff", hired)
    resp = _client(user).post(reverse("me_notice"), {"key": "leave_request_result:1:1:x"})
    assert resp.status_code == 404


def test_rejected_notice_stays_red_even_if_reason_has_the_approved_word(
    actor: User, hired: Employee, sick: LeaveTypeRow
) -> None:
    _approval(True)
    LeaveRequest.objects.create(
        employee=hired,
        leave_type=sick,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 1),
        working_days=1,
        status=RequestStatus.REJECTED,
        reason="Чөлөө батлагдсан хугацаа дууссан",
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )
    body = _client(_staff("staff", hired)).get(reverse("me")).content.decode()
    assert "border-l-red-500" in body
    assert "border-l-emerald-500" not in body


def test_non_approver_never_reaches_the_queue(monkeypatch: pytest.MonkeyPatch, hired: Employee) -> None:
    from employees import views_me

    _approval(True)

    def queue_must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("the queue was worked out for a user who can decide nothing")

    monkeypatch.setattr(views_me, "waiting_for_cached", queue_must_not_run)
    assert _client(_staff("staff", hired)).get(reverse("me")).status_code == 200


def test_waiting_request_stays_visible_to_approver_after_approval_is_switched_off(
    actor: User, hired: Employee, staff_employee: Employee, sick: LeaveTypeRow
) -> None:
    """Spec 5.1: a settings change does not touch waiting requests, so they stay approvable and visible."""
    _approval(True)
    boss_user = _staff("boss_off", hired)
    JobRecord.objects.filter(employee=staff_employee).update(manager=hired)
    request_service.submit(staff_employee, sick, date(2027, 1, 11), date(2027, 1, 12), "", actor, TODAY)
    LeaveSettings.objects.filter(pk=1).update(approval1_manager=False)
    assert LeaveSettings.objects.get(pk=1).approval_on is False
    body = _client(boss_user).get(reverse("me")).content.decode()
    assert "Надад ирсэн хүсэлт" in body  # My page queue
    assert f'href="{reverse("leave:requests")}"' in body  # nav link
    items = attention._leave_requests_waiting(boss_user, timezone.localdate())
    assert [a.kind for a in items] == ["leave_requests"]
