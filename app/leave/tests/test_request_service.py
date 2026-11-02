from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from employees.models import (
    LEAVE_REQUEST_APPROVED,
    LEAVE_REQUEST_REJECTED,
    LEAVE_REQUEST_STEP_APPROVED,
    LEAVE_REQUEST_WITHDRAWN,
    LEAVE_REQUESTED,
    ActivityEntry,
    Employee,
    EmployeeExt,
)
from macs.models import LeaveAssign, LeaveTypeRow

from leave.models import (
    ActionKind,
    LeaveExt,
    LeaveRequest,
    LeaveRequestAction,
    LeaveSettings,
    LeaveTypeExt,
    RequestStatus,
)
from leave.services import records, requests
from leave.services.records import Draft, LeaveError

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def make_group(db: None) -> Group:
    return Group.objects.create(name="Нягтлан бодогч")


def _user(name: str, group: Group | None = None) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    if group is not None:
        user.groups.add(group)
    return user


def _set_approvers(group1: Group | None, group2: Group | None = None) -> None:
    settings_row = LeaveSettings.get()
    settings_row.approval1_group = group1
    settings_row.approval2_group = group2
    settings_row.save()


def _submit(employee: Employee, leave_type: LeaveTypeRow, start: date, end: date, by: User) -> LeaveRequest:
    return requests.submit(employee, leave_type, start, end, "Тэмдэглэл", by, TODAY)


def _assigns(employee: Employee) -> list[LeaveAssign]:
    return list(LeaveAssign.objects.filter(employee=employee))


def test_submit_refused_when_approval_off(employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    with pytest.raises(LeaveError):
        _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), actor)
    assert LeaveRequest.objects.count() == 0


def test_submit_refused_for_switched_off_type(
    employee: Employee, sick: LeaveTypeRow, actor: User, make_group: Group
) -> None:
    _set_approvers(make_group)
    LeaveTypeExt.objects.filter(pk=sick.pk).update(staff_may_request=False)
    with pytest.raises(LeaveError):
        _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), actor)
    assert LeaveRequest.objects.count() == 0


def test_submit_blocks_overlapping_waiting_request(
    employee: Employee, sick: LeaveTypeRow, annual: LeaveTypeRow, actor: User, make_group: Group
) -> None:
    _set_approvers(make_group)
    _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 6), actor)
    with pytest.raises(LeaveError, match="Энэ хугацаанд хүлээгдэж буй хүсэлт байна."):
        _submit(employee, annual, date(2026, 11, 4), date(2026, 11, 5), actor)
    assert LeaveRequest.objects.count() == 1


def test_submit_allows_short_balance_with_warning(
    employee: Employee, annual: LeaveTypeRow, actor: User, make_group: Group, grants_on: None
) -> None:
    _set_approvers(make_group)
    req = _submit(employee, annual, date(2026, 11, 2), date(2026, 11, 27), actor)  # 20 days > 15 balance
    assert req.status == RequestStatus.WAITING
    assert req.working_days == 20


def test_submit_allows_past_dates(employee: Employee, sick: LeaveTypeRow, actor: User, make_group: Group) -> None:
    _set_approvers(make_group)
    req = _submit(employee, sick, date(2026, 10, 5), date(2026, 10, 6), actor)
    assert req.status == RequestStatus.WAITING


def test_one_step_approval_writes_leave_assign_status_1(
    employee: Employee, sick: LeaveTypeRow, actor: User, make_group: Group
) -> None:
    approver = _user("approver_one", make_group)
    _set_approvers(make_group)
    req = _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), actor)

    req = requests.approve(req, approver, TODAY)

    assert req.status == RequestStatus.APPROVED
    assert req.assign_id is not None
    rows = _assigns(employee)
    assert len(rows) == 1
    assert rows[0].pk == req.assign_id
    assert rows[0].status == LeaveAssign.APPROVED == 1
    assert LeaveExt.objects.get(assign=rows[0]).created_by == approver


