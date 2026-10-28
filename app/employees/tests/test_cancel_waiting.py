"""A change that waits for its signed order can be cancelled at any time: nothing was written, so nothing is undone. An
applied change stays cancellable only while it is still scheduled (signed-order plan, Task 6)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from macs.models import EmployeeHistory, Movement

from employees import access
from employees.models import Employee, EmployeeExt, Event, HrOrder, JobRecord, OrderState, SalaryRecord
from employees.services import events, macs_writes
from employees.services.events import EventError
from employees.tests.helpers import record_signed
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

PAST = date(2026, 3, 1)
LATER = date(2026, 4, 1)
OLD_MESSAGE = "Зөвхөн төлөвлөсөн үйл явдлыг цуцлах боломжтой."


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


def future() -> date:
    return timezone.localdate() + timedelta(days=30)


def waiting_promotion(employee: Employee, actor: User, effective: date) -> Event:
    position = macs_writes.save_position("Ахлах нягтлан")
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


def history_counts(employee: Employee) -> tuple[int, int, int, int]:
    return (
        JobRecord.objects.filter(employee=employee).count(),
        SalaryRecord.objects.filter(employee=employee).count(),
        Movement.objects.filter(employee=employee).count(),
        EmployeeHistory.objects.count(),
    )


def test_cancel_waiting_past_dated_change(hired: Employee, actor: User) -> None:
    ev = waiting_promotion(hired, actor, PAST)
    events.cancel(ev, reason="Буруу бүртгэл", by=actor)
    ev.refresh_from_db()
    assert ev.status(timezone.localdate()) == "cancelled"
    order = HrOrder.objects.get(event=ev)
    assert order.state == OrderState.CANCELLED


def test_cancel_waiting_leaves_history_untouched(hired: Employee, actor: User) -> None:
    ev = waiting_promotion(hired, actor, PAST)
    before = history_counts(hired)
    events.cancel(ev, reason="Буруу бүртгэл", by=actor)
    assert history_counts(hired) == before


def test_cancel_applied_past_change_still_refused(hired: Employee, actor: User) -> None:
    position = macs_writes.save_position("Ахлах нягтлан")
    ev = record_signed(
        hired,
        type="promotion",
        effective=PAST,
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert ev.applied_at is not None
    with pytest.raises(EventError) as exc:
        events.cancel(ev, reason="x", by=actor)
    assert exc.value.errors == {"__all__": OLD_MESSAGE}


def test_cancel_applied_future_change_still_works(hired: Employee, actor: User) -> None:
    position = macs_writes.save_position("Ахлах нягтлан")
    ev = record_signed(
        hired,
        type="promotion",
        effective=future(),
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    events.cancel(ev, reason="x", by=actor, cancel_order_no="А/30")  # a signed order needs its new number
    ev.refresh_from_db()
    assert ev.cancelled_at is not None and ev.status(timezone.localdate()) == "cancelled"


def test_order_detail_shows_cancel_for_waiting_change(hr: Client, hired: Employee, actor: User) -> None:
    ev = waiting_promotion(hired, actor, PAST)
    order = HrOrder.objects.get(event=ev)
    response = hr.get(f"/employees/{hired.pk}/order/{order.pk}/detail/")
    assert response.status_code == 200
    assert reverse("employees:event_cancel", args=[hired.pk, ev.pk]) in response.content.decode()
    assert "Цуцлах" in response.content.decode()


def pension_contract(employee: Employee, actor: User, effective: date) -> Event:
    return events.record(
        employee,
        type="contract",
        effective=effective,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        pension=True,
    )


def test_cancelling_waiting_pension_contract_keeps_pensioner_flag_false(hired: Employee, actor: User) -> None:
    # No applied pension contract exists, so the flag stays False even while another waiting pension contract lives.
    first = pension_contract(hired, actor, PAST)
    pension_contract(hired, actor, LATER)
    assert first.applied_at is None
    events.cancel(first, reason="x", by=actor)
    assert EmployeeExt.objects.get(employee=hired).is_pensioner is False


def test_cancelling_waiting_pension_contract_keeps_applied_pensioner_flag(hired: Employee, actor: User) -> None:
    applied = record_signed(
        hired,
        type="contract",
        effective=PAST,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        pension=True,
    )
    assert applied.applied_at is not None
    assert EmployeeExt.objects.get(employee=hired).is_pensioner is True
    waiting = pension_contract(hired, actor, LATER)
    assert waiting.applied_at is None
    events.cancel(waiting, reason="x", by=actor)
    assert EmployeeExt.objects.get(employee=hired).is_pensioner is True


def test_can_cancel_waiting_change_follows_what_it_would_change(hired: Employee, actor: User) -> None:
    hr = login_user("HR", "hr_cancel_a")
    acc = login_user("Accountant", "acc_cancel_a")
    admin = login_user("Admin", "adm_cancel_a")
    engineering = macs_writes.save_department("Инженер")
    mixed = events.record(
        hired,
        type="transfer",
        effective=LATER,
        changes={"department": engineering},
        salary=Decimal("3000000"),
        reason="",
        note="",
        by=actor,
    )
    assert mixed.applied_at is None
    assert [access.can_cancel(u, mixed) for u in (hr, acc, admin)] == [False, False, True]
    job_only = events.record(
        hired,
        type="transfer",
        effective=LATER + timedelta(days=1),
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert [access.can_cancel(u, job_only) for u in (hr, acc)] == [True, False]


def login_user(group: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=group))
    return user
