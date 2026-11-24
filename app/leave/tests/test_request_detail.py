"""The request detail pop-up's rules as service calls: who may see or act on a request, the balance it shows, who else
in the department is off, and the status line."""

from datetime import date

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group, Permission
from django.http import Http404
from employees.models import Department, Employee, EmployeeExt, JobRecord
from employees.services import macs_writes
from macs.models import LeaveAssign, LeaveTypeRow

from leave.models import LeaveRequest, LeaveSettings
from leave.services import ledger, records, rows, writes
from leave.services import requests as request_service
from leave.services.request_page import (
    Balance,
    Other,
    RequestDetail,
    balance_of,
    detail_for,
    others_of,
    visible_request,
)
from leave.tests.conftest import make_employee

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105


def _user(name: str, *groups: Group) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(*groups)
    return user


def _viewer(name: str) -> User:
    """A user with the list right and the people right, and no approver role."""
    user = _user(name)
    user.user_permissions.add(
        Permission.objects.get(codename="view_leave", content_type__app_label="leave"),
        Permission.objects.get(codename="view_employees", content_type__app_label="macs"),
    )
    return User.objects.get(pk=user.pk)  # a fresh object, so no permission is cached from before


@pytest.fixture(autouse=True)
def _approval(db: None) -> None:
    """Approval on, step 1 = the requester's line manager."""
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})


@pytest.fixture
def manager(actor: User, employee: Employee) -> User:
    """A login (Employee role) that is the line manager of `employee`."""
    boss = make_employee(actor, hired=date(2019, 1, 1), register_no="УБ99000001")
    JobRecord.objects.filter(employee=employee).update(manager=boss)
    user = _user("manager", Group.objects.get_or_create(name=roles.EMPLOYEE)[0])
    EmployeeExt.objects.update_or_create(employee=boss, defaults={"user": user})
    return User.objects.get(pk=user.pk)


@pytest.fixture
def dept_b(db: None) -> Department:
    return macs_writes.save_department("Бусад")


def _waiting(
    employee: Employee, leave_type: LeaveTypeRow, actor: User, start: date = date(2026, 11, 2)
) -> LeaveRequest:
    return request_service.submit(employee, leave_type, start, start.replace(day=start.day + 1), "", actor, TODAY)


# --- visible_request


def test_stranger_gets_404(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    with pytest.raises(Http404):
        visible_request(_user("stranger"), req.pk, TODAY)


def test_viewer_in_scope_may_read_but_not_act(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    got, may, override = visible_request(_viewer("viewer_scope"), req.pk, TODAY)
    assert got.pk == req.pk
    assert may is False and override is False


def test_approver_may_act_without_override(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    got, may, override = visible_request(manager, req.pk, TODAY)
    assert got.pk == req.pk
    assert may is True and override is False


def test_requester_never_may_act(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    requester = _viewer("requester")
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": requester})
    req = _waiting(employee, sick, actor)
    got, may, override = visible_request(requester, req.pk, TODAY)
    assert got.pk == req.pk
    assert may is False and override is False


def test_decide_hook_gives_the_act_right(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    _, may, override = visible_request(_user("stranger_hook"), req.pk, TODAY, decide=lambda user, r, day: (True, True))
    assert may is True and override is True


# --- balance_of


def test_type_without_annual_balance_has_no_balance(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    assert balance_of(req, TODAY) == Balance(None, [], False)


def test_no_period_gives_warning_and_needs_override(
    actor: User, employee: Employee, annual: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, annual, actor)
    result = balance_of(req, TODAY)
    assert result.needs_override is True
    assert result.balance_after == -req.working_days
    assert result.warnings == [f"Энэ огноонд амралтын эрх олдсонгүй ({ledger.NO_PERIOD_LABEL})."]


def test_negative_balance_needs_override_and_writes_nothing(
    actor: User, employee: Employee, annual: LeaveTypeRow, manager: User
) -> None:
    ledger.manual_grant(employee, date(2026, 1, 1), date(2026, 12, 31), 1, "тест", actor)
    req = _waiting(employee, annual, actor)  # two days against one day of balance
    before = len(rows.grants(employee.pk, annual_only=False))
    result = balance_of(req, TODAY)
    after = len(rows.grants(employee.pk, annual_only=False))
    assert result.needs_override is True
    assert result.balance_after is not None and result.balance_after < 0
    assert before == after


# --- others_of


def test_others_are_same_department_overlapping_and_open(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User, dept_b: Department
) -> None:
    req = _waiting(employee, sick, actor)  # 2 and 3 November 2026
    peer = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000002")
    _waiting(peer, sick, actor)  # same days: listed
    _waiting(peer, sick, actor, date(2026, 12, 1))  # other days: not listed
    other_dept = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000003")
    JobRecord.objects.filter(employee=other_dept).update(department=dept_b)
    _waiting(other_dept, sick, actor)  # other department: not listed
    assert others_of(manager, req, TODAY) == [
        Other(peer.full_name, date(2026, 11, 2), date(2026, 11, 3), "Хүлээгдэж буй")
    ]


def test_others_respect_the_data_scope(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User, dept_b: Department
) -> None:
    req = _waiting(employee, sick, actor)
    peer = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000002")
    _waiting(peer, sick, actor)
    limited = _viewer("limited_others")
    AccessScope.objects.create(user=limited, limited=True, department_ids=[dept_b.pk])
    limited = User.objects.get(pk=limited.pk)
    assert others_of(limited, req, TODAY) == []


# --- detail_for


def test_decided_request_has_no_balance_and_no_rule(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    request_service.approve(req, manager, TODAY)
    req.refresh_from_db()
    detail = detail_for(manager, req, TODAY)
    assert isinstance(detail, RequestDetail)
    assert detail.waiting is False
    assert detail.balance is None and detail.rule == ""
    assert detail.status_label == "Батлагдсан"


def test_waiting_request_has_balance_and_rule(
    actor: User, employee: Employee, annual: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, annual, actor)
    detail = detail_for(manager, req, TODAY)
    assert detail.waiting is True
    assert detail.balance is not None
    assert detail.rule


def test_status_label_of_a_cancelled_leave(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    request_service.approve(req, manager, TODAY)
    req.refresh_from_db()
    leave = LeaveAssign.objects.get(pk=req.assign_id)
    records.cancel(leave, writes.snapshot(leave), "Төлөвлөгөө өөрчлөгдсөн", actor, TODAY)
    assert detail_for(manager, req, TODAY).status_label == "Цуцалсан"