def test_two_steps_need_both(employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    group1 = Group.objects.create(name="Шат 1")
    group2 = Group.objects.create(name="Шат 2")
    first = _user("approver_first", group1)
    second = _user("approver_second", group2)
    _set_approvers(group1, group2)
    req = _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), actor)

    req = requests.approve(req, first, TODAY)
    assert req.current_step == 2
    assert req.status == RequestStatus.WAITING
    assert _assigns(employee) == []

    with pytest.raises(LeaveError):  # the first approver cannot act on step 2
        requests.approve(req, first, TODAY)

    req = requests.approve(req, second, TODAY)
    assert req.status == RequestStatus.APPROVED
    assert len(_assigns(employee)) == 1


def test_reject_needs_reason_and_writes_nothing(
    employee: Employee, sick: LeaveTypeRow, actor: User, make_group: Group
) -> None:
    approver = _user("approver_reject", make_group)
    _set_approvers(make_group)
    req = _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), actor)

    with pytest.raises(LeaveError, match="Татгалзсан шалтгаан бичнэ үү."):
        requests.reject(req, approver, "  ", TODAY)
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING
    assert _assigns(employee) == []

    req = requests.reject(req, approver, "Давхцаж байна", TODAY)
    assert req.status == RequestStatus.REJECTED
    assert req.reason == "Давхцаж байна"
    assert _assigns(employee) == []


def test_withdraw_only_by_requester_while_waiting(
    employee: Employee, sick: LeaveTypeRow, actor: User, make_group: Group
) -> None:
    requester = _user("requester_login", make_group)
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": requester})
    approver = _user("approver_withdraw", make_group)
    _set_approvers(make_group)
    req = _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), requester)

    with pytest.raises(LeaveError):
        requests.withdraw(req, approver, TODAY)
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING

    req = requests.withdraw(req, requester, TODAY)
    assert req.status == RequestStatus.WITHDRAWN

    with pytest.raises(LeaveError, match="Энэ хүсэлт шийдэгдсэн байна."):
        requests.withdraw(req, requester, TODAY)


def test_short_balance_at_final_approval_needs_reason(
    employee: Employee, annual: LeaveTypeRow, actor: User, make_group: Group, grants_on: None
) -> None:
    approver = _user("approver_short", make_group)
    _set_approvers(make_group)
    req = _submit(employee, annual, date(2026, 11, 2), date(2026, 11, 27), actor)

    with pytest.raises(LeaveError):
        requests.approve(req, approver, TODAY)
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING

    req = requests.approve(req, approver, TODAY, override_reason="Захирал зөвшөөрсөн")
    assert req.status == RequestStatus.APPROVED
    assert LeaveExt.objects.get(assign_id=req.assign_id).override_reason == "Захирал зөвшөөрсөн"


def test_final_approval_fails_when_dates_now_invalid(
    employee: Employee, annual: LeaveTypeRow, actor: User, make_group: Group, grants_on: None
) -> None:
    approver = _user("approver_stale", make_group)
    _set_approvers(make_group)
    req = _submit(employee, annual, date(2026, 11, 2), date(2026, 11, 13), actor)
    # HR records an overlapping annual leave while the request waits
    records.record(Draft(employee, annual, date(2026, 11, 5), date(2026, 11, 6)), actor, TODAY)

    with pytest.raises(LeaveError):
        requests.approve(req, approver, TODAY)
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING
    assert req.assign_id is None
    assert len(_assigns(employee)) == 1  # only HR's row
    assert not LeaveRequestAction.objects.filter(request=req, action=ActionKind.APPROVED).exists()
    assert not ActivityEntry.objects.filter(employee=employee, message__startswith=LEAVE_REQUEST_APPROVED).exists()


def test_waiting_request_not_counted_in_balance(
    employee: Employee, annual: LeaveTypeRow, actor: User, make_group: Group, grants_on: None
) -> None:
    draft = Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 6))
    before = records.check(draft, TODAY).balance_after
    _set_approvers(make_group)
    _submit(employee, annual, date(2026, 11, 9), date(2026, 11, 13), actor)
    assert records.check(draft, TODAY).balance_after == before


