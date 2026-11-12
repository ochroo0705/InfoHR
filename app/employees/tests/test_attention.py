import re
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from leave.models import GrantKind, LeaveRequest, LeaveSettings, LeaveTypeExt
from leave.services import entitlement as leave_entitlement
from leave.services import ledger as leave_ledger
from leave.services import writes as leave_writes
from leave.services.fmt import fmt_days
from macs.models import Branch, ContactRow, ContactType, Entitlement, FiredReason, LeaveTypeRow

from employees import attention
from employees.listing import Row, employee_rows
from employees.models import Employee, EmployeeExt, SetupItem
from employees.services import events, history

from .conftest import hire_values, link_login, named, set_account, set_ext
from .helpers import record_signed
from .test_views import login_as

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def user_in(role: str, name: str = "u1") -> User:
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return u


def set_contact(employee: Employee, present: bool) -> None:
    """Emergency contact = a production row (contacting): one row when present, none otherwise."""
    ContactRow.objects.filter(employee=employee).delete()
    if present:
        ContactRow.objects.create(
            employee=employee, contact_type=named(ContactType, "Утас"), name="А", relative="Ах", value="99"
        )


def texts(user: User, today: date = TODAY) -> list[str]:
    from employees.models import Employee as E

    return [a.text for a in attention.items(user, employee_rows(E.objects.all(), today), today)]


@pytest.fixture(autouse=True)
def death_meaning_set(db: None) -> None:
    """The QC 3c "died" meaning is configured, so its own attention item stays out of these lists."""
    from lists.models import DEATH, MeaningfulEntry

    MeaningfulEntry.objects.create(key=DEATH, value=named(FiredReason, "Нас барсан").pk)


@pytest.fixture
def emp(hired: Employee) -> Employee:
    set_ext(hired, setup_required=False)
    set_contact(hired, present=True)
    hired.save()
    set_account(hired, "123")
    hired.hr_orders.update(state="registered")  # the hire order's pending-number reminder is tested on its own
    return hired


@pytest.mark.parametrize(("delta", "shown"), [(-1, False), (0, True), (14, True), (15, False)])
def test_probation_boundaries(emp: Employee, delta: int, shown: bool) -> None:
    set_ext(emp, probation_end=TODAY + timedelta(days=delta))
    emp.save()
    assert any("Туршилтын" in t for t in texts(user_in("HR"))) is shown


@pytest.mark.parametrize(("delta", "text"), [(0, "дуусна"), (30, "дуусна"), (31, None), (-1, "дууссан")])
def test_contract_boundaries(emp: Employee, delta: int, text: str | None) -> None:
    job = emp.job_records.get()
    job.contract_end = TODAY + timedelta(days=delta)
    job.save()
    found = [t for t in texts(user_in("HR")) if t.startswith("Гэрээ")]
    assert (found == []) if text is None else (len(found) == 1 and found[0].endswith(text))


def test_setup_rule_uses_viewer_visible_items(emp: Employee) -> None:
    set_ext(emp, setup_required=True)
    emp.save()
    hr = user_in("HR")
    assert "Бүрдүүлэлт дутуу" in texts(hr)
    set_ext(emp, setup_required=False)
    emp.save()
    assert "Бүрдүүлэлт дутуу" not in texts(hr)


def test_accountant_sees_neither_setup_nor_personal(emp: Employee) -> None:
    set_ext(emp, setup_required=True)
    set_account(emp, "")
    got = texts(user_in("Accountant"))
    assert got == ["Банкны мэдээлэл бүртгээгүй"]


def test_hr_never_sees_bank_rule(emp: Employee) -> None:
    set_account(emp, "")
    set_contact(emp, present=False)
    emp.save()
    got = [t for t in texts(user_in("HR")) if "Ээлжийн" not in t]  # no leave type is configured in this test
    assert got == ["Яаралтай үед холбогдох хүн бүртгээгүй"]


def test_employee_role_empty(emp: Employee) -> None:
    set_contact(emp, present=False)
    emp.save()
    assert texts(user_in("Employee")) == []


def test_left_excluded_and_sorted(emp: Employee, actor: User, job_values: dict[str, Any]) -> None:
    set_account(emp, "")
    other = history.hire(hire_values("УБ00000002"), {}, start=date(2025, 1, 1), job=job_values, salary=None, by=actor)
    other.family_name = "Аавын"
    other.save()
    admin = User.objects.create_superuser("root", password="x-long-pass-123")  # noqa: S106
    rows = employee_rows(Employee.objects.all(), TODAY)
    names = [a.employee.full_name for a in attention.items(admin, rows, TODAY) if a.kind == "bank" and a.employee]
    assert names == ["Аавын Сараа", "Батын Сараа"]
    history.change_job(
        other, effective=date(2025, 6, 1), changes={"status": "left"}, change_type="correction", note="", by=actor
    )
    rows = employee_rows(Employee.objects.all(), TODAY)
    assert {a.employee.pk for a in attention.items(admin, rows, TODAY) if a.employee} == {emp.pk}


def test_box_on_today_page(client: Client, emp: Employee) -> None:
    set_account(emp, "")
    login_as(client, "Accountant")
    url = reverse("employees:today")
    assert "Банкны мэдээлэл дутуу · 1" in client.get(url).content.decode()


