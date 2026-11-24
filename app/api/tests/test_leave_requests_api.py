"""GET /api/v1/leave/requests and /leave/requests/{pk}: the approver's requests list and the request detail pop-up as
the React page reads them. The rules come from leave.services.request_page; these tests pin the API's shape, its rights,
its paging and the history line."""

from datetime import date, timedelta
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from config import batching
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.utils import timezone
from employees import daily_sync
from employees.models import LEAVE_REQUEST_REJECTED, ActivityEntry, Employee, EmployeeExt, JobRecord
from employees.tests.conftest import _no_offboarding_templates  # noqa: F401 (autouse: no checklist gate here)
from leave.forms import REQUEST_BACKWARDS, REQUEST_TOO_LONG, TOO_LONG_REASON
from leave.models import ActionKind, LeaveRequest, LeaveRequestAction, LeaveSettings, LeaveTypeExt, RequestStatus
from leave.services import ledger
from leave.services import requests as request_service
from leave.services.request_page import list_batch, parse_filter
from leave.services.requests import DECIDED, OVERLAP_WAITING, STEP_MOVED
from leave.tests.conftest import make_employee
from macs.models import LeaveAssign, LeaveTypeRow

from api import leave_requests

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/leave/requests"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"]}
EMPTY_TEXT = "Хүсэлт олдсонгүй"
TODAY = timezone.localdate()
WEEK_START = TODAY + timedelta(days=10)  # a span of seven days always holds working days
WEEK_END = WEEK_START + timedelta(days=6)
LIST_KEYS = {"tab", "status", "statuses", "can_all", "rows", "next_offset", "empty_text"}
ROW_KEYS = {
    "id",
    "employee_name",
    "leave_type",
    "start",
    "end",
    "working_days",
    "waiting",
    "current_step",
    "step_count",
    "rule",
    "status_label",
    "since",
}
DETAIL_KEYS = {
    "id",
    "employee_name",
    "job_line",
    "leave_type",
    "start",
    "end",
    "working_days",
    "created",
    "waiting",
    "current_step",
    "step_count",
    "rule",
    "override",
    "balance_after",
    "warnings",
    "past",
    "status_label",
    "reason",
    "others",
    "history",
    "may",
    "needs_reason",
}


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily sync runs on the first signed-in request of a process; these tests do not want it to write grants."""
    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


@pytest.fixture(autouse=True)
def _approval(db: None) -> None:
    """Approval on, step 1 = the requester's line manager."""
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})


def _user(name: str, group: str | None = None) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    if group is not None:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _viewer(name: str) -> User:
    """Can view leave and the people in scope, and holds no approver role (as test_request_detail's viewer)."""
    user = User.objects.create_user(name, password=PASSWORD)
    user.user_permissions.add(
        Permission.objects.get(codename="view_leave", content_type__app_label="leave"),
        Permission.objects.get(codename="view_employees", content_type__app_label="macs"),
    )
    return User.objects.get(pk=user.pk)


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("leave_req_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def annual(db: None) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=True, is_paid=True)
    return row


@pytest.fixture
def sick(db: None) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Өвчний амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True)
    return row


@pytest.fixture
def employee(actor: User) -> Employee:
    return make_employee(actor, hired=date(2024, 3, 1))


@pytest.fixture
def colleague(actor: User) -> Employee:
    """Same department as `employee` (make_employee's default), with a login that holds no leave right."""
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ22112233")
    EmployeeExt.objects.update_or_create(employee=other, defaults={"user": _user("leave_req_colleague")})
    return other


@pytest.fixture
def manager(actor: User, employee: Employee) -> User:
    """A login (Employee role) that is the line manager of `employee`."""
    boss = make_employee(actor, hired=date(2019, 1, 1), register_no="УБ99000001")
    JobRecord.objects.filter(employee=employee).update(manager=boss)
    user = _user("leave_req_manager", roles.EMPLOYEE)
    EmployeeExt.objects.update_or_create(employee=boss, defaults={"user": user})
    return User.objects.get(pk=user.pk)


@pytest.fixture
def hr() -> User:
    return _user("leave_req_hr", roles.HR)


def _waiting(
    employee: Employee,
    leave_type: LeaveTypeRow,
    actor: User,
    start: date = WEEK_START,
    end: date = WEEK_END,
) -> LeaveRequest:
    return request_service.submit(employee, leave_type, start, end, "", actor, TODAY)


def _detail(req: LeaveRequest) -> str:
    return f"{URL}/{req.pk}"