def test_each_action_writes_activity_entry(employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    group1 = Group.objects.create(name="Шат 1 бүлэг")
    group2 = Group.objects.create(name="Шат 2 бүлэг")
    first = _user("approver_log_one", group1)
    second = _user("approver_log_two", group2)
    requester = _user("requester_log")
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": requester})
    _set_approvers(group1, group2)
    before = ActivityEntry.objects.filter(employee=employee).count()  # the hire entry is already there

    rejected = _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), requester)
    requests.approve(rejected, first, TODAY)  # intermediate step
    requests.reject(rejected, second, "Давхцаж байна", TODAY)
    withdrawn = _submit(employee, sick, date(2026, 11, 9), date(2026, 11, 10), requester)
    requests.withdraw(withdrawn, requester, TODAY)

    messages = list(
        ActivityEntry.objects.filter(employee=employee).order_by("pk").values_list("message", flat=True)[before:]
    )
    assert messages[0].startswith(LEAVE_REQUESTED)
    assert messages[1].startswith(LEAVE_REQUEST_STEP_APPROVED)
    assert messages[1].endswith(" (1-р шат)")
    assert messages[2].startswith(LEAVE_REQUEST_REJECTED)
    assert messages[2].endswith(". Давхцаж байна")
    assert messages[3].startswith(LEAVE_REQUESTED)
    assert messages[4].startswith(LEAVE_REQUEST_WITHDRAWN)
    assert len(messages) == 5
    assert set(LeaveRequestAction.objects.filter(request=rejected).values_list("action", flat=True)) == {
        ActionKind.SUBMITTED,
        ActionKind.APPROVED,
        ActionKind.REJECTED,
    }
    assert set(LeaveRequestAction.objects.filter(request=withdrawn).values_list("action", flat=True)) == {
        ActionKind.SUBMITTED,
        ActionKind.WITHDRAWN,
    }


def test_approve_log_says_step_and_override(employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    group1 = Group.objects.create(name="Шат 1 бүлэг")
    group2 = Group.objects.create(name="Шат 2 бүлэг")
    first = _user("approver_tag_one", group1)
    _user("approver_tag_two", group2)  # a real step-2 member, so the HR user below is an override
    hr = _user("hr_override")
    hr.user_permissions.add(Permission.objects.get(codename="approve_leave", content_type__app_label="accounts"))
    _set_approvers(group1, group2)
    before = ActivityEntry.objects.filter(employee=employee).count()
    req = _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), actor)

    req = requests.approve(req, first, TODAY)
    req = requests.approve(req, hr, TODAY)  # step 2 is not theirs: HR override

    messages = list(
        ActivityEntry.objects.filter(employee=employee).order_by("pk").values_list("message", flat=True)[before:]
    )
    assert messages[1].startswith(LEAVE_REQUEST_STEP_APPROVED)
    assert messages[1].endswith(" (1-р шат)")
    assert messages[2].startswith(LEAVE_REQUEST_APPROVED)
    assert messages[2].endswith(" (2-р шат) (эрхээр)")
    assert LeaveRequestAction.objects.get(request=req, step=2).override is True
    assert LeaveRequestAction.objects.get(request=req, step=1).override is False


def test_submit_refuses_long_note(employee: Employee, sick: LeaveTypeRow, actor: User, make_group: Group) -> None:
    _set_approvers(make_group)
    with pytest.raises(LeaveError, match="200 тэмдэгтээс урт"):
        requests.submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), "а" * 201, actor, TODAY)
    assert LeaveRequest.objects.count() == 0
    req = requests.submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), "а" * 200, actor, TODAY)
    assert len(req.note) == 200


def test_reject_refuses_long_reason(employee: Employee, sick: LeaveTypeRow, actor: User, make_group: Group) -> None:
    approver = _user("approver_long_reason", make_group)
    _set_approvers(make_group)
    req = _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), actor)
    with pytest.raises(LeaveError, match="200 тэмдэгтээс урт"):
        requests.reject(req, approver, "б" * 201, TODAY)
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_approve_refuses_long_override_reason(
    employee: Employee, sick: LeaveTypeRow, actor: User, make_group: Group
) -> None:
    approver = _user("approver_long_override", make_group)
    _set_approvers(make_group)
    req = _submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), actor)
    with pytest.raises(LeaveError, match="200 тэмдэгтээс урт"):
        requests.approve(req, approver, TODAY, override_reason="в" * 201)
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING
    assert _assigns(employee) == []
