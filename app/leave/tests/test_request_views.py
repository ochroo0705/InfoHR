from datetime import UTC, date, datetime, timedelta

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from employees.models import Employee, EmployeeExt, JobRecord
from macs.models import Entitlement, LeaveAssign, LeaveTypeRow

from leave.forms import REQUEST_BACKWARDS
from leave.models import ActionKind, LeaveRequest, LeaveRequestAction, LeaveSettings, LeaveTypeExt, RequestStatus
from leave.services import records, writes
from leave.services import requests as request_service
from leave.services.records import Draft
from leave.templatetags import leave_tags
from leave.tests.conftest import make_employee

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105
TOO_LONG = "а" * 201


def _client(user: User) -> Client:
    c = Client()
    c.force_login(user)
    return c


def _user(name: str, *groups: Group) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(*groups)
    return user


def _settings(**values: object) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults=values)


@pytest.fixture
def approval(db: None) -> None:
    """Approval on, step 1 = the requester's line manager."""
    _settings(approval1_manager=True)


@pytest.fixture
def manager(actor: User, employee: Employee, approval: None) -> User:
    """A login (Employee role) that is the line manager of `employee`."""
    boss = make_employee(actor, hired=date(2019, 1, 1), register_no="УБ99000001")
    Employee.objects.filter(pk=boss.pk).update(given_name="Болд")
    JobRecord.objects.filter(employee=employee).update(manager=boss)
    user = _user("manager", Group.objects.get_or_create(name=roles.EMPLOYEE)[0])
    EmployeeExt.objects.update_or_create(employee=boss, defaults={"user": user})
    return user


def _waiting(employee: Employee, leave_type: LeaveTypeRow, actor: User) -> LeaveRequest:
    return request_service.submit(employee, leave_type, date(2026, 11, 2), date(2026, 11, 3), "", actor, TODAY)


def _detail(req: LeaveRequest) -> str:
    return reverse("leave:request_detail", args=[req.pk])