def _fully_ticked_without_bank(emp: Employee) -> None:
    set_ext(emp, setup_required=True)
    link_login(emp, User.objects.create_user("linked", password="x-long-pass-123"))  # noqa: S106
    emp.save()
    for key in ("contract", "id_copy", "equipment"):
        SetupItem.objects.create(employee=emp, key=key)
    set_account(emp, "")


def test_setup_complete_for_hr_but_not_admin_when_only_bank_missing(emp: Employee) -> None:
    _fully_ticked_without_bank(emp)
    assert "Бүрдүүлэлт дутуу" not in texts(user_in("HR"))
    admin = User.objects.create_superuser("root", password="x-long-pass-123")  # noqa: S106
    assert "Бүрдүүлэлт дутуу" in texts(admin)


def test_missing_salary_insurance_row_flags_bank_for_accountant(emp: Employee) -> None:
    set_account(emp, "")
    assert "Банкны мэдээлэл бүртгээгүй" in texts(user_in("Accountant"))


def test_scheduled_termination_and_near_event_shown(emp: Employee, actor: User) -> None:
    events.record(
        emp, type="contract", effective=TODAY + timedelta(days=7), changes={"contract_no": "CN-NEW"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    record_signed(
        emp, type="termination", effective=TODAY + timedelta(days=20), changes={}, salary=None,
        reason="", fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    got = texts(user_in("HR"))
    assert f"Гарах: {_fmt(TODAY + timedelta(days=20))}" in got
    assert f"Төлөвлөсөн: Гэрээ сунгах / өөрчлөх {_fmt(TODAY + timedelta(days=7))}" in got


def test_day_14_shown_and_today_not_shown(emp: Employee, actor: User) -> None:
    events.record(
        emp, type="contract", effective=TODAY, changes={"contract_no": "CN-0"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    events.record(
        emp, type="contract", effective=TODAY + timedelta(days=14), changes={"contract_no": "CN-14"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    assert f"Төлөвлөсөн: Гэрээ сунгах / өөрчлөх {_fmt(TODAY + timedelta(days=14))}" in texts(user_in("HR"))
    assert not any(_fmt(TODAY) in t and t.startswith("Төлөвлөсөн") for t in texts(user_in("HR", "u2")))


def test_far_future_non_termination_not_shown(emp: Employee, actor: User) -> None:
    events.record(
        emp, type="contract", effective=TODAY + timedelta(days=15), changes={"contract_no": "CN-FAR"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    assert not any(t.startswith("Төлөвлөсөн") for t in texts(user_in("HR")))


def test_cancelled_event_ignored(emp: Employee, actor: User) -> None:
    real_today = timezone.localdate()  # events.cancel only accepts scheduled events, judged on the real clock
    ev = events.record(
        emp, type="termination", effective=real_today + timedelta(days=5), changes={}, salary=None,
        reason="", fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    events.cancel(ev, reason="алдсан", by=actor)
    assert not any(t.startswith("Гарах") for t in texts(user_in("HR"), real_today))


def test_salary_change_hidden_from_hr(emp: Employee, actor: User) -> None:
    events.record(
        emp, type="salary_change", effective=TODAY + timedelta(days=5), changes={},
        salary=Decimal("3000000"), reason="", note="", by=actor,
    )  # fmt: skip
    text = f"Төлөвлөсөн: Цалин өөрчлөх {_fmt(TODAY + timedelta(days=5))}"
    assert text not in texts(user_in("HR"))
    assert text in texts(user_in("Accountant", "acc"))


@pytest.mark.parametrize(
    ("delta", "text"),
    [
        (15, None),
        (14, "Чөлөөнөөс буцах: {d}"),
        (0, "Чөлөөнөөс буцах: {d}"),
        (-1, "Чөлөөнөөс буцах огноо өнгөрсөн: {d}"),
    ],
)
def test_expected_return_from_leave(emp: Employee, delta: int, text: str | None) -> None:
    actor = user_in("HR", "hr1")
    back = TODAY + timedelta(days=delta)
    events.record(
        emp,
        type="leave_start",
        effective=TODAY - timedelta(days=30),
        changes={},
        salary=None,
        reason="unpaid",
        note="",
        by=actor,
        expected_return=back,
    )
    shown = [t for t in texts(actor) if "Чөлөөнөөс" in t]
    assert shown == ([text.format(d=_fmt(back))] if text else [])


def test_most_urgent_first_and_rest_folded(
    client: Client, emp: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    emp.job_records.update(contract_end=today - timedelta(days=10))
    for i in range(12):  # new hires without an emergency contact: one "missing" item each at least
        history.hire(hire_values(f"УБ991122{i:02d}"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    hr = user_in("HR", "hr1")
    found = attention.items(hr, employee_rows(Employee.objects.all(), today), today)
    assert found[0].employee == emp and "дууссан" in found[0].text
    assert [a.urgency for a in found] == sorted(a.urgency for a in found)
    login_as(client, "HR")
    html = client.get(reverse("employees:today")).content.decode()
    groups = attention.group(found)
    assert groups[0].label == "Гэрээ дууссан" and groups[0].dated
    assert [g.urgency for g in groups] == sorted(g.urgency for g in groups)
    assert sum(len(g.items) for g in groups) == len(found)
    emergency = next(g for g in groups if g.kind == "emergency")
    assert not emergency.dated and len(emergency.items) >= 12
    assert "Гэрээ дууссан" in html and f"Яаралтай үед холбогдох хүн дутуу · {len(emergency.items)}" in html
    assert f"Бүгдийг харах ({len(emergency.items) - attention.GROUP_LIMIT}) →" in html  # past three wait behind it
    # Chips are for the overdue and due-soon groups; missing-data groups are one-line rows in the closed gap section.
    queued = [g for g in groups if not g.dated and g.urgency != attention.MISSING]
    assert html.count("data-chip") == attention.GROUP_LIMIT * sum(
        1 for g in queued if len(g.items) >= attention.GROUP_LIMIT
    ) + sum(len(g.items) for g in queued if len(g.items) < attention.GROUP_LIMIT)
    assert 'data-attention-gap data-kind="emergency"' in html


def _many_without_contact(actor: User, job_values: dict[str, Any], count: int) -> None:
    for i in range(count):
        history.hire(hire_values(f"УБ771122{i:02d}"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)


def test_a_group_shows_three_items_and_loads_the_rest_on_request(
    client: Client, emp: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    _many_without_contact(actor, job_values, 14)
    login_as(client, "HR")
    today = timezone.localdate()
    hr = User.objects.get(username="viewer")
    groups = attention.group(attention.items(hr, employee_rows(Employee.objects.all(), today), today))
    emergency = next(g for g in groups if g.kind == "emergency")
    assert len(emergency.items) > attention.GROUP_LIMIT
    page = client.get(reverse("employees:today")).content.decode()
    assert f"Бүгдийг харах ({len(emergency.items) - attention.GROUP_LIMIT}) →" in page
    more = client.get(reverse("employees:attention_more"), {"kind": "emergency", "urgency": str(emergency.urgency)})
    assert more.status_code == 200 and more["Cache-Control"] == "no-store"
    body = more.content.decode()
    assert body.count("group/chip") == len(emergency.items) - attention.GROUP_LIMIT
    rest = emergency.items[attention.GROUP_LIMIT :]
    assert all(f'href="/employees/{a.employee.pk}/' in body for a in rest if a.employee)
    assert not any(
        f'href="/employees/{a.employee.pk}/' in body for a in emergency.items[: attention.GROUP_LIMIT] if a.employee
    )


def test_a_dated_group_loads_the_rest_as_lines(
    client: Client, emp: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    for i in range(12):
        person = history.hire(
            hire_values(f"УБ661122{i:02d}"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor
        )
        person.job_records.update(contract_end=today + timedelta(days=5 + i))
    login_as(client, "HR")
    hr = User.objects.get(username="viewer")
    groups = attention.group(attention.items(hr, employee_rows(Employee.objects.all(), today), today))
    ending = next(g for g in groups if g.kind == "contract" and g.dated)
    assert len(ending.items) > attention.GROUP_LIMIT
    body = client.get(
        reverse("employees:attention_more"), {"kind": "contract", "urgency": str(ending.urgency)}
    ).content.decode()
    assert body.count("<li") == len(ending.items) - attention.GROUP_LIMIT


def _attention_group_tags(html: str) -> list[str]:
    return re.findall(r"<details data-attention-group[^>]*>", html)


def _contract_people(actor: User, job_values: dict[str, Any], ends: list[date]) -> None:
    for i, end in enumerate(ends):
        person = history.hire(
            hire_values(f"УБ551122{i:02d}"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor
        )
        person.job_records.update(contract_end=end)


def test_groups_are_closed_except_overdue(
    client: Client, emp: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    emp.job_records.update(contract_end=today - timedelta(days=10))  # overdue
    _contract_people(actor, job_values, [today + timedelta(days=5)])  # due soon
    login_as(client, "HR")
    tags = _attention_group_tags(client.get(reverse("employees:today")).content.decode())
    assert len(tags) >= 2
    overdue = [t for t in tags if " open" in t]
    assert len(overdue) == 1 and 'data-urgency="0"' in overdue[0]
    assert all('data-urgency="0"' not in t for t in tags if t not in overdue)


def test_summary_shows_nearest_date_for_dated_groups_only(
    client: Client, emp: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    _contract_people(actor, job_values, [today + timedelta(days=9), today + timedelta(days=4)])
    login_as(client, "HR")
    html = client.get(reverse("employees:today")).content.decode()
    pattern = r'<details data-attention-group data-kind="(\w+)"[^>]*>\s*<summary[^>]*>(.*?)</summary>'
    by_kind = {m.group(1): m.group(2) for m in re.finditer(pattern, html, re.S)}
    nearest = _fmt(today + timedelta(days=4))
    assert nearest in by_kind["contract"] and _fmt(today + timedelta(days=9)) not in by_kind["contract"]
    assert "text-slate-500" in by_kind["contract"]
    gap_row = re.search(r'<li data-attention-gap data-kind="emergency"[^>]*>(.*?)</li>', html, re.S)
    assert gap_row is not None and not re.search(r"\d{4}-\d{2}-\d{2}", gap_row.group(1))


def test_count_in_the_summary_ignores_items_hidden_with_Мэдлээ(  # noqa: N802
    client: Client, emp: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    _many_without_contact(actor, job_values, 3)
    hr = login_as(client, "HR")
    today = timezone.localdate()
    found = attention.items(hr, employee_rows(Employee.objects.all(), today), today)
    keys = [a.key for a in found if a.kind == "emergency"]
    assert len(keys) == 3
    client.post(reverse("employees:attention"), {"key": keys[0], "action": "dismiss"})
    html = client.get(reverse("employees:today")).content.decode()
    assert "Яаралтай үед холбогдох хүн дутуу · 2" in html


def test_scheduled_changes_still_show_on_the_page(client: Client, emp: Employee, actor: User) -> None:
    real_today = timezone.localdate()
    record_signed(
        emp, type="termination", effective=real_today + timedelta(days=6), changes={}, salary=None,
        reason="", fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    login_as(client, "HR")
    html = client.get(reverse("employees:today")).content.decode()
    assert "Ажлаас гарах · 1" in html and "data-attention-group" in html


def test_attention_more_needs_login_and_a_real_group(client: Client, emp: Employee) -> None:
    assert client.get(reverse("employees:attention_more"), {"kind": "emergency", "urgency": "2"}).status_code == 302
    login_as(client, "HR")
    assert client.get(reverse("employees:attention_more"), {"kind": "nope", "urgency": "9"}).status_code == 404
    assert client.post(reverse("employees:attention_more")).status_code == 405


def test_dismiss_all_in_group(client: Client, emp: Employee, actor: User, job_values: dict[str, Any]) -> None:
    today = timezone.localdate()
    for i in range(2):
        history.hire(hire_values(f"УБ881122{i:02d}"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    hr = login_as(client, "HR")
    found = attention.items(hr, employee_rows(Employee.objects.all(), today), today)
    keys = [a.key for a in found if a.kind == "emergency"]
    assert len(keys) >= 2
    client.post(reverse("employees:attention"), {"key": keys, "action": "dismiss_all"})
    shown, hidden = attention.split(hr, attention.items(hr, employee_rows(Employee.objects.all(), today), today))
    assert {a.key for a in hidden} == set(keys) and not any(a.kind == "emergency" for a in shown)


def _scheduled_leave(emp: Employee, actor: User, start: date) -> None:
    events.record(emp, type="leave_start", effective=start, changes={}, salary=None, reason="unpaid", note="", by=actor)


def test_dismiss_hides_for_that_user_only_and_can_be_restored(
    client: Client, emp: Employee, actor: User, annual_type: LeaveTypeRow
) -> None:  # annual_type: the "no leave type chosen" notice would otherwise stay in the list
    today = timezone.localdate()
    _scheduled_leave(emp, actor, today + timedelta(days=3))
    hr = login_as(client, "HR")
    item = next(
        a for a in attention.items(hr, employee_rows(Employee.objects.all(), today), today) if a.kind == "scheduled"
    )
    html = client.post(reverse("employees:attention"), {"key": item.key, "action": "dismiss"}).content.decode()
    assert "Нуусан (1)" in html and "Шинэ зүйл алга." in html
    shown, hidden = attention.split(hr, attention.items(hr, employee_rows(Employee.objects.all(), today), today))
    assert hidden == [item] and item not in shown
    other = user_in("HR", "hr2")
    shown2, hidden2 = attention.split(
        other, attention.items(other, employee_rows(Employee.objects.all(), today), today)
    )
    assert item in shown2 and not hidden2
    client.post(reverse("employees:attention"), {"key": item.key, "action": "restore"})
    assert attention.split(hr, [item]) == ([item], [])


def test_changed_item_shows_again(emp: Employee, actor: User) -> None:
    hr = user_in("HR", "hr1")
    a = attention.Attention(emp, "Чөлөөнөөс буцах: 2026-10-20", "leave", attention.DUE, date(2026, 10, 20))
    attention.dismiss(hr, a)
    b = attention.Attention(emp, "Чөлөөнөөс буцах огноо өнгөрсөн: 2026-10-20", "leave", attention.OVERDUE, a.due)
    assert attention.split(hr, [a, b]) == ([b], [a])


def test_cannot_dismiss_unknown_key(client: Client, emp: Employee) -> None:
    login_as(client, "HR")
    response = client.post(reverse("employees:attention"), {"key": "leave:999:x", "action": "dismiss"})
    assert response.status_code == 404


@pytest.fixture
def annual_type(db: None) -> LeaveTypeRow:
    return leave_writes.save_leave_type(
        "Ээлжийн амралт", {"is_paid": True, "uses_annual_balance": True, "is_active": True, "order": 1}
    )


def _current_year(emp: Employee) -> tuple[date, date]:
    start = leave_entitlement.year_start_for(emp, TODAY)
    return start, leave_entitlement.next_year_start(emp, start) - timedelta(days=1)


def test_negative_leave_balance_item(emp: Employee, annual_type: LeaveTypeRow) -> None:
    start, end = _current_year(emp)
    leave_writes.add_grant(emp, annual_type, start, end, 15, "", GrantKind.AUTO, None)
    leave_writes.add_grant(emp, annual_type, start, end, -20, "test", GrantKind.ADJUSTMENT, None)
    left = next(p for p in leave_ledger.periods(emp, TODAY)[0] if p.start == start).left
    assert left < 0
    expected = f"Ээлжийн амралтын үлдэгдэл хасах: {fmt_days(left)} хоног"
    assert expected in texts(user_in("HR"))
    assert expected in texts(user_in("Accountant", "acc"))
    assert not any("Ээлжийн амралтын" in t for t in texts(user_in("Employee", "e1")))


def test_attention_doubled_grant(emp: Employee, annual_type: LeaveTypeRow) -> None:
    start, end = _current_year(emp)
    leave_writes.add_grant(emp, annual_type, start, end, 15, "", GrantKind.AUTO, None)
    assert "Ээлжийн амралт: давхардсан эрх" not in texts(user_in("HR", "h1"))
    leave_writes.add_grant(emp, annual_type, start, end, 5, "гараар", GrantKind.MANUAL, None)
    assert "Ээлжийн амралт: давхардсан эрх" in texts(user_in("HR", "h2"))


def test_attention_silent_when_not_configured(emp: Employee, annual_type: LeaveTypeRow) -> None:
    start, end = _current_year(emp)
    leave_writes.add_grant(emp, annual_type, start, end, 15, "", GrantKind.AUTO, None)
    leave_writes.add_grant(emp, annual_type, start, end, -20, "test", GrantKind.ADJUSTMENT, None)
    LeaveTypeExt.objects.update(uses_annual_balance=False)
    # No balance or doubled-grant item; HR does not get the settings notice (leave settings are Admin only).
    assert [t for t in texts(user_in("HR")) if "Ээлжийн амралт" in t] == []


def test_future_rehire_does_not_break_leave_item(emp: Employee, actor: User) -> None:
    record_signed(
        emp, type="termination", effective=date(2026, 3, 1), changes={}, salary=None,
        reason="", fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    record_signed(
        emp, type="rehire", effective=TODAY + timedelta(days=30), changes={}, salary=None,
        reason="", note="", by=actor,
    )  # fmt: skip
    rows = employee_rows(Employee.objects.all(), TODAY)
    found = attention.items(user_in("HR"), rows, TODAY)
    assert not any(a.kind == "leave_balance" for a in found)


def test_attention_never_writes_leave_grants(emp: Employee) -> None:
    before = Entitlement.objects.count()
    attention.items(user_in("HR"), employee_rows(Employee.objects.all(), TODAY), TODAY)
    assert Entitlement.objects.count() == before


def test_attention_survives_missing_leave_rule(emp: Employee, annual_type: LeaveTypeRow) -> None:
    from leave.models import AnnualLeaveRule

    start, end = _current_year(emp)
    leave_writes.add_grant(emp, annual_type, start, end, -20, "test", GrantKind.ADJUSTMENT, None)
    AnnualLeaveRule.objects.all().delete()
    found = texts(user_in("HR", "rule_hr"))
    assert any(t.startswith("Ээлжийн амралтын үлдэгдэл хасах") for t in found)


def test_attention_not_configured_notice(emp: Employee, annual_type: LeaveTypeRow) -> None:
    LeaveTypeExt.objects.update(uses_annual_balance=False)
    notice = "Ээлжийн амралтын төрлийг сонгоогүй байна"
    admin_items = attention.items(user_in("Admin", "admin_nc"), employee_rows(Employee.objects.all(), TODAY), TODAY)
    matches = [a for a in admin_items if a.text == notice]
    assert len(matches) == 1
    assert matches[0].url == reverse("leave:settings")
    assert notice not in texts(user_in("Accountant", "acc_nc"))
    assert notice not in texts(user_in("HR"))


def _pending(emp: Employee) -> list[str]:
    return [t for t in texts(user_in("HR")) if "тушаалын дугаар оруулаагүй" in t]


def test_pending_order_listed(emp: Employee) -> None:
    from employees.models import HrOrder, OrderState, OrderType

    emp.hr_orders.all().delete()
    HrOrder.objects.create(employee=emp, is_hire=True, order_type=OrderType.HIRED, state=OrderState.PENDING)
    assert _pending(emp) == ["Ажилд орсон тушаалын дугаар оруулаагүй"]
    items = attention.items(user_in("HR", "u2"), employee_rows(Employee.objects.all(), TODAY), TODAY)
    assert next(a for a in items if a.kind == "order_number").urgency == attention.DUE


def test_registered_order_not_listed(emp: Employee) -> None:
    from employees.models import OrderState

    emp.hr_orders.update(state=OrderState.REGISTERED)
    assert _pending(emp) == []


def test_probation_ended_listed_until_type_changed(emp: Employee) -> None:
    set_ext(emp, probation_end=TODAY - timedelta(days=3))
    emp.save()
    job = emp.job_records.get()
    job.emptype = 9
    job.save()
    want = f"Туршилтын хугацаа {_fmt(TODAY - timedelta(days=3))}-нд дууссан — төрөл өөрчлөх тушаал гаргана уу"
    hr = user_in("HR")
    assert want in texts(hr)
    items = attention.items(hr, employee_rows(Employee.objects.all(), TODAY), TODAY)
    assert next(a for a in items if a.kind == "probation_ended").urgency == attention.OVERDUE
    job.emptype = 1
    job.save()
    assert want not in texts(hr)


def test_contract_ended_listed(emp: Employee) -> None:
    job = emp.job_records.get()
    job.emptype = 5
    job.contract_end = TODAY - timedelta(days=1)
    job.save()
    want = f"Гэрээ {_fmt(TODAY - timedelta(days=1))}-нд дууссан — төрөл өөрчлөх тушаал гаргана уу"
    assert want in texts(user_in("HR"))


def _expired(emp: Employee, emptype: int, **extra: Any) -> None:
    set_ext(emp, probation_end=TODAY - timedelta(days=3))
    emp.save()
    job = emp.job_records.get()
    job.emptype = emptype
    job.contract_end = TODAY - timedelta(days=1)
    for k, v in extra.items():
        setattr(job, k, v)
    job.save()


NEW_KINDS = {"order_number", "probation_ended", "contract_ended"}


def _kinds(user: User) -> set[str]:
    found = attention.items(user, employee_rows(Employee.objects.all(), TODAY), TODAY)
    return {a.kind for a in found} & NEW_KINDS


@pytest.mark.parametrize("emptype", [9, 5])
def test_left_employee_gets_no_new_items(emp: Employee, emptype: int) -> None:
    emp.hr_orders.update(state="pending")
    _expired(emp, emptype, status="left")
    assert _kinds(user_in("HR")) == set()


def test_cancelled_order_not_listed(emp: Employee) -> None:
    emp.hr_orders.update(state="cancelled")
    assert _kinds(user_in("HR")) == set()


def test_non_manager_keeps_old_contract_item_and_sees_no_new_ones(emp: Employee) -> None:
    emp.hr_orders.update(state="pending")
    _expired(emp, 5)
    acc = user_in("Accountant", "acc")
    assert _kinds(acc) == set()
    assert f"Гэрээ {_fmt(TODAY - timedelta(days=1))}-нд дууссан" in texts(acc)
    _expired(emp, 9)
    assert _kinds(acc) == set()


# --- shared date rules (attention.sees_hr_dates, probation_end, contract_end, planned_return, dated_events) ---


def _row(employee: Employee, today: date = TODAY) -> Row:
    return next(iter(employee_rows(Employee.objects.filter(pk=employee.pk), today)))


def test_sees_hr_dates_for_manage_or_salary_right() -> None:
    assert attention.sees_hr_dates(user_in("HR"))
    assert attention.sees_hr_dates(user_in("Accountant", "acc"))
    assert not attention.sees_hr_dates(user_in("Employee", "plain"))


def test_sees_hr_dates_leave_right_needs_annual_type() -> None:
    user = user_in("Employee", "leave_only")
    user.user_permissions.add(Permission.objects.get(content_type__app_label="leave", codename="view_leave"))
    user = User.objects.get(pk=user.pk)  # fresh instance: permission cache is per object
    assert not attention.sees_hr_dates(user)


def test_sees_hr_dates_leave_right_with_annual_type(annual_type: LeaveTypeRow) -> None:
    user = user_in("Employee", "leave_only")
    user.user_permissions.add(Permission.objects.get(content_type__app_label="leave", codename="view_leave"))
    user = User.objects.get(pk=user.pk)
    assert attention.sees_hr_dates(user)


def test_probation_and_contract_end_read_the_row(emp: Employee) -> None:
    set_ext(emp, probation_end=TODAY + timedelta(days=3))
    emp.save()
    job = emp.job_records.get()
    job.contract_end = TODAY + timedelta(days=9)
    job.save()
    row = _row(emp)
    assert attention.probation_end(row) == TODAY + timedelta(days=3)
    assert attention.contract_end(row) == TODAY + timedelta(days=9)


def test_probation_end_none_without_hr_row(emp: Employee) -> None:
    EmployeeExt.objects.filter(employee=emp).delete()
    assert attention.probation_end(_row(emp)) is None


def test_planned_return_only_for_long_leave_rows(emp: Employee) -> None:
    actor = user_in("HR", "hr1")
    back = TODAY + timedelta(days=20)
    events.record(
        emp,
        type="leave_start",
        effective=TODAY - timedelta(days=30),
        changes={},
        salary=None,
        reason="unpaid",
        note="",
        by=actor,
        expected_return=back,
    )
    row = _row(emp)
    assert row.state == "long_leave"
    assert attention.planned_return(row, TODAY) == back
    assert attention.planned_return(replace(row, state="active"), TODAY) is None


def test_dated_events_applied_waiting_cancelled_and_salary(emp: Employee, actor: User) -> None:
    today = timezone.localdate()  # events.cancel judges on the real clock
    ids = [emp.pk]
    events.record(  # before the window: recorded first, later changes must not precede it
        emp, type="contract", effective=today - timedelta(days=1), changes={"contract_no": "C0"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    on_day = events.record(
        emp, type="contract", effective=today, changes={"contract_no": "C1"}, salary=None, reason="", note="", by=actor
    )  # fmt: skip
    salary = events.record(
        emp, type="salary_change", effective=today + timedelta(days=2), changes={},
        salary=Decimal("3000000"), reason="", note="", by=actor,
    )  # fmt: skip
    cancelled = events.record(
        emp, type="contract", effective=today + timedelta(days=5), changes={"contract_no": "CX"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    events.cancel(cancelled, reason="алдсан", by=actor)
    waiting = events.record(
        emp, type="termination", effective=today + timedelta(days=6), changes={}, salary=None,
        reason="", fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip

    def pks(can_salary: bool, **kwargs: Any) -> set[int]:
        return set(attention.dated_events(ids, can_salary, **kwargs).values_list("pk", flat=True))

    assert pks(True, start=today) == {on_day.pk, salary.pk}
    assert pks(False, start=today) == {on_day.pk}
    assert pks(True, start=today + timedelta(days=1)) == {salary.pk}
    assert pks(True, start=today, waiting=True) == {waiting.pk}
    assert pks(True, start=today + timedelta(days=30), waiting=True) == {waiting.pk}  # waiting ignores start


def test_missing_data_rows_sit_in_the_closed_gap_section(emp: Employee, client: Client) -> None:
    """Missing data is one closed «Өгөгдөл дутуу» section with a count row per problem (no person links on the page)."""
    set_account(emp, "")
    set_contact(emp, present=False)
    emp.save()
    login_as(client, "Admin")
    html = client.get(reverse("employees:today")).content.decode()
    section = html[html.index("data-attention-gaps") :]
    assert " open" not in section.split(">", 1)[0]
    assert "Банкны мэдээлэл дутуу · 1" in section and "Яаралтай үед холбогдох хүн дутуу · 1" in section


def _approval_on_with_waiting_request(
    emp: Employee, boss_user: User, actor: User, leave_type: LeaveTypeRow, job: dict[str, Any]
) -> None:
    """Direct-manager approval is on, and one request of `emp` waits for the employee linked to `boss_user`."""
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})
    boss = history.hire(hire_values("УБ00000002"), {}, start=date(2025, 1, 1), job=job, salary=None, by=actor)
    link_login(boss, boss_user)
    job_row = emp.job_records.get()
    job_row.manager = boss
    job_row.save()
    LeaveRequest.objects.create(
        employee=emp,
        leave_type=leave_type,
        start_date=TODAY + timedelta(days=7),
        end_date=TODAY + timedelta(days=8),
        working_days=2,
        step1_manager=True,
        step_count=1,
        created_by=actor,
    )


def test_approver_sees_waiting_requests_item(
    emp: Employee, actor: User, annual_type: LeaveTypeRow, job_values: dict[str, Any]
) -> None:
    boss_user = User.objects.create_user("boss_login", password="x-long-pass-123")  # noqa: S106
    _approval_on_with_waiting_request(emp, boss_user, actor, annual_type, job_values)
    matches = [a for a in attention.items(boss_user, [], TODAY) if a.kind == "leave_requests"]
    assert [(a.text, a.url) for a in matches] == [("1 чөлөөний хүсэлт таныг хүлээж байна", reverse("leave:requests"))]


def test_non_approver_has_no_requests_item(
    emp: Employee, actor: User, annual_type: LeaveTypeRow, job_values: dict[str, Any]
) -> None:
    boss_user = User.objects.create_user("boss_login2", password="x-long-pass-123")  # noqa: S106
    _approval_on_with_waiting_request(emp, boss_user, actor, annual_type, job_values)
    stranger = user_in("Employee", "stranger_login")
    assert not any(a.kind == "leave_requests" for a in attention.items(stranger, [], TODAY))


# --- Task 1: attention tiers (urgent / soon / gaps) ---


def _grp(kind: str, urgency: int, count: int) -> attention.Group:
    items = [attention.Attention(None, f"{kind} {i}", kind, urgency) for i in range(count)]
    return attention.Group(kind, urgency, kind, items)


def test_tiers_split_by_urgency() -> None:
    overdue = [_grp("contract", attention.OVERDUE, 2)]
    due = [_grp("probation", attention.DUE, 3)]
    missing = [_grp("bank", attention.MISSING, 5)]
    t = attention.tiers(overdue + due + missing)
    assert t.urgent == overdue and t.soon == due and t.gaps == missing
    assert (t.urgent_count, t.soon_count, t.gap_count) == (2, 3, 5)


def test_tiers_empty() -> None:
    t = attention.tiers([])
    assert t.urgent == [] and t.soon == [] and t.gaps == []
    assert (t.urgent_count, t.soon_count, t.gap_count) == (0, 0, 0)


# --- Task 2: group destinations («Бүгдийг нээх →») ---


def test_group_url_orders() -> None:
    # The orders register takes ?state=, so the link opens the pending orders only (brief Task 2, Step 3).
    g = attention.Group("order_number", attention.DUE, "x", [])
    assert g.url == reverse("employees:orders") + "?state=pending"


def test_group_url_unknown_is_empty() -> None:
    g = attention.Group("bank", attention.MISSING, "x", [])
    assert g.url == ""


def test_order_group_markup_links_to_pending_orders(client: Client, emp: Employee) -> None:
    from employees.models import HrOrder, OrderState, OrderType

    emp.hr_orders.all().delete()
    HrOrder.objects.create(employee=emp, is_hire=True, order_type=OrderType.HIRED, state=OrderState.PENDING)
    login_as(client, "HR")
    html = client.get(reverse("employees:today")).content.decode()
    want_href = f'href="{reverse("employees:orders")}?state=pending"'
    assert want_href in html
    assert "Бүгдийг нээх →" in html


def test_group_without_url_renders_no_open_all_link(client: Client, emp: Employee) -> None:
    set_account(emp, "")
    login_as(client, "Accountant")
    html = client.get(reverse("employees:today")).content.decode()
    assert "Банкны мэдээлэл дутуу" in html  # the bank group is on the page
    assert "Бүгдийг нээх →" not in html


def _bank_gap_people(actor: User, job_values: dict[str, Any], count: int) -> list[Employee]:
    """New hires have no bank account: each one is a «Банкны мэдээлэл дутуу» item (distinct short names)."""
    return [
        history.hire(
            hire_values(f"УБ7733{i:04d}") | {"given_name": f"Ажилтан{i}"},
            {},
            start=date(2026, 1, 5),
            job=job_values,
            salary=None,
            by=actor,
        )  # fmt: skip
        for i in range(count)
    ]


def _gap_url(offset: int | None = None) -> str:
    url = f"{reverse('employees:attention_more')}?kind=bank&urgency={attention.MISSING}&all=1"
    return url if offset is None else f"{url}&offset={offset}"


def test_gap_page_is_capped(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    _bank_gap_people(actor, job_values, 20)
    login_as(client, "Accountant")
    body = client.get(_gap_url()).content.decode()
    assert body.count("data-chip") == attention.GAP_PAGE
    assert body.count("data-gap-more") == 1 and "+ 12 бусад →" in body


def test_gap_page_offset_continues(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    _bank_gap_people(actor, job_values, 20)
    login_as(client, "Accountant")
    second = client.get(_gap_url(8)).content.decode()
    assert second.count("data-chip") == 8 and "+ 4 бусад →" in second
    last = client.get(_gap_url(16)).content.decode()
    assert last.count("data-chip") == 4 and "data-gap-more" not in last
    past = client.get(_gap_url(99))
    assert past.status_code == 200 and past.content.strip() == b""


def test_gap_bad_offset_is_zero(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    _bank_gap_people(actor, job_values, 20)
    login_as(client, "Accountant")
    first = client.get(_gap_url(0)).content
    assert client.get(_gap_url("abc")).content == first  # type: ignore[arg-type]
    assert client.get(_gap_url(-5)).content == first


def test_label_clashes_marks_same_short_names() -> None:
    a = Employee(pk=1, family_name="Батын", given_name="Азжаргал")
    b = Employee(pk=2, family_name="Бямбын", given_name="Азжаргал")  # also «Б. Азжаргал»
    c = Employee(pk=3, family_name="Батын", given_name="Сараа")
    items = [attention.Attention(e, "text", "bank") for e in (a, b, c)]
    assert attention.label_clashes(items) == {1, 2}
    assert attention.label_clashes(items + [attention.Attention(None, "system", "lists_death")]) == {1, 2}


def test_clashing_chips_show_code(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    people = _bank_gap_people(actor, job_values, 3)
    for employee, family, code in zip(
        people, ("Батын", "Бямбын", "Гантулга"), ("UB001", "UB002", "UB003"), strict=True
    ):
        Employee.objects.filter(pk=employee.pk).update(family_name=family, given_name="Азжаргал", code=code)
    login_as(client, "Accountant")
    body = client.get(_gap_url()).content.decode()
    assert "Б. Азжаргал · UB001" in body and "Б. Азжаргал · UB002" in body
    assert "UB003" not in body  # its short name is unique in the group: no code


def _page_pks(body: str) -> list[int]:
    return [int(pk) for pk in re.findall(r'href="/employees/(\d+)/#salary"', body)]


def test_gap_pages_are_disjoint_and_cover_the_group(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    people = _bank_gap_people(actor, job_values, 20)
    login_as(client, "Accountant")
    pages = [_page_pks(client.get(_gap_url(offset)).content.decode()) for offset in (0, 8, 16)]
    shown = [pk for page in pages for pk in page]
    assert len(shown) == len(set(shown)) == 20  # no person twice across the pages
    assert set(shown) == {person.pk for person in people}


def test_gap_all_is_ignored_for_a_dated_group(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    today = timezone.localdate()
    _contract_people(actor, job_values, [today + timedelta(days=d) for d in range(3, 8)])  # 5 due contracts
    login_as(client, "HR")
    url = f"{reverse('employees:attention_more')}?kind=contract&urgency={attention.DUE}&all=1"
    body = client.get(url).content.decode()
    assert body.count("group/item") == 5 - attention.GROUP_LIMIT  # the normal rest past three, not all five
    assert "data-gap-more" not in body


def test_gap_all_shows_only_the_scope_users_people(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    north, south = Branch.objects.create(name="Хойд"), Branch.objects.create(name="Өмнөд")
    inside, other = _bank_gap_people(actor, job_values, 2)
    Employee.objects.filter(pk=inside.pk).update(branch_id=north.pk)
    Employee.objects.filter(pk=other.pk).update(branch_id=south.pk)
    accountant = login_as(client, "Accountant")
    AccessScope.objects.update_or_create(user=accountant, defaults={"limited": True, "branch_ids": [north.pk]})
    body = client.get(_gap_url()).content.decode()
    assert f"/employees/{inside.pk}/" in body
    assert f"/employees/{other.pk}/" not in body


def test_dismiss_refreshes_the_tile_out_of_band(client: Client, emp: Employee, actor: User) -> None:
    emp.job_records.update(contract_end=timezone.localdate() - timedelta(days=10))  # one overdue item
    hr = login_as(client, "HR")
    today = timezone.localdate()
    urgent = next(
        a for a in attention.items(hr, employee_rows(Employee.objects.all(), today), today)
        if a.urgency == attention.OVERDUE
    )  # fmt: skip
    body = client.post(reverse("employees:attention"), {"key": urgent.key, "action": "dismiss"}).content.decode()
    assert 'id="attention-tile"' in body and 'hx-swap-oob="true"' in body
    assert re.search(r'data-tile="attention">0<', body)
