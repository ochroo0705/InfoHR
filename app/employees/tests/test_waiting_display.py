"""A change that waits for its signed order is shown to the user (signed-order plan, Task 7b): the Work tab block,
the order pop-up's chip and note, the attention group (overdue when its date has passed) and the order register's chip.
An applied change shows none of it."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from macs.models import FiredReason

from employees import attention
from employees.listing import employee_rows
from employees.models import Employee, Event, HrOrder, Position
from employees.services import events, history, macs_writes
from employees.tests.conftest import hire_values, named
from employees.tests.helpers import record_signed
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

BLOCK = "Гарын үсэг хүлээж буй өөрчлөлт"
DUE_HEADING = "Гарын үсэг хүлээж буй өөрчлөлт"
OVERDUE_HEADING = "Гарын үсэг хүлээж буй өөрчлөлт — хугацаа нь болсон"
CHIP = "Гарын үсэг хүлээж байна"
NOTE = "Тушаал гарын үсэгтэй болмогц хүчин төгөлдөр болно"
OVERDUE = "хугацаа нь болсон"
ORDER_NUMBER = "дугаар оруулаагүй"
AMOUNT = "3123456"
AMOUNT_GROUPED = "3,123,456"


@pytest.fixture
def today() -> date:
    return timezone.localdate()


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr_display")
    return client


def _kwargs(actor: User, effective: date, salary: Decimal | None = None) -> dict[str, Any]:
    """A job-only promotion by default; `events.record` makes it wait for its signed order."""
    new = Position.objects.create(name=f"Ахлах {effective.isoformat()}")
    return {
        "type": "promotion",
        "effective": effective,
        "changes": {"position": new},
        "salary": salary,
        "reason": "",
        "note": "",
        "by": actor,
    }


def _waiting(emp: Employee, actor: User, effective: date, salary: Decimal | None = None) -> Event:
    ev = events.record(emp, **_kwargs(actor, effective, salary))
    assert ev.applied_at is None
    return ev


def _work(client: Client, emp: Employee) -> str:
    return client.get(f"/employees/{emp.pk}/").content.decode()


def _today_page(client: Client) -> str:
    return client.get(reverse("employees:today")).content.decode()


def test_work_tab_lists_the_waiting_change_with_its_chip_date_and_cancel(
    hr: Client, hired: Employee, actor: User, today: date
) -> None:
    ev = _waiting(hired, actor, today + timedelta(days=20))
    body = _work(hr, hired)
    assert BLOCK in body
    assert ev.get_type_display() in body
    assert (today + timedelta(days=20)).isoformat() in body
    assert CHIP in body
    assert "дугаар хүлээгдэж байна" in body
    assert reverse("employees:event_cancel", args=[hired.pk, ev.pk]) in body
    # The waiting order is listed once: in the block (its pop-up link). Not in the «Бусад тушаал» panel.
    order = HrOrder.objects.get(event=ev)
    assert body.count(reverse("employees:order_detail", args=[hired.pk, order.pk])) == 1
    assert f'id="order-{order.pk}"' not in body


def test_block_is_hidden_when_nothing_waits(hr: Client, hired: Employee, actor: User, today: date) -> None:
    record_signed(hired, **_kwargs(actor, today - timedelta(days=3)))
    body = _work(hr, hired)
    assert BLOCK not in body
    assert CHIP not in body


def test_accountant_sees_the_waiting_job_change_but_no_cancel(
    client: Client, hired: Employee, actor: User, today: date
) -> None:
    ev = _waiting(hired, actor, today + timedelta(days=20))
    login_as(client, "Accountant", "acc_display")
    body = _work(client, hired)
    assert BLOCK in body
    assert reverse("employees:event_cancel", args=[hired.pk, ev.pk]) not in body


def test_order_pop_up_shows_chip_and_note_for_a_waiting_change(
    hr: Client, hired: Employee, actor: User, today: date
) -> None:
    ev = _waiting(hired, actor, today + timedelta(days=20))
    order = HrOrder.objects.get(event=ev)
    body = hr.get(reverse("employees:order_detail", args=[hired.pk, order.pk])).content.decode()
    assert CHIP in body and NOTE in body


def test_order_pop_up_has_no_waiting_chip_for_an_applied_change(
    hr: Client, hired: Employee, actor: User, today: date
) -> None:
    ev = record_signed(hired, **_kwargs(actor, today - timedelta(days=3)))
    order = HrOrder.objects.get(event=ev)
    body = hr.get(reverse("employees:order_detail", args=[hired.pk, order.pk])).content.decode()
    assert CHIP not in body and NOTE not in body


def test_attention_shows_a_waiting_change_and_flags_one_whose_date_passed(
    hr: Client, hired: Employee, actor: User, today: date
) -> None:
    _waiting(hired, actor, today - timedelta(days=2))
    body = _today_page(hr)
    assert BLOCK in body
    assert "гарын үсэг хүлээж байна" in body
    assert OVERDUE in body


def test_only_the_overdue_heading_shows_when_only_overdue_changes_exist(
    hr: Client, hired: Employee, actor: User, today: date
) -> None:
    _waiting(hired, actor, today - timedelta(days=2))
    body = _today_page(hr)
    assert body.count(f"{OVERDUE_HEADING} · 1</h3>") == 1
    assert body.count(f"{DUE_HEADING} · 1</h3>") == 0


def test_only_the_due_heading_shows_when_only_future_changes_exist(
    hr: Client, hired: Employee, actor: User, today: date
) -> None:
    _waiting(hired, actor, today + timedelta(days=5))
    body = _today_page(hr)
    assert body.count(f"{DUE_HEADING} · 1</h3>") == 1
    assert body.count(f"{OVERDUE_HEADING} · 1</h3>") == 0
    assert OVERDUE not in body  # a future-dated waiting change is not overdue


def test_both_headings_show_distinct_when_both_kinds_exist(
    hr: Client, hired: Employee, actor: User, job_values: dict[str, Any], today: date
) -> None:
    _waiting(hired, actor, today - timedelta(days=2))
    other = history.hire(
        hire_values("УБ99112234"), {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor
    )
    _waiting(other, actor, today + timedelta(days=5))  # the second employee's change is not yet due
    body = _today_page(hr)
    assert body.count(f"{OVERDUE_HEADING} · 1</h3>") == 1
    assert body.count(f"{DUE_HEADING} · 1</h3>") == 1


def _texts(user: User, today: date) -> list[str]:
    rows = employee_rows(Employee.objects.all(), today)
    return [a.text for a in attention.items(user, rows, today)]


def test_attention_waiting_item_is_added_and_other_items_stay(hired: Employee, actor: User, today: date) -> None:
    hr_user = User.objects.create_user("hr_att_display", password="x-long-pass-123")  # noqa: S106
    hr_user.groups.add(Group.objects.get(name="HR"))
    before = _texts(hr_user, today)
    _waiting(hired, actor, today - timedelta(days=2))
    after = _texts(hr_user, today)
    waiting = [t for t in after if "гарын үсэг хүлээж байна" in t]
    assert len(waiting) == 1 and waiting[0].endswith(OVERDUE)
    # The waiting order also raises the existing "order number missing" item; everything else is unchanged.
    others = [t for t in after if t not in waiting and ORDER_NUMBER not in t]
    assert others == [t for t in before if ORDER_NUMBER not in t]


def test_attention_includes_a_waiting_rehire_of_a_left_employee(hired: Employee, actor: User, today: date) -> None:
    """A rehire waits for its order; the employee is left meanwhile, and the attention box must still show it."""
    record_signed(
        hired,
        type="termination",
        effective=today - timedelta(days=60),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    rehire = events.record(
        hired,
        type="rehire",
        effective=today + timedelta(days=10),
        changes={"position": macs_writes.save_position("Программист")},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert rehire.applied_at is None
    hr_user = User.objects.create_user("hr_left_display", password="x-long-pass-123")  # noqa: S106
    hr_user.groups.add(Group.objects.get(name="HR"))
    assert hired.pk in {r.employee.pk for r in employee_rows(Employee.objects.all(), today) if r.state == "left"}
    texts = _texts(hr_user, today)
    assert f"{rehire.get_type_display()} {(today + timedelta(days=10)).isoformat()} — гарын үсэг хүлээж байна" in texts


def test_waiting_change_with_salary_shows_no_amount_to_hr_without_salary_right(
    hr: Client, hired: Employee, actor: User, today: date
) -> None:
    ev = _waiting(hired, actor, today + timedelta(days=20), salary=Decimal(AMOUNT))
    assert ev.applied_at is None
    body = _work(hr, hired)
    assert BLOCK in body and ev.get_type_display() in body
    assert AMOUNT not in body and AMOUNT_GROUPED not in body
    # A job + salary change needs both rights to cancel: HR (no salary manage right) gets no cancel button.
    assert reverse("employees:event_cancel", args=[hired.pk, ev.pk]) not in body
    page = _today_page(hr)
    assert AMOUNT not in page and AMOUNT_GROUPED not in page


def test_waiting_change_with_salary_has_no_cancel_for_accountant_without_manage(
    client: Client, hired: Employee, actor: User, today: date
) -> None:
    ev = _waiting(hired, actor, today + timedelta(days=20), salary=Decimal(AMOUNT))
    login_as(client, "Accountant", "acc_salary_display")
    body = _work(client, hired)
    assert BLOCK in body
    assert reverse("employees:event_cancel", args=[hired.pk, ev.pk]) not in body


def test_register_row_shows_the_chip_for_a_waiting_order(hr: Client, hired: Employee, actor: User, today: date) -> None:
    _waiting(hired, actor, today + timedelta(days=20))
    body = hr.get(reverse("employees:orders")).content.decode()
    assert CHIP in body


def test_register_row_has_no_chip_for_an_applied_order(hr: Client, hired: Employee, actor: User, today: date) -> None:
    record_signed(hired, **_kwargs(actor, today + timedelta(days=20)))
    body = hr.get(reverse("employees:orders")).content.decode()
    assert CHIP not in body