def test_approver_without_view_leave_sees_own_queue_only(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    _waiting(employee, sick, actor)
    c = _client(manager)
    resp = c.get(reverse("leave:requests"))
    assert resp.status_code == 200
    assert employee.given_name in resp.content.decode()
    assert c.get(reverse("leave:requests") + "?tab=all").status_code == 403


def test_queue_hides_requests_this_user_does_not_decide(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000002")
    Employee.objects.filter(pk=other.pk).update(given_name="Дорж")
    _waiting(employee, sick, actor)
    request_service.submit(other, sick, date(2026, 12, 1), date(2026, 12, 1), "", actor, TODAY)  # no manager set
    body = _client(manager).get(reverse("leave:requests")).content.decode()
    assert "Сараа" in body
    assert "Дорж" not in body


def test_detail_hidden_from_non_approver(actor: User, employee: Employee, sick: LeaveTypeRow, approval: None) -> None:
    req = _waiting(employee, sick, actor)
    stranger = _user("stranger")
    assert _client(stranger).get(_detail(req)).status_code == 404


def test_detail_shows_no_salary_or_personal_data(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    resp = _client(manager).get(_detail(req))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Сараа" in body
    assert "99112233" not in body  # work phone and register number
    assert "2500000" not in body  # salary


def test_detail_offers_approve_and_reject_to_approver(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    body = _client(manager).get(_detail(req)).content.decode()
    assert reverse("leave:request_approve", args=[req.pk]) in body
    assert reverse("leave:request_reject", args=[req.pk]) in body


def test_view_leave_user_sees_detail_read_only(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    req = _waiting(employee, sick, actor)
    viewer = _user("viewer")
    viewer.user_permissions.add(
        Permission.objects.get(codename="view_leave", content_type__app_label="leave"),
        Permission.objects.get(codename="view_employees", content_type__app_label="macs"),
    )
    resp = _client(viewer).get(_detail(req))
    assert resp.status_code == 200
    assert reverse("leave:request_approve", args=[req.pk]) not in resp.content.decode()


def test_all_tab_lists_every_visible_request_for_view_leave(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    _waiting(employee, sick, actor)
    viewer = _user("viewer")
    viewer.user_permissions.add(
        Permission.objects.get(codename="view_leave", content_type__app_label="leave"),
        Permission.objects.get(codename="view_employees", content_type__app_label="macs"),
    )
    resp = _client(viewer).get(reverse("leave:requests") + "?tab=all")
    assert resp.status_code == 200
    assert "Сараа" in resp.content.decode()


def test_approve_post_moves_step_and_returns_done(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    hr = Group.objects.create(name="Нягтлан HR")
    _settings(approval2_group=hr)
    req = _waiting(employee, sick, actor)
    resp = _client(manager).post(reverse("leave:request_approve", args=[req.pk]), {"override_reason": ""})
    assert resp.status_code == 204
    assert resp["HX-Refresh"] == "true"
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING
    assert req.current_step == 2


def test_final_approve_marks_request_approved(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    assert _client(manager).post(reverse("leave:request_approve", args=[req.pk]), {}).status_code == 204
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED
    assert req.assign_id is not None


def test_approve_by_non_approver_is_404(actor: User, employee: Employee, sick: LeaveTypeRow, approval: None) -> None:
    req = _waiting(employee, sick, actor)
    stranger = _user("stranger")
    resp = _client(stranger).post(reverse("leave:request_approve", args=[req.pk]), {})
    assert resp.status_code == 404
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_approve_reason_too_long_shows_error_not_500(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    resp = _client(manager).post(reverse("leave:request_approve", args=[req.pk]), {"override_reason": TOO_LONG})
    assert resp.status_code == 200
    assert "200 тэмдэгт" in resp.content.decode()
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_reject_modal_opens_with_reason_field(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _waiting(employee, sick, actor)
    resp = _client(manager).get(reverse("leave:request_reject", args=[req.pk]))
    assert resp.status_code == 200
    assert 'name="reason"' in resp.content.decode()


def test_reject_requires_reason(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    c = _client(manager)
    url = reverse("leave:request_reject", args=[req.pk])
    resp = c.post(url, {"reason": "   "})
    assert resp.status_code == 200
    assert "Татгалзсан шалтгаан бичнэ үү." in resp.content.decode()
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_reject_reason_too_long_refused(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    resp = _client(manager).post(reverse("leave:request_reject", args=[req.pk]), {"reason": TOO_LONG})
    assert resp.status_code == 200
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_reject_with_reason_marks_rejected(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = _waiting(employee, sick, actor)
    resp = _client(manager).post(reverse("leave:request_reject", args=[req.pk]), {"reason": "Ачаалал их байна"})
    assert resp.status_code == 204
    req.refresh_from_db()
    assert req.status == RequestStatus.REJECTED
    assert req.reason == "Ачаалал их байна"


def test_requests_list_fixed_queries(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    def add(n: int, first: int) -> None:
        for i in range(n):
            start = date(2027, 1, 4) + timedelta(days=(first + i) * 7)
            LeaveRequest.objects.create(
                employee=employee,
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
            assert _client(manager).get(reverse("leave:requests")).status_code == 200
        return len(ctx.captured_queries)

    add(5, 0)
    few = count()
    add(35, 5)
    assert count() == few


def test_nav_link_shown_only_when_relevant(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    link = f'href="{reverse("leave:requests")}"'
    assert link not in _client(manager).get(reverse("leave:requests")).content.decode()  # no items yet
    _waiting(employee, sick, actor)
    assert link in _client(manager).get(reverse("leave:requests")).content.decode()
    stranger = _user("stranger")
    assert link not in _client(stranger).get(reverse("leave:requests")).content.decode()
    _settings(approval1_manager=False)
    # approval off does not touch waiting requests (spec 5.1): the approver still sees the link while one waits
    assert link in _client(manager).get(reverse("leave:requests")).content.decode()
    LeaveRequest.objects.update(status=RequestStatus.WITHDRAWN)
    assert link not in _client(manager).get(reverse("leave:requests")).content.decode()


def _annual_request(employee: Employee, annual: LeaveTypeRow, actor: User) -> LeaveRequest:
    """A waiting request written straight to the table: a request long enough that the balance cannot cover it."""
    return LeaveRequest.objects.create(
        employee=employee,
        leave_type=annual,
        start_date=date(2026, 3, 2),
        end_date=date(2027, 2, 26),
        working_days=260,
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )


def test_detail_get_writes_no_grants(
    actor: User, employee: Employee, annual: LeaveTypeRow, grants_on: None, manager: User
) -> None:
    req = _annual_request(employee, annual, actor)
    before = Entitlement.objects.count()
    assert _client(manager).get(_detail(req)).status_code == 200
    assert Entitlement.objects.count() == before


def test_detail_lists_peers_on_leave_and_waiting_inside_scope_only(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    boss = EmployeeExt.objects.get(user=manager).employee
    AccessScope.objects.create(user=manager, limited=True, own_team=True)  # the manager's own team only
    on_leave = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000002")
    waiting = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000003")
    outside = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000004")
    Employee.objects.filter(pk=on_leave.pk).update(given_name="Аня")
    Employee.objects.filter(pk=waiting.pk).update(given_name="Гэрэл")
    Employee.objects.filter(pk=outside.pk).update(given_name="Цэцэг")
    JobRecord.objects.filter(employee__in=[on_leave, waiting]).update(manager=boss)
    records.record(
        Draft(employee=on_leave, leave_type=sick, start_date=date(2026, 11, 2), end_date=date(2026, 11, 3)),
        actor,
        TODAY,
    )
    req = _waiting(employee, sick, actor)
    request_service.submit(waiting, sick, date(2026, 11, 2), date(2026, 11, 2), "", actor, TODAY)
    body = _client(manager).get(_detail(req)).content.decode()
    assert "Аня" in body
    assert "Гэрэл" in body
    assert "Цэцэг" not in body


def test_approve_needing_override_with_empty_reason_stays_waiting(
    actor: User, employee: Employee, annual: LeaveTypeRow, grants_on: None, manager: User
) -> None:
    req = _annual_request(employee, annual, actor)
    resp = _client(manager).post(reverse("leave:request_approve", args=[req.pk]), {"override_reason": ""})
    assert resp.status_code == 200
    assert "Үлдэгдэл хүрэлцэхгүй тул шалтгаан бичнэ үү." in resp.content.decode()
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_detail_shows_past_dates_note(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    req = LeaveRequest.objects.create(
        employee=employee,
        leave_type=sick,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        working_days=2,
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )
    assert "өнгөрсөн огноотой" in _client(manager).get(_detail(req)).content.decode()


def test_waiting_since_is_last_approval_of_previous_step(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = LeaveRequest.objects.create(
        employee=employee,
        leave_type=sick,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 1),
        working_days=1,
        step1_manager=False,
        step2_manager=True,
        step_count=2,
        current_step=2,
        created_by=actor,
    )
    action = LeaveRequestAction.objects.create(request=req, step=1, action=ActionKind.APPROVED, by=actor)
    LeaveRequestAction.objects.filter(pk=action.pk).update(at=datetime(2026, 10, 1, 9, tzinfo=UTC))
    LeaveRequest.objects.filter(pk=req.pk).update(created_at=datetime(2026, 9, 1, 9, tzinfo=UTC))
    assert "2026-10-01" in _client(manager).get(reverse("leave:requests")).content.decode()


def test_plain_user_nav_adds_no_queue_work(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = _user("plain", Group.objects.get_or_create(name=roles.EMPLOYEE)[0])

    def queue_must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("the queue was worked out for a user who can decide nothing")

    monkeypatch.setattr(leave_tags, "waiting_for_cached", queue_must_not_run)
    _waiting(employee, sick, actor)  # waiting requests exist, but none is this user's

    def nav_queries(approval_on: bool) -> int:
        _settings(approval1_manager=approval_on)
        request = RequestFactory().get("/")
        request.user = plain
        with CaptureQueriesContext(connection) as ctx:
            leave_tags.requests_nav({"request": request})
        return len(ctx.captured_queries)

    off = nav_queries(False)
    on = nav_queries(True)
    assert on - off <= 6


def test_no_grant_for_start_date_asks_for_reason_and_approves_with_it(
    actor: User, employee: Employee, annual: LeaveTypeRow, manager: User
) -> None:
    """Annual type with no grant period (grants off): the reason field is shown, and a reason lets the leave through."""
    req = LeaveRequest.objects.create(
        employee=employee,
        leave_type=annual,
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 3),
        working_days=2,
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )
    c = _client(manager)
    assert 'name="override_reason"' in c.get(_detail(req)).content.decode()
    resp = c.post(reverse("leave:request_approve", args=[req.pk]), {"override_reason": "Тохиролцсон"})
    assert resp.status_code == 204
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED


# --- Staff side (Task 6): the request form, check, withdraw. The employee is always the logged-in user's own record.


def _staff_login(employee: Employee, name: str = "staff") -> User:
    user = _user(name, Group.objects.get_or_create(name=roles.EMPLOYEE)[0])
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": user})
    return user


def _form_data(leave_type: LeaveTypeRow, **extra: object) -> dict[str, object]:
    data: dict[str, object] = {
        "leave_type": leave_type.pk,
        "start_date": "2027-11-02",
        "end_date": "2027-11-03",
        "note": "",
    }
    data.update(extra)
    return data


def test_request_form_offers_only_requestable_types(
    actor: User, employee: Employee, sick: LeaveTypeRow, annual: LeaveTypeRow, approval: None
) -> None:
    LeaveTypeExt.objects.filter(pk=annual.pk).update(staff_may_request=False)
    body = _client(_staff_login(employee)).get(reverse("leave:request_new")).content.decode()
    assert f'<option value="{sick.pk}"' in body
    assert f'<option value="{annual.pk}"' not in body


def test_request_post_creates_waiting_request_for_own_record(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000009")
    c = _client(_staff_login(employee))
    resp = c.post(reverse("leave:request_new"), _form_data(sick, employee=other.pk))
    assert resp.status_code == 204
    assert resp["HX-Refresh"] == "true"
    req = LeaveRequest.objects.get()
    assert req.employee_id == employee.pk
    assert req.status == RequestStatus.WAITING
    assert not LeaveRequest.objects.filter(employee=other).exists()


def test_request_form_refuses_when_approval_off(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    _settings(approval1_manager=False)
    c = _client(_staff_login(employee))
    assert c.get(reverse("leave:request_new")).status_code == 403
    assert c.post(reverse("leave:request_new"), _form_data(sick)).status_code == 403
    assert not LeaveRequest.objects.exists()


def test_request_form_needs_the_right(actor: User, employee: Employee, sick: LeaveTypeRow, approval: None) -> None:
    user = _user("noright")
    user.groups.clear()  # every new user gets the Employee role (accounts/signals.py): remove it for this case
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": user})
    assert _client(user).get(reverse("leave:request_new")).status_code == 403


def test_request_note_too_long_shows_message_not_500(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    resp = _client(_staff_login(employee)).post(reverse("leave:request_new"), _form_data(sick, note=TOO_LONG))
    assert resp.status_code == 200
    assert "Тайлбар 200 тэмдэгтээс урт байж болохгүй." in resp.content.decode()
    assert not LeaveRequest.objects.exists()


def test_request_end_before_start_is_refused(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    resp = _client(_staff_login(employee)).post(
        reverse("leave:request_new"), _form_data(sick, start_date="2027-11-05", end_date="2027-11-02")
    )
    assert resp.status_code == 200
    assert not LeaveRequest.objects.exists()


def test_request_form_shows_backwards_dates_message(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    resp = _client(_staff_login(employee)).post(
        reverse("leave:request_new"), _form_data(sick, start_date="2027-11-05", end_date="2027-11-02")
    )
    assert resp.status_code == 200
    assert REQUEST_BACKWARDS in resp.content.decode()
    assert not LeaveRequest.objects.exists()


def test_request_submit_refreshes_the_page(actor: User, employee: Employee, sick: LeaveTypeRow, approval: None) -> None:
    resp = _client(_staff_login(employee)).post(reverse("leave:request_new"), _form_data(sick))
    assert resp.status_code == 204
    assert resp["HX-Refresh"] == "true"


def test_request_check_is_post_only_and_previews(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    c = _client(_staff_login(employee))
    assert c.get(reverse("leave:request_check")).status_code == 405
    resp = c.post(reverse("leave:request_check"), _form_data(sick))
    assert resp.status_code == 200
    assert "ажлын өдөр" in resp.content.decode()
    assert not LeaveRequest.objects.exists()


# No wrapping transaction (ensure_grants must open its own); serialized_rollback keeps the seeded roles.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_request_check_works_outside_a_transaction_and_warns_over_balance(
    actor: User, employee: Employee, annual: LeaveTypeRow, grants_on: None, approval: None
) -> None:
    resp = _client(_staff_login(employee)).post(
        reverse("leave:request_check"), _form_data(annual, start_date="2027-11-02", end_date="2027-11-30")
    )
    assert resp.status_code == 200
    assert "Үлдэгдэл" in resp.content.decode()


def test_withdraw_own_waiting_request(actor: User, employee: Employee, sick: LeaveTypeRow, approval: None) -> None:
    req = _waiting(employee, sick, actor)
    c = _client(_staff_login(employee))
    assert c.get(reverse("leave:request_withdraw", args=[req.pk])).status_code == 405
    assert c.post(reverse("leave:request_withdraw", args=[req.pk])).status_code == 204
    req.refresh_from_db()
    assert req.status == RequestStatus.WITHDRAWN


def test_withdraw_someone_elses_request_is_404(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    req = _waiting(employee, sick, actor)
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99000010")
    c = _client(_staff_login(other, name="other"))
    assert c.post(reverse("leave:request_withdraw", args=[req.pk])).status_code == 404
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING


def test_withdraw_after_decision_shows_message(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    req = _waiting(employee, sick, actor)
    LeaveRequest.objects.filter(pk=req.pk).update(status=RequestStatus.REJECTED)
    resp = _client(_staff_login(employee)).post(reverse("leave:request_withdraw", args=[req.pk]))
    assert resp.status_code == 200
    assert "Энэ хүсэлт шийдэгдсэн байна." in resp.content.decode()


def test_withdraw_still_works_when_approval_is_off(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    """Controller ruling: waiting requests made before approval was switched off stay withdrawable."""
    req = _waiting(employee, sick, actor)
    _settings(approval1_manager=False)
    assert _client(_staff_login(employee)).post(reverse("leave:request_withdraw", args=[req.pk])).status_code == 204
    req.refresh_from_db()
    assert req.status == RequestStatus.WITHDRAWN


def test_approve_with_stale_step_is_refused_and_request_stays_on_step_two(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    """The same person decides both steps; a second click from the screen opened at step 1 must not approve step 2."""
    _settings(approval2_manager=True)
    req = _waiting(employee, sick, actor)
    url = reverse("leave:request_approve", args=[req.pk])
    c = _client(manager)
    assert c.post(url, {"step": "1"}).status_code == 204
    resp = c.post(url, {"step": "1"})
    assert resp.status_code == 200
    assert "Энэ хүсэлт өөр шатанд шилжсэн байна." in resp.content.decode()
    req.refresh_from_db()
    assert req.status == RequestStatus.WAITING
    assert req.current_step == 2
    assert LeaveRequestAction.objects.filter(request=req, action=ActionKind.APPROVED).count() == 1


def test_forged_step_value_is_ignored_not_a_server_error(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    """A non-ASCII digit passes str.isdigit() but int() refuses it; the view must treat it as no step, never a 500."""
    req = _waiting(employee, sick, actor)
    resp = _client(manager).post(reverse("leave:request_approve", args=[req.pk]), {"step": "²"})
    assert resp.status_code == 204
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED


def test_refused_approve_shows_reason_field(actor: User, employee: Employee, sick: LeaveTypeRow, manager: User) -> None:
    """A sick request needs no reason at first; once an approve is refused the reason field is on the form."""
    req = _waiting(employee, sick, actor)
    c = _client(manager)
    assert 'name="override_reason"' not in c.get(_detail(req)).content.decode()
    resp = c.post(reverse("leave:request_approve", args=[req.pk]), {"step": "2"})
    assert "өөр шатанд шилжсэн" in resp.content.decode()
    assert 'name="override_reason"' in resp.content.decode()


def _hr_viewer(name: str) -> User:
    """An HR user with the list right («Бүгд») and the people right, and no approver role."""
    viewer = _user(name)
    viewer.user_permissions.add(
        Permission.objects.get(codename="view_leave", content_type__app_label="leave"),
        Permission.objects.get(codename="view_employees", content_type__app_label="macs"),
    )
    return viewer


def _approved(employee: Employee, sick: LeaveTypeRow, actor: User, manager: User) -> LeaveRequest:
    req = _waiting(employee, sick, actor)
    assert _client(manager).post(reverse("leave:request_approve", args=[req.pk]), {}).status_code == 204
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED and req.assign_id is not None
    return req


def test_cancelled_leave_shows_cancelled_in_request_list(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _approved(employee, sick, actor, manager)
    leave = LeaveAssign.objects.get(pk=req.assign_id)
    records.cancel(leave, writes.snapshot(leave), "Төлөвлөгөө өөрчлөгдсөн", actor, TODAY)
    body = _client(_hr_viewer("hr_cancel")).get(reverse("leave:requests") + "?tab=all").content.decode()
    assert ">Цуцалсан</td>" in body and ">Батлагдсан</td>" not in body  # the status filter also has the word
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED  # the request itself is not changed


def test_mistake_leave_shows_mistake_in_request_list(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _approved(employee, sick, actor, manager)
    leave = LeaveAssign.objects.get(pk=req.assign_id)
    records.cancel(leave, writes.snapshot(leave), "Буруу оруулсан", actor, date(2026, 11, 5))  # already started
    body = _client(_hr_viewer("hr_mistake")).get(reverse("leave:requests") + "?tab=all").content.decode()
    assert ">Буруу бүртгэсэн</td>" in body and ">Батлагдсан</td>" not in body


def test_hr_sees_pending_request_of_in_scope_person_under_all(
    actor: User, employee: Employee, sick: LeaveTypeRow, approval: None
) -> None:
    """R1-A11: «Бүгд» lists a pending request of an in-scope person for HR (not only the approver's own queue)."""
    _waiting(employee, sick, actor)
    body = _client(_hr_viewer("hr_all_pending")).get(reverse("leave:requests") + "?tab=all").content.decode()
    assert employee.full_name in body and ">Хүлээгдэж буй</td>" in body


def test_cancelled_leave_shows_cancelled_in_request_popup(
    actor: User, employee: Employee, sick: LeaveTypeRow, manager: User
) -> None:
    req = _approved(employee, sick, actor, manager)
    leave = LeaveAssign.objects.get(pk=req.assign_id)
    records.cancel(leave, writes.snapshot(leave), "Төлөвлөгөө өөрчлөгдсөн", actor, TODAY)
    body = _client(_hr_viewer("hr_popup_cancel")).get(_detail(req)).content.decode()
    assert "Энэ хүсэлт шийдэгдсэн: Цуцалсан" in body and "Энэ хүсэлт шийдэгдсэн: Батлагдсан" not in body


def test_detail_explains_hr_override(
    monkeypatch: pytest.MonkeyPatch, actor: User, employee: Employee, annual: LeaveTypeRow, manager: User
) -> None:
    """An HR override is named as one: «(эрхээр)» with the line that HR approved it instead of the manager."""
    req = LeaveRequest.objects.create(
        employee=employee,
        leave_type=annual,
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 3),
        working_days=2,
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )
    monkeypatch.setattr("leave.views_requests.can_act", lambda user, req, day: (True, True))
    body = _client(manager).get(_detail(req)).content.decode()
    assert "Удирдлагын оронд батлав" in body
