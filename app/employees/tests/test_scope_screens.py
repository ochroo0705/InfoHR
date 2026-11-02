"""Screens leak test (data scope, spec §7). A limited HR user never sees, counts or opens a person outside the scope.

Part A covers the employee screens: the list (full page, htmx batches, grid and table), the detail page and its
partials, every write that takes an employee pk, the palette, Today, and the register check. Part B (leave, orders,
reports and exports, activity log, scope modes) lives in test_scope_screens_b.py and imports this file's fixtures.
"""

import re
from datetime import date, timedelta
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from leave.models import LeaveTypeExt
from leave.services import records
from leave.services.records import Draft
from macs.models import Branch, FiredReason, LeaveTypeRow

from employees import attention, sections, views
from employees.access import visible_employees
from employees.forms import JobCorrectionForm
from employees.listing import employee_rows
from employees.models import (
    ActivityEntry,
    Department,
    Employee,
    EmployeeExt,
    Event,
    EventType,
    HrOrder,
    JobRecord,
    OrderState,
    Position,
    SalaryRecord,
)
from employees.services import events, history, macs_writes

from .conftest import hire_values, link_login, named, set_ext
from .helpers import record_signed

pytestmark = pytest.mark.django_db

IN_FAMILY, IN_GIVEN = "Цэрэнпил", "Оюунчимэг"  # branch north: in scope
OUT_FAMILY, OUT_GIVEN = "Лхагвасүрэн", "Мөнхтуяа"  # branch south: out of scope
IN_REGISTER, OUT_REGISTER = "УБ00000011", "УБ00000022"
PEND_OUT_FAMILY, PEND_OUT_GIVEN = "Тэнгис", "Болд"  # branch south: no order number yet
OUT_ORDER = "7001"  # the order number of the out-of-scope hire
OTHER_FAMILY, OTHER_GIVEN = "Дашдорж", "Саранчимэг"  # branch south: a third person outside the scope
OTHER_REGISTER = "УБ00000044"
PASSWORD = "x-long-pass-123"  # noqa: S105


def _hire(
    actor: User,
    job: dict[str, Any],
    branch: Branch,
    register_no: str,
    family: str,
    given: str,
    order: str = "",
) -> Employee:
    values = {**hire_values(register_no), "family_name": family, "given_name": given}
    start = date(timezone.localdate().year, 1, 1)  # this year, so the reports' whole-year period includes the hire
    extra: dict[str, Any] = {}
    if order:
        extra = {"order_number": order, "order_date": start, "order_summary": "Ажилд авах"}
    employee = history.hire(values, {}, start=start, job=dict(job), salary=None, by=actor, **extra)
    Employee.objects.filter(pk=employee.pk).update(branch_id=branch.pk)
    return employee


