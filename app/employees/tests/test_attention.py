from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from leave.models import GrantKind, LeaveTypeExt
from leave.services import entitlement as leave_entitlement
from leave.services import ledger as leave_ledger
from leave.services import writes as leave_writes
from leave.services.fmt import fmt_days
from macs.models import ContactRow, ContactType, Entitlement, FiredReason, LeaveTypeRow

from employees import attention
from employees.listing import employee_rows
from employees.models import Employee, SetupItem
from employees.services import events, history

from .conftest import hire_values, link_login, named, set_account, set_ext
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


def test_strip_on_full_page_only(client: Client, emp: Employee) -> None:
    set_account(emp, "")
    login_as(client, "Accountant")
    url = reverse("employees:list")
    assert "Банкны мэдээлэл дутуу · 1" in client.get(url).content.decode()
    assert "Анхаарах" not in client.get(url, HTTP_HX_REQUEST="true").content.decode()


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
    events.record(
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
    for i in range(6):  # new hires without an emergency contact: one "missing" item each at least
        history.hire(hire_values(f"УБ991122{i:02d}"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    hr = user_in("HR", "hr1")
    found = attention.items(hr, employee_rows(Employee.objects.all(), today), today)
    assert found[0].employee == emp and "дууссан" in found[0].text
    assert [a.urgency for a in found] == sorted(a.urgency for a in found)
    login_as(client, "HR")
    html = client.get(reverse("employees:list")).content.decode()
    groups = attention.group(found)
    assert groups[0].label == "Гэрээ дууссан" and groups[0].dated
    assert [g.urgency for g in groups] == sorted(g.urgency for g in groups)
    assert sum(len(g.items) for g in groups) == len(found)
    emergency = next(g for g in groups if g.kind == "emergency")
    assert not emergency.dated and len(emergency.items) >= 6
    assert "Гэрээ дууссан" in html and f"Яаралтай үед холбогдох хүн дутуу · {len(emergency.items)}" in html
    assert f"+{len(emergency.items) - 5}" in html  # chips past five fold behind "+N"


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
    events.record(
        emp, type="termination", effective=date(2026, 3, 1), changes={}, salary=None,
        reason="", fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    events.record(
        emp, type="rehire", effective=TODAY + timedelta(days=30), changes={}, salary=None,
        reason="", note="", by=actor,
    )  # fmt: skip
    rows = employee_rows(Employee.objects.all(), TODAY)
    found = attention.items(user_in("HR"), rows, TODAY)
    assert not any(a.kind == "leave_balance" for a in found)


def test_box_opens_only_when_something_is_overdue(client: Client, emp: Employee) -> None:
    set_account(emp, "")
    login_as(client, "Accountant")
    url = reverse("employees:list")
    assert " open data-overdue" not in client.get(url).content.decode()  # only missing data: folded
    emp.job_records.update(contract_end=timezone.localdate() - timedelta(days=1))
    assert " open data-overdue" in client.get(url).content.decode()


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