def _grant(employee: Employee, days: int, actor: User) -> None:
    ledger.manual_grant(employee, date(TODAY.year, 1, 1), date(TODAY.year + 1, 12, 31), days, "тест", actor)


# --- rights and login ----------------------------------------------------------------------------------------------


def test_every_route_needs_a_signed_in_user(actor: User, employee: Employee, sick: LeaveTypeRow) -> None:
    req = _waiting(employee, sick, actor)
    anonymous = Client()
    for url in (URL, _detail(req)):
        response = anonymous.get(url)
        assert response.status_code == 401, url
        assert response.json() == NOT_LOGGED_IN


def test_mine_tab_needs_only_a_signed_in_user() -> None:
    response = _client(_user("leave_req_plain")).get(URL, {"tab": "mine"})
    assert response.status_code == 200
    assert response.json()["rows"] == []


def test_all_tab_needs_the_view_right(actor: User, employee: Employee, sick: LeaveTypeRow) -> None:
    _waiting(employee, sick, actor)
    client = _client(_user("leave_req_employee", roles.EMPLOYEE))
    response = client.get(URL, {"tab": "all"})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_can_all_follows_can_view(manager: User, hr: User) -> None:
    assert _client(manager).get(URL).json()["can_all"] is False
    assert _client(hr).get(URL).json()["can_all"] is True


# --- the list ------------------------------------------------------------------------------------------------------


