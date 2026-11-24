"""The requests list's rules as service calls: the cases of test_request_views.py for the list, without the page."""

from datetime import date, timedelta

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from employees.models import Employee, EmployeeExt, JobRecord
from macs.models import LeaveAssign, LeaveTypeRow

from leave.models import LeaveRequest, LeaveSettings, RequestStatus
from leave.services import records, writes
from leave.services import requests as request_service
from leave.services.request_page import STATUS_FILTERS, RequestFilter, Row, list_batch, parse_filter
from leave.tests.conftest import make_employee

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105


def _user(name: str, *groups: Group) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(*groups)
    return user


def _hr_viewer(name: str) -> User:
    """An HR user with the list right («Бүгд») and the people right, and no approver role."""
    viewer = _user(name)
    viewer.user_permissions.add(
        Permission.objects.get(codename="view_leave", content_type__app_label="leave"),
        Permission.objects.get(codename="view_employees", content_type__app_label="macs"),
    )
    return User.objects.get(pk=viewer.pk)  # a fresh object, so no permission is cached from before


@pytest.fixture
def approval(db: None) -> None:
    """Approval on, step 1 = the requester's line manager."""
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})


@pytest.fixture
def manager(actor: User, employee: Employee, approval: None) -> User:
    """A login (Employee role) that is the line manager of `employee`."""
    boss = make_employee(actor, hired=date(2019, 1, 1), register_no="УБ99000001")
    Employee.objects.filter(pk=boss.pk).update(given_name="Болд")
    JobRecord.objects.filter(employee=employee).update(manager=boss)
    user = _user("manager", Group.objects.get_or_create(name=roles.EMPLOYEE)[0])
    EmployeeExt.objects.update_or_create(employee=boss, defaults={"user": user})
    return User.objects.get(pk=user.pk)


def _waiting(
    employee: Employee, leave_type: LeaveTypeRow, actor: User, start: date = date(2026, 11, 2)
) -> LeaveRequest:
    return request_service.submit(employee, leave_type, start, start + timedelta(days=1), "", actor, TODAY)


def _approved_on(employee: Employee, leave_type: LeaveTypeRow, actor: User, manager: User, start: date) -> LeaveRequest:
    req = _waiting(employee, leave_type, actor, start)
    request_service.approve(req, manager, TODAY)
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED and req.assign_id is not None
    return req


def _batch(user: User, query: dict[str, str], offset: int = 0, size: int = 50) -> tuple[list[Row], bool]:
    return list_batch(user, parse_filter(query), offset, size, TODAY)


def _pks(user: User, query: dict[str, str]) -> set[int]:
    rows, more = _batch(user, query)
    assert not more
    return {row.req.pk for row in rows}


# --- parse_filter


def test_junk_tab_is_the_mine_queue() -> None:
    assert parse_filter({"tab": "garbage"}) == RequestFilter(tab="mine", status="")
    assert parse_filter({}).tab == "mine"


def test_all_tab_keeps_a_known_status_and_drops_junk() -> None:
    assert parse_filter({"tab": "all", "status": "approved"}) == RequestFilter(tab="all", status="approved")
    assert parse_filter({"tab": "all", "status": "garbage"}).status == ""
    assert parse_filter({"tab": "all"}).status == ""


def test_status_is_ignored_on_the_mine_queue() -> None:
    assert parse_filter({"tab": "mine", "status": "approved"}).status == ""
    assert parse_filter({"status": "rejected"}).status == ""


def test_status_filter_values_are_the_list_values() -> None:
    values = [value for value, _ in STATUS_FILTERS]
    assert values[-2:] == ["cancelled", "mistake"]
    assert set(RequestStatus.values) <= set(values)


# --- list_batch: the mine queue


