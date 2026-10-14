from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from employees import attention
from employees.listing import employee_rows
from employees.models import Employee, SalaryInsurance, SetupItem
from employees.services import events, history

from .conftest import new_employee
from .test_views import login_as

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def user_in(role: str, name: str = "u1") -> User:
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return u


def texts(user: User, today: date = TODAY) -> list[str]:
    from employees.models import Employee as E

    return [a.text for a in attention.items(user, employee_rows(E.objects.all(), today), today)]


@pytest.fixture
def emp(hired: Employee) -> Employee:
    hired.emergency_name, hired.emergency_phone = "А", "99"
    hired.setup_required = False
    hired.save()
    SalaryInsurance.objects.create(employee=hired, account_no="123")
    return hired


@pytest.mark.parametrize(("delta", "shown"), [(-1, False), (0, True), (14, True), (15, False)])
def test_probation_boundaries(emp: Employee, delta: int, shown: bool) -> None:
    emp.probation_end = TODAY + timedelta(days=delta)
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
    emp.setup_required = True
    emp.save()
    hr = user_in("HR")
    assert "Бүрдүүлэлт дутуу" in texts(hr)
    emp.setup_required = False
    emp.save()
    assert "Бүрдүүлэлт дутуу" not in texts(hr)


def test_accountant_sees_neither_setup_nor_personal(emp: Employee) -> None:
    emp.setup_required, emp.emergency_name = True, ""
    emp.save()
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")
    got = texts(user_in("Accountant"))
    assert got == ["Банкны мэдээлэл бүртгээгүй"]


def test_hr_never_sees_bank_rule(emp: Employee) -> None:
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")
    emp.emergency_phone = ""
    emp.save()
    got = texts(user_in("HR"))
    assert got == ["Яаралтай үед холбогдох хүн бүртгээгүй"]


def test_employee_role_empty(emp: Employee) -> None:
    emp.emergency_name = ""
    emp.save()
    assert texts(user_in("Employee")) == []


def test_left_excluded_and_sorted(emp: Employee, actor: User, job_values: dict[str, Any]) -> None:
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")
    other = history.hire(new_employee("УБ00000002"), start=date(2025, 1, 1), job=job_values, salary=None, by=actor)
    other.family_name = "Аавын"
    other.save()
    admin = User.objects.create_superuser("root", password="x-long-pass-123")  # noqa: S106
    rows = employee_rows(Employee.objects.all(), TODAY)
    names = [a.employee.full_name for a in attention.items(admin, rows, TODAY) if a.kind == "bank"]
    assert names == ["Аавын Сараа", "Батын Сараа"]
    history.change_job(
        other, effective=date(2025, 6, 1), changes={"status": "left"}, change_type="correction", note="", by=actor
    )
    rows = employee_rows(Employee.objects.all(), TODAY)
    assert {a.employee.pk for a in attention.items(admin, rows, TODAY)} == {emp.pk}


def test_strip_on_full_page_only(client: Client, emp: Employee) -> None:
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")
    login_as(client, "Accountant")
    url = reverse("employees:list")
    assert "Анхаарах (1)" in client.get(url).content.decode()
    assert "Анхаарах" not in client.get(url, HTTP_HX_REQUEST="true").content.decode()


def _fully_ticked_without_bank(emp: Employee) -> None:
    emp.setup_required = True
    emp.user = User.objects.create_user("linked", password="x-long-pass-123")  # noqa: S106
    emp.save()
    for key in ("contract", "id_copy", "equipment"):
        SetupItem.objects.create(employee=emp, key=key)
    SalaryInsurance.objects.filter(employee=emp).update(account_no="")


def test_setup_complete_for_hr_but_not_admin_when_only_bank_missing(emp: Employee) -> None:
    _fully_ticked_without_bank(emp)
    assert "Бүрдүүлэлт дутуу" not in texts(user_in("HR"))
    admin = User.objects.create_superuser("root", password="x-long-pass-123")  # noqa: S106
    assert "Бүрдүүлэлт дутуу" in texts(admin)


def test_missing_salary_insurance_row_flags_bank_for_accountant(emp: Employee) -> None:
    SalaryInsurance.objects.filter(employee=emp).delete()
    assert "Банкны мэдээлэл бүртгээгүй" in texts(user_in("Accountant"))


def test_scheduled_termination_and_near_event_shown(emp: Employee, actor: User) -> None:
    events.record(
        emp, type="contract", effective=TODAY + timedelta(days=7), changes={"contract_no": "CN-NEW"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    events.record(
        emp, type="termination", effective=TODAY + timedelta(days=20), changes={}, salary=None,
        reason="resignation", note="", by=actor,
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
    ev = events.record(
        emp, type="termination", effective=TODAY + timedelta(days=5), changes={}, salary=None,
        reason="resignation", note="", by=actor,
    )  # fmt: skip
    events.cancel(ev, reason="алдсан", by=actor)
    assert not any(t.startswith("Гарах") for t in texts(user_in("HR")))


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
        history.hire(new_employee(f"УБ991122{i:02d}"), start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    hr = user_in("HR", "hr1")
    found = attention.items(hr, employee_rows(Employee.objects.all(), today), today)
    assert found[0].employee == emp and "дууссан" in found[0].text
    assert [a.urgency for a in found] == sorted(a.urgency for a in found)
    login_as(client, "HR")
    html = client.get(reverse("employees:list")).content.decode()
    assert len(found) > 5 and f"Бүгдийг харах ({len(found)})" in html


def _scheduled_leave(emp: Employee, actor: User, start: date) -> None:
    events.record(emp, type="leave_start", effective=start, changes={}, salary=None, reason="unpaid", note="", by=actor)


def test_dismiss_hides_for_that_user_only_and_can_be_restored(client: Client, emp: Employee, actor: User) -> None:
    today = timezone.localdate()
    _scheduled_leave(emp, actor, today + timedelta(days=3))
    hr = login_as(client, "HR")
    item = next(a for a in attention.items(hr, employee_rows(Employee.objects.all(), today), today))
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