def test_mine_rows_are_the_services_queue(manager: User, employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    req = _waiting(employee, sick, actor)
    body = _client(manager).get(URL, {"tab": "mine"}).json()
    expected, more = list_batch(manager, parse_filter({"tab": "mine"}), 0, batching.LIST_BATCH, TODAY)
    assert not more
    assert [row["id"] for row in body["rows"]] == [row.req.pk for row in expected] == [req.pk]
    assert set(body) == LIST_KEYS
    assert set(body["rows"][0]) == ROW_KEYS
    assert body["tab"] == "mine"
    assert body["next_offset"] is None
    assert body["empty_text"] == EMPTY_TEXT
    row = body["rows"][0]
    assert row["waiting"] is True
    assert (row["current_step"], row["step_count"]) == (1, req.step_count)
    assert row["rule"] == "Шууд удирдлага"
    assert row["status_label"] == "Хүлээгдэж буй"
    assert row["employee_name"] == employee.full_name
    assert row["since"] == timezone.localtime(req.created_at).date().isoformat()


def test_all_rows_follow_the_services_list_and_the_status_filter(
    hr: User, employee: Employee, sick: LeaveTypeRow, actor: User, manager: User
) -> None:
    waiting = _waiting(employee, sick, actor)
    decided = _waiting(employee, sick, actor, WEEK_START + timedelta(days=20), WEEK_END + timedelta(days=20))
    request_service.approve(decided, manager, TODAY)
    client = _client(hr)

    everything = client.get(URL, {"tab": "all"}).json()
    expected, _ = list_batch(hr, parse_filter({"tab": "all"}), 0, batching.LIST_BATCH, TODAY)
    assert [row["id"] for row in everything["rows"]] == [row.req.pk for row in expected]
    assert {waiting.pk, decided.pk} <= {row["id"] for row in everything["rows"]}

    approved = client.get(URL, {"tab": "all", "status": "approved"}).json()
    assert approved["status"] == "approved"
    assert [row["id"] for row in approved["rows"]] == [decided.pk]


def test_decided_row_has_no_step_rule_or_since(
    hr: User, employee: Employee, sick: LeaveTypeRow, actor: User, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    request_service.approve(req, manager, TODAY)
    [row] = [r for r in _client(hr).get(URL, {"tab": "all"}).json()["rows"] if r["id"] == req.pk]
    assert set(row) == ROW_KEYS
    assert row["waiting"] is False
    assert row["current_step"] is None
    assert row["step_count"] is None
    assert row["rule"] == ""
    assert row["since"] is None
    assert row["status_label"] == "Батлагдсан"


def test_list_is_never_cached(manager: User) -> None:
    assert _client(manager).get(URL)["Cache-Control"] == "no-store"


def test_next_offset_follows_the_batch_size(
    monkeypatch: pytest.MonkeyPatch, hr: User, employee: Employee, sick: LeaveTypeRow, actor: User
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 1)
    _waiting(employee, sick, actor)
    _waiting(employee, sick, actor, WEEK_START + timedelta(days=20), WEEK_END + timedelta(days=20))
    client = _client(hr)
    first = client.get(URL, {"tab": "all"}).json()
    assert len(first["rows"]) == 1
    assert first["next_offset"] == 1

    second = client.get(URL, {"tab": "all", "offset": "1"}).json()
    assert len(second["rows"]) == 1
    assert second["next_offset"] is None


def test_unknown_status_is_the_same_as_no_status(hr: User, employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    _waiting(employee, sick, actor)
    client = _client(hr)
    plain = client.get(URL, {"tab": "all"}).json()
    garbage = client.get(URL, {"tab": "all", "status": "garbage"}).json()
    assert garbage["rows"] == plain["rows"]
    assert garbage["status"] == ""
    assert garbage["next_offset"] == plain["next_offset"]


def test_bad_offset_is_the_first_batch(hr: User, employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    _waiting(employee, sick, actor)
    client = _client(hr)
    first = client.get(URL, {"tab": "all"}).json()
    assert client.get(URL, {"tab": "all", "offset": "abc"}).json()["rows"] == first["rows"]


def test_statuses_lists_the_filters_with_their_labels(hr: User) -> None:
    body = _client(hr).get(URL, {"tab": "all"}).json()
    values = [s["value"] for s in body["statuses"]]
    assert values[:4] == [
        RequestStatus.WAITING,
        RequestStatus.APPROVED,
        RequestStatus.REJECTED,
        RequestStatus.WITHDRAWN,
    ]
    assert {"value": "cancelled", "label": "Цуцалсан"} in body["statuses"]
    assert {"value": "mistake", "label": "Буруу бүртгэсэн"} in body["statuses"]


# --- the detail pop-up ---------------------------------------------------------------------------------------------


def test_approver_may_act_and_sees_the_balance(
    actor: User, employee: Employee, annual: LeaveTypeRow, manager: User
) -> None:
    _grant(employee, 20, actor)
    req = _waiting(employee, annual, actor)
    body = _client(manager).get(_detail(req)).json()
    assert set(body) == DETAIL_KEYS
    assert body["may"] is True
    assert body["override"] is False
    assert body["needs_reason"] is False
    assert body["waiting"] is True
    assert (body["current_step"], body["step_count"]) == (1, req.step_count)
    assert body["rule"] == "Шууд удирдлага"
    assert body["balance_after"] == 20 - req.working_days
    assert body["warnings"] == []
    assert body["status_label"] == "Хүлээгдэж буй"
    assert body["employee_name"] == employee.full_name
    assert body["job_line"] == "Санхүү · Нягтлан"
    assert body["created"] == timezone.localtime(req.created_at).date().isoformat()
    assert body["start"] == WEEK_START.isoformat()
    assert body["end"] == WEEK_END.isoformat()


def test_viewer_reads_but_may_not_act(actor: User, employee: Employee, annual: LeaveTypeRow) -> None:
    _grant(employee, 20, actor)
    req = _waiting(employee, annual, actor)
    body = _client(_viewer("leave_req_viewer")).get(_detail(req)).json()
    assert body["may"] is False
    assert body["override"] is False
    assert body["needs_reason"] is False
    assert body["waiting"] is True


def test_stranger_and_colleague_without_the_right_get_404(
    actor: User, employee: Employee, colleague: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    for user in (_user("leave_req_stranger"), _user("leave_req_colleague_login")):
        response = _client(user).get(_detail(req))
        assert response.status_code == 404
        assert response.json() == NOT_FOUND


def test_missing_request_is_404(manager: User) -> None:
    response = _client(manager).get(f"{URL}/999999")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_needs_reason_for_a_negative_balance(
    actor: User, employee: Employee, annual: LeaveTypeRow, manager: User
) -> None:
    _grant(employee, 1, actor)  # one day against a week of leave
    req = _waiting(employee, annual, actor)
    body = _client(manager).get(_detail(req)).json()
    assert body["balance_after"] < 0
    assert body["needs_reason"] is True


def test_no_needs_reason_with_a_positive_balance(
    actor: User, employee: Employee, annual: LeaveTypeRow, manager: User
) -> None:
    _grant(employee, 20, actor)
    req = _waiting(employee, annual, actor)
    assert _client(manager).get(_detail(req)).json()["needs_reason"] is False


def test_decided_request_has_no_step_rule_or_balance(
    hr: User, employee: Employee, sick: LeaveTypeRow, actor: User, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    request_service.approve(req, manager, TODAY)
    body = _client(hr).get(_detail(req)).json()
    assert body["waiting"] is False
    assert body["current_step"] is None
    assert body["step_count"] is None
    assert body["rule"] == ""
    assert body["balance_after"] is None
    assert body["warnings"] == []
    assert body["needs_reason"] is False
    assert body["may"] is False
    assert body["status_label"] == "Батлагдсан"


def test_history_text_is_the_template_line(hr: User, employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    req = _waiting(employee, sick, actor)
    approver = User.objects.create_user("leave_req_approver", password=PASSWORD, first_name="Болд", last_name="Дорж")
    action = LeaveRequestAction.objects.create(
        request=req, step=1, action=ActionKind.APPROVED, by=approver, override=True, reason="Тохиролцсон"
    )
    history = _client(hr).get(_detail(req)).json()["history"]
    submitted_day = timezone.localtime(req.created_at).date().isoformat()
    assert history[0]["text"] == f"{submitted_day} · Хүсэлт гаргасан · leave_req_actor"
    day = timezone.localtime(action.at).date().isoformat()
    assert history[-1] == {
        "at": day,
        "text": f"{day} · Батласан (1-р шат) (эрхээр) · Дорж Болд · Тохиролцсон",
    }


def test_detail_has_no_salary_or_register_number(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    response = _client(manager).get(_detail(req))
    assert response.status_code == 200
    text = response.content.decode()
    assert "2500000" not in text  # salary
    assert "УБ99112233" not in text  # register number
    assert set(response.json()) == DETAIL_KEYS


def test_detail_is_never_cached(manager: User, actor: User, employee: Employee, sick: LeaveTypeRow) -> None:
    req = _waiting(employee, sick, actor)
    assert _client(manager).get(_detail(req))["Cache-Control"] == "no-store"


def test_others_lists_same_department_people_on_leave(
    actor: User, employee: Employee, colleague: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    _waiting(colleague, sick, actor)
    others = _client(manager).get(_detail(req)).json()["others"]
    assert [o["name"] for o in others] == [colleague.full_name]
    assert others[0]["state"] == "Хүлээгдэж буй"
    assert set(others[0]) == {"name", "start", "end", "state"}


# --- writes: approve, reject, options, check and create ------------------------------------------------------------

REJECT_REQUIRED = "Татгалзсан шалтгаан бичнэ үү."  # RejectForm's required text
NEEDS_REASON = "Үлдэгдэл хүрэлцэхгүй тул шалтгаан бичнэ үү."  # records._validated: a negative balance without a reason
SAVED = {"ok": True, "error": "", "form_errors": [], "field_errors": {}}


def _post(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, data=body, content_type="application/json")


def _refused(error: str = "", **field_errors: list[str]) -> dict[str, Any]:
    return {"ok": False, "error": error, "form_errors": [], "field_errors": field_errors}


def _no_request_right(employee: Employee) -> User:
    """The employee's own login without the request right. New logins get the Employee role, so it is removed here."""
    user = EmployeeExt.objects.get(employee=employee).user
    user.groups.clear()
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _with_request_right(name: str) -> User:
    """A login with the staff request right and no own employee record."""
    user = _user(name)
    user.user_permissions.add(Permission.objects.get(codename="request_own_leave", content_type__app_label="leave"))
    return User.objects.get(pk=user.pk)  # fresh permission cache


@pytest.fixture
def requester(employee: Employee) -> User:
    """The staff side: the login is the employee's own record and holds the request right."""
    user = _with_request_right("leave_req_requester")
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": user})
    return user


def _request_body(leave_type: LeaveTypeRow, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "leave_type": leave_type.pk,
        "start_date": WEEK_START.isoformat(),
        "end_date": WEEK_END.isoformat(),
        "note": "",
    }
    body.update(changes)
    return body


def _approve_url(req: LeaveRequest) -> str:
    return f"{URL}/{req.pk}/approve"


def _reject_url(req: LeaveRequest) -> str:
    return f"{URL}/{req.pk}/reject"


# --- approve ---


def test_approve_one_step_writes_the_leave(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    response = _post(_client(manager), _approve_url(req), {})
    assert response.status_code == 200
    assert response.json() == SAVED
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED
    assert LeaveAssign.objects.filter(employee=employee).count() == 1


def test_approve_moves_a_two_step_request_on(actor: User, employee: Employee, sick: LeaveTypeRow) -> None:
    LeaveSettings.objects.filter(pk=1).update(
        approval1_manager=False,
        approval1_group=Group.objects.create(name="Шат 1"),
        approval2_group=Group.objects.create(name="Шат 2"),
    )
    first = _user("leave_req_first", "Шат 1")
    second = _user("leave_req_second", "Шат 2")
    req = _waiting(employee, sick, actor)

    assert _post(_client(first), _approve_url(req), {"step": 1}).json() == SAVED
    req.refresh_from_db()
    assert (req.status, req.current_step) == (RequestStatus.WAITING, 2)
    assert not LeaveAssign.objects.filter(employee=employee).exists()

    assert _post(_client(second), _approve_url(req), {"step": 2}).json() == SAVED
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED
    assert LeaveAssign.objects.filter(employee=employee).count() == 1


def test_approve_is_404_for_a_stranger_and_for_the_requester(
    actor: User, employee: Employee, sick: LeaveTypeRow, requester: User
) -> None:
    req = _waiting(employee, sick, actor)
    for user in (_user("leave_req_stranger"), requester):
        response = _post(_client(user), _approve_url(req), {})
        assert response.status_code == 404
        assert response.json() == NOT_FOUND


def test_stale_step_is_refused(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    assert _post(_client(manager), _approve_url(req), {"step": 2}).json() == _refused(STEP_MOVED)
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_approve_of_a_request_decided_meanwhile_is_refused(
    monkeypatch: pytest.MonkeyPatch, actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    """can_act refuses a decided request before the service runs, so the race is simulated: the approver's screen
    loaded the request while it still waited, and someone else decided it before the approval was sent."""
    req = _waiting(employee, sick, actor)
    loaded_before = LeaveRequest.objects.get(pk=req.pk)
    request_service.approve(req, manager, TODAY)
    monkeypatch.setattr(leave_requests, "visible_request", lambda *args: (loaded_before, True, False))
    assert _post(_client(manager), _approve_url(req), {}).json() == _refused(DECIDED)


def test_negative_balance_needs_a_reason(actor: User, employee: Employee, annual: LeaveTypeRow, manager: User) -> None:
    _grant(employee, 1, actor)  # one day against a week of leave
    req = _waiting(employee, annual, actor)
    assert _post(_client(manager), _approve_url(req), {}).json() == _refused(NEEDS_REASON)
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING
    assert _post(_client(manager), _approve_url(req), {"override_reason": "Захирал зөвшөөрсөн"}).json() == SAVED
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED


def test_approve_reason_of_201_characters_is_refused(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    body = _post(_client(manager), _approve_url(req), {"override_reason": "а" * 201}).json()
    assert body == _refused(override_reason=[TOO_LONG_REASON])


# --- reject ---


def test_reject_needs_a_reason(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    for reason in ("", "   "):
        body = _post(_client(manager), _reject_url(req), {"reason": reason}).json()
        assert body == _refused(reason=[REJECT_REQUIRED])
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_reject_reason_of_201_characters_is_refused(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    assert _post(_client(manager), _reject_url(req), {"reason": "а" * 201}).json() == _refused(reason=[TOO_LONG_REASON])


def test_reject_writes_the_status_and_the_log(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    assert _post(_client(manager), _reject_url(req), {"reason": "  Хэт олон өдөр  "}).json() == SAVED
    req.refresh_from_db()
    assert req.status == RequestStatus.REJECTED
    assert req.reason == "Хэт олон өдөр"
    entry = ActivityEntry.objects.get(employee=employee, message__startswith=LEAVE_REQUEST_REJECTED)
    assert entry.message.endswith(". Хэт олон өдөр")
    assert not LeaveAssign.objects.filter(employee=employee).exists()


def test_reject_is_404_for_a_stranger(actor: User, employee: Employee, sick: LeaveTypeRow) -> None:
    req = _waiting(employee, sick, actor)
    response = _post(_client(_user("leave_req_stranger")), _reject_url(req), {"reason": "Үгүй"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


# --- options and check: the staff side ---


def test_options_refused_without_the_right_own_record_or_approval(
    sick: LeaveTypeRow, colleague: Employee, requester: User
) -> None:
    no_right = _no_request_right(colleague)  # its own record, no request right
    no_record = _with_request_right("leave_req_no_record")  # the right, but no own record
    for user in (no_right, no_record):
        response = _client(user).get(f"{URL}/options")
        assert response.status_code == 403
        assert response.json() == FORBIDDEN
    assert _post(_client(no_right), f"{URL}/check", _request_body(sick)).status_code == 403

    LeaveSettings.objects.filter(pk=1).update(approval1_manager=False)
    response = _client(requester).get(f"{URL}/options")
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_options_lists_the_requestable_types(annual: LeaveTypeRow, sick: LeaveTypeRow, requester: User) -> None:
    off = LeaveTypeRow.objects.create(name="Идэвхгүй")
    LeaveTypeExt.objects.create(leave_type=off, is_active=False)
    stopped = LeaveTypeRow.objects.create(name="Хориглосон")
    LeaveTypeExt.objects.create(leave_type=stopped, staff_may_request=False)
    response = _client(requester).get(f"{URL}/options")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"types"}
    assert {t["value"] for t in body["types"]} == {annual.pk, sick.pk}
    assert {"value": annual.pk, "label": str(annual)} in body["types"]


def test_check_of_an_invalid_form_is_not_valid(sick: LeaveTypeRow, requester: User) -> None:
    backwards = _request_body(sick, start_date=WEEK_END.isoformat(), end_date=WEEK_START.isoformat())
    empty = {"leave_type": None, "start_date": None, "end_date": None, "note": ""}
    for body in (backwards, empty):
        assert _post(_client(requester), f"{URL}/check", body).json() == {
            "valid": False,
            "working_days": 0,
            "balance_after": None,
            "period": None,
            "errors": [],
            "warnings": [],
        }


def test_check_of_a_valid_form_gives_the_days(sick: LeaveTypeRow, requester: User) -> None:
    body = _post(_client(requester), f"{URL}/check", _request_body(sick)).json()
    assert set(body) == {"valid", "working_days", "balance_after", "period", "errors", "warnings"}
    assert body["valid"] is True
    assert body["working_days"] > 0
    assert body["errors"] == []


def test_check_reports_an_overlap_and_creates_nothing(
    actor: User, employee: Employee, sick: LeaveTypeRow, requester: User
) -> None:
    _waiting(employee, sick, actor)
    before = LeaveRequest.objects.count()
    body = _post(_client(requester), f"{URL}/check", _request_body(sick)).json()
    assert body["valid"] is False
    assert OVERLAP_WAITING in body["errors"]
    assert LeaveRequest.objects.count() == before


# --- create ---


def test_create_is_refused_without_the_staff_right(sick: LeaveTypeRow, colleague: Employee) -> None:
    assert _post(_client(_no_request_right(colleague)), URL, _request_body(sick)).status_code == 403
    assert not LeaveRequest.objects.exists()


def test_create_writes_a_waiting_request_for_the_own_record(
    employee: Employee, colleague: Employee, sick: LeaveTypeRow, requester: User
) -> None:
    body = _request_body(sick, employee=colleague.pk, note="Гэр бүл")  # someone else's id is ignored
    assert _post(_client(requester), URL, body).json() == SAVED
    req = LeaveRequest.objects.get()
    assert req.employee == employee
    assert req.status == RequestStatus.WAITING
    assert req.note == "Гэр бүл"


def test_create_refuses_end_before_start_and_long_note(sick: LeaveTypeRow, requester: User) -> None:
    backwards = _request_body(sick, start_date=WEEK_END.isoformat(), end_date=WEEK_START.isoformat())
    assert _post(_client(requester), URL, backwards).json() == {
        "ok": False,
        "error": "",
        "form_errors": [REQUEST_BACKWARDS],
        "field_errors": {},
    }
    assert _post(_client(requester), URL, _request_body(sick, note="а" * 201)).json() == _refused(
        note=[REQUEST_TOO_LONG]
    )
    assert not LeaveRequest.objects.exists()


def test_create_refused_with_the_service_message(
    actor: User, employee: Employee, sick: LeaveTypeRow, requester: User
) -> None:
    _waiting(employee, sick, actor)
    assert _post(_client(requester), URL, _request_body(sick)).json() == _refused(OVERLAP_WAITING)
    assert LeaveRequest.objects.count() == 1


def test_create_refuses_a_type_staff_cannot_request(sick: LeaveTypeRow, requester: User) -> None:
    off = LeaveTypeRow.objects.create(name="Идэвхгүй")
    LeaveTypeExt.objects.create(leave_type=off, is_active=False)
    body = _post(_client(requester), URL, _request_body(off)).json()
    assert body["ok"] is False
    assert set(body["field_errors"]) == {"leave_type"}
    assert not LeaveRequest.objects.exists()