def _user_in(role: str, name: str, *, limit: list[int] | None = None) -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    if limit is not None:
        AccessScope.objects.create(user=user, limited=True, branch_ids=limit)
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _waiting_promotion(employee: Employee, actor: User, position: Position) -> Event:
    """A promotion that waits for its signed order (nothing written yet), effective next month."""
    effective = timezone.localdate() + timedelta(days=30)
    ev = events.record(
        employee,
        type="promotion",
        effective=effective,
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert ev.applied_at is None
    return ev


@pytest.fixture
def north(db: None) -> Branch:
    return Branch.objects.create(name="Хойд")


@pytest.fixture
def south(db: None) -> Branch:
    return Branch.objects.create(name="Өмнөд")


@pytest.fixture
def people(actor: User, job_values: dict[str, Any], north: Branch, south: Branch) -> tuple[Employee, Employee]:
    """(inside, outside): the first is in branch north, the second in branch south and has an order number."""
    inside = _hire(actor, job_values, north, IN_REGISTER, IN_FAMILY, IN_GIVEN)
    outside = _hire(actor, job_values, south, OUT_REGISTER, OUT_FAMILY, OUT_GIVEN, order=OUT_ORDER)
    return inside, outside


@pytest.fixture
def hr_north(north: Branch, people: tuple[Employee, Employee]) -> Client:
    """An HR user limited to branch north (no employee row of their own)."""
    return _client(_user_in(roles.HR, "hr_north", limit=[north.pk]))


@pytest.fixture
def root(db: None) -> User:
    return User.objects.create_superuser("root", password="Root-pass-1")  # noqa: S106


@pytest.fixture
def leave_type(db: None) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Чөлөө")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=False)
    return row


@pytest.fixture
def due_soon(actor: User, leave_type: LeaveTypeRow, people: tuple[Employee, Employee]) -> None:
    """Both people get a birthday, a contract end, a probation end and leave today: a leak would show on Today."""
    today = timezone.localdate()
    soon = today + timedelta(days=3)
    for employee in people:
        Employee.objects.filter(pk=employee.pk).update(birth_date=date(1990, soon.month, soon.day))
        JobRecord.objects.filter(employee=employee).update(contract_end=today + timedelta(days=5))
        set_ext(employee, probation_end=today + timedelta(days=5))
        draft = Draft(employee, leave_type, today, today)
        assert not records.check(draft, today).errors
        records.record(draft, actor, today)


def _snapshot(pk: int) -> list[Any]:
    """Everything a write on one person could change, plus the global counts of events and activity."""
    return [
        list(Employee.objects.filter(pk=pk).values()),
        list(EmployeeExt.objects.filter(employee_id=pk).values()),
        list(JobRecord.objects.filter(employee_id=pk).values()),
        list(SalaryRecord.objects.filter(employee_id=pk).values()),
        list(HrOrder.objects.filter(employee_id=pk).values()),
        Event.objects.count(),
        ActivityEntry.objects.count(),
    ]


# --- employee list: full page, filters, htmx batches (grid and table) ---


def test_list_hides_outside_person(hr_north: Client) -> None:
    for params in ({}, {"view": "table"}):
        body = hr_north.get(reverse("employees:list"), params).content.decode()
        assert IN_FAMILY in body
        assert OUT_FAMILY not in body


@pytest.mark.parametrize("query", [OUT_FAMILY, OUT_REGISTER])
def test_list_search_finds_no_outside_person(hr_north: Client, people: tuple[Employee, Employee], query: str) -> None:
    _, outside = people
    body = hr_north.get(reverse("employees:list"), {"q": query}).content.decode()
    # The search box echoes the query, so the test looks for the person's own link, not the name.
    assert f"/employees/{outside.pk}/" not in body


@pytest.mark.parametrize("view", ["grid", "table"])
def test_list_batches_hide_outside_person(
    hr_north: Client, actor: User, job_values: dict[str, Any], north: Branch, monkeypatch: pytest.MonkeyPatch, view: str
) -> None:
    _hire(actor, job_values, north, "УБ00000033", "Баярсайхан", "Соёлмаа")  # a second person in scope
    monkeypatch.setattr(views, "LIST_BATCH", 1)  # one person per batch: the outside person would be batch three
    bodies = [
        hr_north.get(
            reverse("employees:list"), {"view": view, "offset": str(offset)}, headers={"HX-Request": "true"}
        ).content.decode()
        for offset in range(3)
    ]
    joined = "".join(bodies)
    assert IN_FAMILY in joined and "Баярсайхан" in joined
    assert OUT_FAMILY not in joined
    assert OUT_REGISTER not in joined


# --- employee page and its partials ---


def test_detail_is_404_for_outside_person(hr_north: Client, people: tuple[Employee, Employee]) -> None:
    inside, outside = people
    assert hr_north.get(reverse("employees:detail", args=[outside.pk])).status_code == 404
    assert hr_north.get(reverse("employees:detail", args=[inside.pk])).status_code == 200


@pytest.mark.parametrize("section", list(sections.SECTIONS))
def test_section_partials_are_404_for_outside_person(
    hr_north: Client, people: tuple[Employee, Employee], section: str
) -> None:
    inside, outside = people
    for query in ({}, {"fields": "1"}):
        url = reverse("employees:personal_section", args=[outside.pk, section])
        assert hr_north.get(url, query).status_code == 404
    assert hr_north.get(reverse("employees:personal_section", args=[inside.pk, section])).status_code == 200


@pytest.mark.parametrize("kind", sorted(sections.INLINE_LISTS))
def test_personal_lists_are_404_for_outside_person(
    hr_north: Client, people: tuple[Employee, Employee], kind: str
) -> None:
    inside, outside = people
    assert hr_north.get(reverse("employees:personal_list", args=[outside.pk, kind])).status_code == 404
    assert hr_north.get(reverse("employees:personal_list", args=[inside.pk, kind])).status_code == 200


def test_activity_more_is_404_for_outside_person(hr_north: Client, people: tuple[Employee, Employee]) -> None:
    inside, outside = people
    assert hr_north.get(reverse("employees:activity_more", args=[outside.pk])).status_code == 404
    assert hr_north.get(reverse("employees:activity_more", args=[inside.pk])).status_code == 200


def test_every_employee_pk_write_is_404_and_changes_nothing(
    hr_north: Client, actor: User, people: tuple[Employee, Employee]
) -> None:
    _, outside = people
    pk = outside.pk
    waiting = _waiting_promotion(outside, actor, macs_writes.save_position("Ахлах нягтлан"))
    order = HrOrder.objects.get(employee=outside, is_hire=True)
    job = JobRecord.objects.get(employee=outside)
    kind = sorted(sections.INLINE_LISTS)[0]
    routes: list[tuple[str, str, dict[str, Any]]] = [
        ("POST", reverse("employees:save", args=[pk]), {"family_name": "Өөрчлөгдсөн"}),
        ("POST", reverse("employees:login_create", args=[pk]), {"username": "x"}),
        ("POST", reverse("employees:setup_toggle", args=[pk, "x"]), {}),
        ("POST", reverse("employees:note", args=[pk]), {"text": "x"}),
        ("POST", reverse("employees:correct_job", args=[pk, job.pk]), {}),
        ("POST", reverse("employees:correct_salary", args=[pk, 1]), {}),
        ("POST", reverse("employees:set_salary", args=[pk]), {}),
        ("GET", reverse("employees:event", args=[pk, EventType.TERMINATION.value]), {}),
        ("POST", reverse("employees:event", args=[pk, EventType.TERMINATION.value]), {}),
        ("POST", reverse("employees:event_cancel", args=[pk, waiting.pk]), {}),
        ("GET", reverse("employees:order_edit", args=[pk, order.pk]), {}),
        ("POST", reverse("employees:order_edit", args=[pk, order.pk]), {}),
        ("POST", reverse("employees:order_upload", args=[pk, order.pk]), {}),
        ("GET", reverse("employees:order_detail", args=[pk, order.pk]), {}),
        ("POST", reverse("employees:order_cancel", args=[pk, order.pk]), {}),
        ("GET", reverse("employees:order_history", args=[pk, order.pk]), {}),
        ("GET", reverse("employees:order_file", args=[pk, order.pk]), {}),
        ("GET", reverse("employees:order_document", args=[pk, order.pk]), {}),
        ("GET", reverse("employees:order_document_pdf", args=[pk, order.pk]), {}),
        ("POST", reverse("employees:personal_section", args=[pk, "identity"]), {}),
        ("POST", reverse("employees:personal_add", args=[pk, kind]), {}),
        ("POST", reverse("employees:personal_edit", args=[pk, kind, 1]), {}),
        ("POST", reverse("employees:personal_delete", args=[pk, kind, 1]), {}),
    ]
    before = _snapshot(pk)
    for method, url, data in routes:
        response = getattr(hr_north, method.lower())(url, data)
        assert response.status_code == 404, f"{method} {url} answered {response.status_code}"
    assert _snapshot(pk) == before


# --- event cancel: a real waiting change of the outside person; the same request for the inside one is the control ---


def test_cancel_of_outside_event_is_404_and_control_in_scope_works(
    hr_north: Client, actor: User, people: tuple[Employee, Employee]
) -> None:
    inside, outside = people
    position = macs_writes.save_position("Ахлах нягтлан")
    out_event = _waiting_promotion(outside, actor, position)
    in_event = _waiting_promotion(inside, actor, position)
    response = hr_north.post(reverse("employees:event_cancel", args=[outside.pk, out_event.pk]), {"reason": "Буруу"})
    assert response.status_code == 404
    out_event.refresh_from_db()
    assert out_event.cancelled_at is None and out_event.applied_at is None
    # control: the same request for the in-scope person's event is not refused by scope
    response = hr_north.post(reverse("employees:event_cancel", args=[inside.pk, in_event.pk]), {"reason": "Буруу"})
    assert response.status_code != 404
    in_event.refresh_from_db()
    assert in_event.cancelled_at is not None


# --- Today ---


def test_today_counts_and_lists_only_scoped_people(
    hr_north: Client, people: tuple[Employee, Employee], due_soon: None
) -> None:
    inside, outside = people
    response = hr_north.get(reverse("employees:today"))
    assert response.status_code == 200
    ctx = response.context
    assert ctx["headcount"] == 1
    assert [a.row.employee.pk for a in ctx["away"]] == [inside.pk]
    assert {u.row.employee.pk for u in ctx["upcoming"]} == {inside.pk}
    assert {a.employee.pk for a in ctx["attention"] if a.employee is not None} == {inside.pk}
    assert {line.row.employee.pk for line in ctx["timeline"].lines} == {inside.pk}
    assert OUT_FAMILY not in response.content.decode()


# --- orders waiting for a number: the Today tile and the attention item ---


def test_pending_orders_tile_and_attention_are_scoped(
    hr_north: Client, actor: User, job_values: dict[str, Any], south: Branch, people: tuple[Employee, Employee]
) -> None:
    inside, _ = people
    pend_out = _hire(actor, job_values, south, "УБ00000044", PEND_OUT_FAMILY, PEND_OUT_GIVEN)  # no order number
    assert HrOrder.objects.get(employee=inside).state == OrderState.PENDING
    assert HrOrder.objects.get(employee=pend_out).state == OrderState.PENDING

    everyone = _client(_user_in(roles.HR, "hr_all_pending")).get(reverse("employees:today"))
    assert everyone.context["pending_orders"] == 2
    assert 'data-tile="orders">2<' in everyone.content.decode()
    assert len([a for a in everyone.context["attention"] if a.kind == "order_number"]) == 2

    response = hr_north.get(reverse("employees:today"))
    assert response.status_code == 200
    assert response.context["pending_orders"] == 1
    body = response.content.decode()
    assert 'data-tile="orders">1<' in body
    assert PEND_OUT_FAMILY not in body
    assert f"/employees/{pend_out.pk}/" not in body
    numbered = [a for a in response.context["attention"] if a.kind == "order_number"]
    assert [a.employee.pk for a in numbered] == [inside.pk]


# --- command palette ---


@pytest.mark.parametrize("query", [OUT_FAMILY, OUT_GIVEN, OUT_ORDER, f"{OUT_FAMILY} {OUT_GIVEN}"])
def test_palette_finds_no_outside_person_or_order(
    hr_north: Client, people: tuple[Employee, Employee], query: str
) -> None:
    _, outside = people
    body = hr_north.get(reverse("employees:palette"), {"q": query}).content.decode()
    assert OUT_FAMILY not in body
    assert f"/employees/{outside.pk}/" not in body
    assert OUT_ORDER not in body


@pytest.mark.parametrize("query", ["Нягтлан", "Санхүү", IN_FAMILY])
def test_palette_finds_inside_person_by_position_department_and_name(hr_north: Client, query: str) -> None:
    body = hr_north.get(reverse("employees:palette"), {"q": query}).content.decode()
    assert IN_FAMILY in body
    assert OUT_FAMILY not in body


def test_palette_on_outside_page_offers_no_actions(hr_north: Client, people: tuple[Employee, Employee]) -> None:
    _, outside = people
    body = hr_north.get(reverse("employees:palette"), {"from": f"/employees/{outside.pk}/"}).content.decode()
    assert f"/employees/{outside.pk}/" not in body
    assert OUT_FAMILY not in body


# --- register check (hire form) ---


def test_check_register_does_not_reveal_outside_person(hr_north: Client, people: tuple[Employee, Employee]) -> None:
    _, outside = people
    body = hr_north.get(reverse("employees:check_register"), {"register_no": OUT_REGISTER}).content.decode()
    assert OUT_FAMILY not in body
    assert f"/employees/{outside.pk}/" not in body


# --- Анхаарах (attention) box ---


def test_attention_box_ignores_outside_items(
    hr_north: Client, root: User, people: tuple[Employee, Employee], due_soon: None
) -> None:
    _, outside = people
    today = timezone.localdate()
    everyone = attention.items(root, employee_rows(Employee.objects.all(), today), today)
    outside_keys = [a.key for a in everyone if a.employee is not None and a.employee.pk == outside.pk]
    assert outside_keys, "the outside person must have attention items, or the test proves nothing"
    response = hr_north.post(reverse("employees:attention"), {"key": outside_keys, "action": "dismiss"})
    assert response.status_code == 404
    all_keys = [a.key for a in everyone if a.employee is not None]
    response = hr_north.post(reverse("employees:attention"), {"key": all_keys, "action": "dismiss"})
    assert response.status_code == 200
    assert OUT_FAMILY not in response.content.decode()


def test_attention_more_hides_outside_items(
    hr_north: Client, root: User, people: tuple[Employee, Employee], due_soon: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside, outside = people
    today = timezone.localdate()
    everyone = attention.items(root, employee_rows(Employee.objects.all(), today), today)
    mine = next(a for a in everyone if a.employee is not None and a.employee.pk == outside.pk)
    monkeypatch.setattr(attention, "GROUP_LIMIT", 0)  # every item of the group is loaded by «+N»
    response = hr_north.get(reverse("employees:attention_more"), {"kind": mine.kind, "urgency": str(mine.urgency)})
    assert response.status_code == 200  # the group exists: the in-scope person has the same kind of item
    body = response.content.decode()
    assert f"/employees/{inside.pk}/" in body
    assert OUT_FAMILY not in body


# --- hire: a limited user who hires outside the scope is sent to the list, not to a page that 404s ---
# The hire form has no branch field (a branch is set on the employee page), so these tests limit the HR user by
# department, which the hire form does set.


def _hire_post(job: dict[str, Any], department: Department, register_no: str, family: str) -> dict[str, str]:
    return {
        "family_name": family,
        "given_name": "Ажилтан",
        "register_no": register_no,
        "birth_date": "1999-11-22",
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": "2026-01-05",
        "work_conditions": "1",
        "prior_service_years": "0",
        "prior_service_months": "0",
        "start": "2026-01-05",
        "position": str(job["position"].pk),
        "department": str(department.pk),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def _hr_in_department(department: Department) -> Client:
    user = _user_in(roles.HR, "hr_dept")
    AccessScope.objects.create(user=user, limited=True, department_ids=[department.pk])
    return _client(User.objects.get(pk=user.pk))


def test_limited_hire_outside_scope_redirects_to_list(job_values: dict[str, Any]) -> None:
    other = macs_writes.save_department("Худалдаа")
    hr = _hr_in_department(job_values["department"])
    response = hr.post(reverse("employees:add"), _hire_post(job_values, other, "УБ00000066", "Шинэгүй"))
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:list")
    assert Employee.objects.filter(family_name="Шинэгүй").exists()


def test_limited_hire_inside_scope_redirects_to_detail(job_values: dict[str, Any]) -> None:
    hr = _hr_in_department(job_values["department"])
    response = hr.post(
        reverse("employees:add"), _hire_post(job_values, job_values["department"], "УБ00000077", "Дотоод")
    )
    assert response.status_code == 302
    hired = Employee.objects.get(family_name="Дотоод")
    assert response["Location"] == reverse("employees:detail", args=[hired.pk])


def _shown_password(page: str) -> str:
    return page.split('rounded bg-surface px-2 py-1 font-mono text-base tracking-wider select-all">')[1].split("<")[0]


def test_out_of_scope_hire_with_login_shows_password_once(job_values: dict[str, Any]) -> None:
    other = macs_writes.save_department("Худалдаа")
    hr = _hr_in_department(job_values["department"])
    post = _hire_post(job_values, other, "УБ00000066", "Шинэгүй")
    post.update(create_login="on", username="gadur.hire")
    response = hr.post(reverse("employees:add"), post)
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:list")
    shown = hr.get(response["Location"])
    page = shown.content.decode()
    assert "gadur.hire" in page and page.count('id="one-time-login"') == 1
    password = _shown_password(page)
    assert page.count(password) == 1
    assert "no-store" in shown["Cache-Control"]
    assert views.ONE_TIME_LOGIN_KEY not in hr.session
    again = hr.get(reverse("employees:list")).content.decode()
    assert password not in again and 'id="one-time-login"' not in again
    created = User.objects.get(username="gadur.hire")
    assert created.must_change_password and created.check_password(password)


def test_visible_hire_with_login_still_shows_password_on_detail(job_values: dict[str, Any]) -> None:
    hr = _hr_in_department(job_values["department"])
    post = _hire_post(job_values, job_values["department"], "УБ00000099", "Дотоодын")
    post.update(create_login="on", username="dotood.hire")
    response = hr.post(reverse("employees:add"), post)
    assert response.status_code == 302
    hired = Employee.objects.get(family_name="Дотоодын")
    assert response["Location"] == reverse("employees:detail", args=[hired.pk])
    page = hr.get(response["Location"]).content.decode()
    assert page.count('id="one-time-login"') == 1
    assert page.count(_shown_password(page)) == 1


# --- controls: the same screens show both people to users who are not limited ---


def test_control_unlimited_hr_sees_everyone(people: tuple[Employee, Employee], due_soon: None) -> None:
    inside, outside = people
    hr = _client(_user_in(roles.HR, "hr_all"))
    body = hr.get(reverse("employees:list")).content.decode()
    assert IN_FAMILY in body and OUT_FAMILY in body
    assert hr.get(reverse("employees:detail", args=[outside.pk])).status_code == 200
    assert hr.get(reverse("employees:today")).context["headcount"] == 2
    assert OUT_FAMILY in hr.get(reverse("employees:palette"), {"q": OUT_FAMILY}).content.decode()
    assert OUT_ORDER in hr.get(reverse("employees:palette"), {"q": OUT_ORDER}).content.decode()
    check = hr.get(reverse("employees:check_register"), {"register_no": OUT_REGISTER}).content.decode()
    assert OUT_FAMILY in check


def test_control_admin_with_limited_row_sees_everyone(north: Branch, people: tuple[Employee, Employee]) -> None:
    inside, outside = people
    admin = _client(_user_in(roles.ADMIN, "admin_limited", limit=[north.pk]))
    body = admin.get(reverse("employees:list")).content.decode()
    assert IN_FAMILY in body and OUT_FAMILY in body
    assert admin.get(reverse("employees:detail", args=[outside.pk])).status_code == 200


# --- manager picker: the choice lists only people the user may see (plus the employee's current manager) ---


def _manager_select(body: str) -> str:
    match = re.search(r'<select[^>]*\bname="manager".*?</select>', body, re.S)
    assert match is not None, "no manager select on the page"
    return match.group(0)


def test_hire_form_manager_picker_lists_only_visible_people(
    hr_north: Client, people: tuple[Employee, Employee]
) -> None:
    _, outside = people
    assert outside.code and outside.code.strip()
    select = _manager_select(hr_north.get(reverse("employees:add")).content.decode())
    assert IN_FAMILY in select
    assert OUT_FAMILY not in select and outside.code not in select


def test_hire_form_manager_picker_control_unlimited_sees_everyone(people: tuple[Employee, Employee]) -> None:
    _, outside = people
    hr = _client(_user_in(roles.HR, "hr_all_picker"))
    select = _manager_select(hr.get(reverse("employees:add")).content.decode())
    assert IN_FAMILY in select and OUT_FAMILY in select


@pytest.fixture
def reporting(
    actor: User,
    job_values: dict[str, Any],
    north: Branch,
    south: Branch,
    people: tuple[Employee, Employee],
) -> Employee:
    """Inside branch north, reports to the OUT person (branch south). Other people: IN_FAMILY, OTHER_FAMILY."""
    _, outside = people
    _other = _hire(actor, job_values, south, OTHER_REGISTER, OTHER_FAMILY, OTHER_GIVEN)
    return _hire(actor, {**job_values, "manager": outside}, north, "УБ00000055", "Дэлгэрмаа", "Бат")


def test_event_form_manager_picker_lists_only_visible_people_plus_current(
    hr_north: Client, reporting: Employee, people: tuple[Employee, Employee]
) -> None:
    url = reverse("employees:event", args=[reporting.pk, EventType.TRANSFER.value])
    select = _manager_select(hr_north.get(url).content.decode())
    _, outside = people
    assert IN_FAMILY in select  # a colleague in scope
    assert OUT_FAMILY in select  # the current manager, though out of scope
    assert OTHER_FAMILY not in select and OTHER_REGISTER not in select  # a third person outside the scope
    control = _client(_user_in(roles.HR, "hr_all_event"))
    all_select = _manager_select(control.get(url).content.decode())
    assert IN_FAMILY in all_select and OUT_FAMILY in all_select and OTHER_FAMILY in all_select


def _transfer_post(
    reporting: Employee, job_values: dict[str, Any], position: Position, manager: Employee
) -> dict[str, str]:
    return {
        "effective": timezone.localdate().isoformat(),
        "position": str(position.pk),
        "department": str(job_values["department"].pk),
        "manager": str(manager.pk),
        "reason": "",
        "note": "",
    }


def test_event_post_with_out_of_scope_manager_is_refused(
    hr_north: Client,
    actor: User,
    job_values: dict[str, Any],
    reporting: Employee,
    people: tuple[Employee, Employee],
) -> None:
    _, outside = people
    other = Employee.objects.get(family_name=OTHER_FAMILY)
    position = macs_writes.save_position("Ахлах нягтлан")
    url = reverse("employees:event", args=[reporting.pk, EventType.TRANSFER.value])
    before = _snapshot(reporting.pk)
    response = hr_north.post(url, _transfer_post(reporting, job_values, position, other))
    assert response.status_code == 200
    assert "manager" in response.context["form"].errors
    assert _snapshot(reporting.pk) == before
    # The control: the current out-of-scope manager stays valid when only the position changes.
    kept = hr_north.post(url, _transfer_post(reporting, job_values, position, outside))
    assert kept.status_code == 204
    assert Event.objects.filter(employee=reporting, type=EventType.TRANSFER).count() == 1


def test_correction_form_manager_picker_scoped(
    north: Branch,
    reporting: Employee,
    people: tuple[Employee, Employee],
    job_values: dict[str, Any],
) -> None:
    inside, outside = people
    other = Employee.objects.get(family_name=OTHER_FAMILY)
    record = JobRecord.objects.get(employee=reporting)
    limited = _user_in(roles.HR, "hr_correct", limit=[north.pk])
    scoped = JobCorrectionForm(user=limited, instance=record)
    scoped_choices = scoped.fields["manager"].queryset  # type: ignore[attr-defined]
    assert set(scoped_choices.values_list("pk", flat=True)) == {inside.pk, outside.pk}
    everyone = JobCorrectionForm(instance=record)  # no user: every employee except the employee themself
    everyone_choices = everyone.fields["manager"].queryset  # type: ignore[attr-defined]
    assert set(everyone_choices.values_list("pk", flat=True)) == {inside.pk, outside.pk, other.pk}


def _correction_post(record: JobRecord, manager: Employee, **changes: Any) -> dict[str, Any]:
    """The whole correction form: every job field as the record is now, the manager, a reason, and any change."""
    initial = JobCorrectionForm(instance=record).initial
    data: dict[str, Any] = {f: "" if initial.get(f) is None else initial[f] for f in JobRecord.JOB_FIELDS}
    data.update(manager=manager.pk, reason="засвар", **changes)
    return data


def test_correction_view_refuses_out_of_scope_manager(
    hr_north: Client, reporting: Employee, people: tuple[Employee, Employee]
) -> None:
    _, outside = people
    other = Employee.objects.get(family_name=OTHER_FAMILY)
    record = JobRecord.objects.get(employee=reporting)
    url = reverse("employees:correct_job", args=[reporting.pk, record.pk])
    before = _snapshot(reporting.pk)
    refused = hr_north.post(url, _correction_post(record, other))
    assert refused.status_code == 200
    assert "manager" in refused.context["form"].errors
    assert JobRecord.objects.get(pk=record.pk).manager_id == outside.pk
    assert _snapshot(reporting.pk) == before
    # The control: the current out-of-scope manager stays valid when only the position changes.
    position = macs_writes.save_position("Ахлах нягтлан")
    kept = hr_north.post(url, _correction_post(record, outside, position=position.pk))
    assert kept.status_code == 204
    changed = JobRecord.objects.get(pk=record.pk)
    assert changed.position_id == position.pk and changed.manager_id == outside.pk


def test_hire_post_refuses_out_of_scope_manager(
    north: Branch, hr_north: Client, job_values: dict[str, Any], people: tuple[Employee, Employee]
) -> None:
    inside, outside = people
    url = reverse("employees:add")
    branch = {"branch": str(north.pk)}
    posted = _hire_post(job_values, job_values["department"], "УБ00000088", "Гадаад")
    refused = hr_north.post(url, {**posted, "manager": outside.pk, **branch})
    assert refused.status_code == 200
    assert "manager" in refused.context["job"].errors
    assert not Employee.objects.filter(family_name="Гадаад").exists()
    # The control: the same hire with an in-scope manager creates the employee.
    created = hr_north.post(
        url, {**_hire_post(job_values, job_values["department"], "УБ00000089", "Зөв"), "manager": inside.pk, **branch}
    )
    assert created.status_code == 302
    assert Employee.objects.filter(family_name="Зөв").exists()


# --- hire branch: the hire form sets the person's branch; a branch-limited hirer may pick only their branches ---


def _branch_select(body: str) -> str:
    match = re.search(r'<select[^>]*\bname="branch".*?</select>', body, re.S)
    assert match is not None, "no branch select on the page"
    return match.group(0)


def _branch_select_tag(body: str) -> str:
    match = re.search(r'<select[^>]*\bname="branch"[^>]*>', body)
    assert match is not None, "no branch select on the page"
    return match.group(0)


def test_hire_form_branch_select_for_branch_limited_user(
    north: Branch, south: Branch, people: tuple[Employee, Employee]
) -> None:
    inside, _ = people
    hirer = _user_in(roles.HR, "hr_branch_own", limit=[north.pk])
    link_login(inside, hirer)  # the hirer's own employee is in branch north
    body = _client(User.objects.get(pk=hirer.pk)).get(reverse("employees:add")).content.decode()
    select = _branch_select(body)
    assert f'value="{north.pk}"' in select and f'value="{south.pk}"' not in select
    assert "required" in _branch_select_tag(body)
    assert re.search(rf'<option value="{north.pk}"[^>]*\bselected', select)


def test_branch_limited_hirer_sees_the_person_they_hire(
    north: Branch, hr_north: Client, job_values: dict[str, Any]
) -> None:
    url = reverse("employees:add")
    posted = {**_hire_post(job_values, job_values["department"], "УБ00000101", "Салбарын"), "branch": str(north.pk)}
    response = hr_north.post(url, posted)
    assert response.status_code == 302
    hired = Employee.objects.get(family_name="Салбарын")
    assert response["Location"] == reverse("employees:detail", args=[hired.pk])
    assert hired.branch_id == north.pk
    assert visible_employees(User.objects.get(username="hr_north")).filter(pk=hired.pk).exists()


def test_hire_post_with_branch_outside_limit_is_refused(
    north: Branch, south: Branch, hr_north: Client, job_values: dict[str, Any]
) -> None:
    url = reverse("employees:add")
    refused = hr_north.post(
        url, {**_hire_post(job_values, job_values["department"], "УБ00000102", "Хязгаар"), "branch": str(south.pk)}
    )
    assert refused.status_code == 200
    assert "branch" in refused.context["job"].errors
    missing = hr_north.post(url, _hire_post(job_values, job_values["department"], "УБ00000104", "Хязгаар"))
    assert missing.status_code == 200 and "branch" in missing.context["job"].errors  # required for this user
    assert not Employee.objects.filter(family_name="Хязгаар").exists()


def test_hire_branch_for_unlimited_user_is_optional_with_all_branches(
    north: Branch, south: Branch, people: tuple[Employee, Employee], job_values: dict[str, Any]
) -> None:
    _, outside = people
    hirer = _user_in(roles.HR, "hr_branch_all")
    link_login(outside, hirer)  # the hirer's own employee is in branch south
    hr = _client(User.objects.get(pk=hirer.pk))
    body = hr.get(reverse("employees:add")).content.decode()
    select = _branch_select(body)
    assert f'value="{north.pk}"' in select and f'value="{south.pk}"' in select
    assert "required" not in _branch_select_tag(body)
    assert re.search(rf'<option value="{south.pk}"[^>]*\bselected', select)
    response = hr.post(
        reverse("employees:add"), _hire_post(job_values, job_values["department"], "УБ00000103", "Салбаргүй")
    )
    assert response.status_code == 302
    assert Employee.objects.get(family_name="Салбаргүй").branch_id is None


def test_branch_limited_hirer_outside_own_branch_defaults_to_first_listed(
    north: Branch, south: Branch, people: tuple[Employee, Employee]
) -> None:
    _, outside = people  # the hirer works in branch south, but may hire only into branch north
    hirer = _user_in(roles.HR, "hr_branch_fallback", limit=[north.pk])
    link_login(outside, hirer)
    body = _client(User.objects.get(pk=hirer.pk)).get(reverse("employees:add")).content.decode()
    select = _branch_select(body)
    assert f'value="{south.pk}"' not in select
    assert re.search(rf'<option value="{north.pk}"[^>]*\bselected', select)


def _branch_and_department_hr(branch: Branch, department: int, name: str) -> Client:
    """An HR user limited by BOTH a branch and a department: they see the people in either."""
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=roles.HR))
    AccessScope.objects.create(user=user, limited=True, branch_ids=[branch.pk], department_ids=[department])
    return _client(User.objects.get(pk=user.pk))


def _save(client: Client, employee: Employee, **post: str) -> Any:
    """The Ажил tab's save as htmx posts it: only the posted fields; the rest is completed from the stored values.
    Status 200 is the form with its errors, 204 is a saved person."""
    return client.post(
        reverse("employees:save", args=[employee.pk]), {"tab": "work", **post}, headers={"HX-Request": "true"}
    )


def _stored_branch(employee: Employee) -> int | None:
    return Employee.objects.get(pk=employee.pk).branch_id


def test_limited_save_with_branch_outside_the_limit_is_refused(
    north: Branch, south: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    inside = _hire(actor, job_values, north, IN_REGISTER, IN_FAMILY, IN_GIVEN)
    client = _branch_and_department_hr(north, job_values["department"].pk, "hr_save_refused")

    response = _save(client, inside, branch=str(south.pk))

    assert response.status_code == 200
    assert "branch" in response.context["form"].errors
    assert _stored_branch(inside) == north.pk


def test_limited_save_without_branch_keeps_a_branch_outside_the_limit(
    north: Branch, south: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    # Visible through the department only: the branch is outside the user's list but is the person's current one.
    outside = _hire(actor, job_values, south, OUT_REGISTER, OUT_FAMILY, OUT_GIVEN)
    client = _branch_and_department_hr(north, job_values["department"].pk, "hr_save_dept")
    assert visible_employees(User.objects.get(username="hr_save_dept")).filter(pk=outside.pk).exists()

    response = _save(client, outside)  # no branch posted

    assert response.status_code == 204
    assert _stored_branch(outside) == south.pk


def test_limited_section_save_without_branch_keeps_a_branch_outside_the_limit(
    north: Branch, south: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    outside = _hire(actor, job_values, south, OUT_REGISTER, OUT_FAMILY, OUT_GIVEN)
    client = _branch_and_department_hr(north, job_values["department"].pk, "hr_section_dept")

    response = client.post(reverse("employees:personal_section", args=[outside.pk, "identity"]), {})

    assert response.status_code == 200
    assert response.context["editing"] is False  # saved, not sent back with errors
    assert _stored_branch(outside) == south.pk


def test_unlimited_hr_user_may_move_the_employee_to_another_branch(
    north: Branch, south: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    inside = _hire(actor, job_values, north, IN_REGISTER, IN_FAMILY, IN_GIVEN)
    hr = _client(_user_in(roles.HR, "hr_all_move"))

    response = _save(hr, inside, branch=str(south.pk))

    assert response.status_code == 204
    assert _stored_branch(inside) == south.pk


def test_limited_save_with_blank_branch_is_refused_when_the_person_has_one(
    north: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    inside = _hire(actor, job_values, north, IN_REGISTER, IN_FAMILY, IN_GIVEN)
    client = _branch_and_department_hr(north, job_values["department"].pk, "hr_blank_refused")

    response = _save(client, inside, branch="")

    assert response.status_code == 200
    assert "branch" in response.context["form"].errors
    assert _stored_branch(inside) == north.pk


def test_limited_save_with_blank_branch_is_accepted_when_the_person_has_none(
    north: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    legacy = _hire(actor, job_values, north, IN_REGISTER, IN_FAMILY, IN_GIVEN)
    Employee.objects.filter(pk=legacy.pk).update(branch_id=None)
    client = _branch_and_department_hr(north, job_values["department"].pk, "hr_blank_legacy")

    response = _save(client, legacy, branch="")

    assert response.status_code == 204
    assert _stored_branch(legacy) is None


# --- leavers: the picker offers only people who work here now, plus the employee's current manager ---


def _terminate(employee: Employee, actor: User) -> None:
    record_signed(
        employee,
        type="termination",
        effective=timezone.localdate(),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )


@pytest.fixture
def leavers(actor: User, job_values: dict[str, Any], north: Branch) -> tuple[Employee, Employee]:
    """(terminated, dismissed): both in branch north, neither works here now. The second has no HR job history
    and a MACS emptype of 3 (dismissed), so it is judged by the MACS row, as the employee list judges it."""
    gone = _hire(actor, job_values, north, "УБ00000031", "Явсан", "Бат")
    _terminate(gone, actor)
    dismissed = _hire(actor, job_values, north, "УБ00000032", "Чөлөөлөгдсөн", "Дорж")
    JobRecord.objects.filter(employee=dismissed).delete()
    Employee.objects.filter(pk=dismissed.pk).update(emptype=3)
    return gone, dismissed


@pytest.fixture
def ex_boss_report(actor: User, job_values: dict[str, Any], north: Branch) -> tuple[Employee, Employee]:
    """(ex_manager, report): the report's current manager has left."""
    ex = _hire(actor, job_values, north, "УБ00000041", "Хуучин", "Дарга")
    report = _hire(actor, {**job_values, "manager": ex}, north, "УБ00000042", "Тайлагдсан", "Ажилтан")
    _terminate(ex, actor)
    return ex, report


def _assert_no_leaver(select: str, leaver_people: tuple[Employee, Employee]) -> None:
    for leaver in leaver_people:
        code, family = leaver.code or "", leaver.family_name or ""
        assert code and family and family not in select and code not in select


def test_hire_form_manager_picker_leaves_out_leavers(
    hr_north: Client, actor: User, people: tuple[Employee, Employee], leavers: tuple[Employee, Employee]
) -> None:
    inside, _ = people
    select = _manager_select(hr_north.get(reverse("employees:add")).content.decode())
    assert IN_FAMILY in select
    _assert_no_leaver(select, leavers)
    control = _client(_user_in(roles.HR, "hr_all_leavers"))
    all_select = _manager_select(control.get(reverse("employees:add")).content.decode())
    assert IN_FAMILY in all_select
    _assert_no_leaver(all_select, leavers)


def test_event_form_manager_picker_keeps_current_leaver_only(
    hr_north: Client, ex_boss_report: tuple[Employee, Employee], leavers: tuple[Employee, Employee]
) -> None:
    ex, report = ex_boss_report
    url = reverse("employees:event", args=[report.pk, EventType.TRANSFER.value])
    select = _manager_select(hr_north.get(url).content.decode())
    code, family = ex.code or "", ex.family_name or ""
    assert code and family in select and code in select  # the current manager has left, but stays valid
    assert IN_FAMILY in select
    _assert_no_leaver(select, leavers)


def test_correction_form_manager_picker_keeps_current_leaver_only(
    north: Branch,
    people: tuple[Employee, Employee],
    ex_boss_report: tuple[Employee, Employee],
    leavers: tuple[Employee, Employee],
) -> None:
    inside, _ = people
    ex, report = ex_boss_report
    record = JobRecord.objects.get(employee=report)
    limited = _user_in(roles.HR, "hr_correct_leaver", limit=[north.pk])
    choices = JobCorrectionForm(user=limited, instance=record).fields["manager"].queryset  # type: ignore[attr-defined]
    pks = set(choices.values_list("pk", flat=True))
    assert {inside.pk, ex.pk} <= pks
    assert not {gone.pk for gone in leavers} & pks


def test_event_post_refuses_other_leaver_and_keeps_current_leaver(
    hr_north: Client,
    job_values: dict[str, Any],
    ex_boss_report: tuple[Employee, Employee],
    leavers: tuple[Employee, Employee],
) -> None:
    ex, report = ex_boss_report
    gone, _ = leavers
    position = macs_writes.save_position("Ахлах нягтлан")
    url = reverse("employees:event", args=[report.pk, EventType.TRANSFER.value])
    before = _snapshot(report.pk)
    refused = hr_north.post(url, _transfer_post(report, job_values, position, gone))
    assert refused.status_code == 200
    assert "manager" in refused.context["form"].errors
    assert _snapshot(report.pk) == before
    kept = hr_north.post(url, _transfer_post(report, job_values, position, ex))
    assert kept.status_code == 204
    assert Event.objects.filter(employee=report, type=EventType.TRANSFER).count() == 1