def test_mine_queue_holds_only_requests_the_user_may_decide(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    mine = _waiting(employee, sick, actor)
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000002")  # no manager set
    not_mine = request_service.submit(other, sick, date(2026, 12, 1), date(2026, 12, 1), "", actor, TODAY)
    assert _pks(manager, {"tab": "mine"}) == {mine.pk}
    assert not_mine.pk not in _pks(manager, {"tab": "mine"})
    assert _pks(_user("stranger"), {"tab": "mine"}) == set()


def test_mine_queue_is_oldest_first_by_created_at_then_pk(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    first = _waiting(employee, sick, actor, date(2026, 11, 2))
    second = _waiting(employee, sick, actor, date(2026, 11, 9))
    rows, more = _batch(manager, {"tab": "mine"})
    assert not more
    assert [row.req.pk for row in rows] == sorted([first.pk, second.pk], key=lambda pk: (_created(pk), pk))


def _created(pk: int) -> object:
    return LeaveRequest.objects.get(pk=pk).created_at


def test_waiting_row_has_rule_and_since(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    rows, _ = _batch(manager, {"tab": "mine"})
    (row,) = rows
    assert row.req.pk == req.pk
    assert row.rule  # the approver rule's label
    assert row.since == req.created_at  # step 1 waits since the submission


# --- list_batch: the all list


def test_all_list_is_newest_first(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    older = _waiting(employee, sick, actor, date(2026, 11, 2))
    newer = _waiting(employee, sick, actor, date(2026, 11, 9))
    rows, more = _batch(_hr_viewer("hr_order"), {"tab": "all"})
    assert not more
    pks = [row.req.pk for row in rows]
    assert pks.index(newer.pk) < pks.index(older.pk)


def test_all_list_needs_visible_requests(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    _waiting(employee, sick, actor)
    assert _pks(_user("plain_all"), {"tab": "all"}) == set()


def test_decided_row_has_no_rule_and_no_since(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _approved_on(employee, sick, actor, manager, date(2026, 11, 2))
    rows, _ = _batch(_hr_viewer("hr_decided"), {"tab": "all"})
    (row,) = [r for r in rows if r.req.pk == req.pk]
    assert row.rule == "" and row.since is None
    assert row.status == ""  # not cancelled and not a mistake


def test_row_is_a_row_dataclass_with_status_default(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    row = Row(req, "rule")
    assert row.since is None and row.status == ""


# --- list_batch: status filters


@pytest.fixture
def leave_outcomes(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> dict[str, LeaveRequest]:
    """Three approved requests: one normal, one whose leave was cancelled before it started, one whose leave
    was cancelled after it started (a mistake)."""
    normal = _approved_on(employee, sick, actor, manager, date(2026, 11, 2))
    cancelled = _approved_on(employee, sick, actor, manager, date(2026, 11, 9))
    leave = LeaveAssign.objects.get(pk=cancelled.assign_id)
    records.cancel(leave, writes.snapshot(leave), "Төлөвлөгөө өөрчлөгдсөн", actor, TODAY)
    mistake = _approved_on(employee, sick, actor, manager, date(2026, 11, 16))
    leave = LeaveAssign.objects.get(pk=mistake.assign_id)
    records.cancel(leave, writes.snapshot(leave), "Буруу оруулсан", actor, date(2026, 11, 20))
    return {"normal": normal, "cancelled": cancelled, "mistake": mistake}


def test_approved_leaves_out_cancelled_and_mistake(leave_outcomes: dict[str, LeaveRequest]) -> None:
    viewer = _hr_viewer("hr_approved")
    assert _pks(viewer, {"tab": "all", "status": "approved"}) == {leave_outcomes["normal"].pk}


def test_cancelled_and_mistake_split_on_the_mistake_flag(leave_outcomes: dict[str, LeaveRequest]) -> None:
    viewer = _hr_viewer("hr_outcomes")
    assert _pks(viewer, {"tab": "all", "status": "cancelled"}) == {leave_outcomes["cancelled"].pk}
    assert _pks(viewer, {"tab": "all", "status": "mistake"}) == {leave_outcomes["mistake"].pk}


def test_cancelled_rows_show_their_status(leave_outcomes: dict[str, LeaveRequest]) -> None:
    rows, _ = _batch(_hr_viewer("hr_row_status"), {"tab": "all"})
    by_pk = {row.req.pk: row for row in rows}
    assert by_pk[leave_outcomes["cancelled"].pk].status == "Цуцалсан"
    assert by_pk[leave_outcomes["mistake"].pk].status == "Буруу бүртгэсэн"
    assert by_pk[leave_outcomes["normal"].pk].status == ""


def test_junk_status_is_dropped_so_all_rows_show(leave_outcomes: dict[str, LeaveRequest]) -> None:
    viewer = _hr_viewer("hr_unknown")
    everything = {leave_outcomes[k].pk for k in ("normal", "cancelled", "mistake")}
    assert _pks(viewer, {"tab": "all", "status": "garbage"}) == everything


def test_status_with_no_requests_lists_none(leave_outcomes: dict[str, LeaveRequest]) -> None:
    assert _pks(_hr_viewer("hr_rejected"), {"tab": "all", "status": "rejected"}) == set()


# --- list_batch: size and the more-flag


def test_size_and_more_flag_on_the_mine_queue(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    for day in (2, 9, 16):
        _waiting(employee, sick, actor, date(2026, 11, day))
    first, more = _batch(manager, {"tab": "mine"}, 0, 2)
    assert len(first) == 2 and more
    rest, more = _batch(manager, {"tab": "mine"}, 2, 2)
    assert len(rest) == 1 and not more


def test_size_and_more_flag_on_the_all_list(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    for day in (2, 9, 16):
        _waiting(employee, sick, actor, date(2026, 11, day))
    viewer = _hr_viewer("hr_paging")
    first, more = _batch(viewer, {"tab": "all"}, 0, 2)
    assert len(first) == 2 and more
    rest, more = _batch(viewer, {"tab": "all"}, 2, 2)
    assert len(rest) == 1 and not more
    assert {r.req.pk for r in first}.isdisjoint({r.req.pk for r in rest})
