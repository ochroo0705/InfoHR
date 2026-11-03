"""Hire and rehire start an onboarding checklist; it never blocks or fails anything."""

from datetime import date, timedelta
from typing import Any

import pytest
from accounts.models import User
from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTemplate
from checklists.services import lifecycle, onboarding
from django.test import Client
from django.utils import timezone
from macs.models import FiredReason

from employees.models import Employee
from employees.services import events
from employees.tests.helpers import record_signed, sign_event

from .conftest import named
from .test_views import add_payload, login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def onboarding_on() -> ChecklistTemplate:
    """The conftest switches every template off; onboarding tests want the starter back."""
    ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING).update(active=True)
    return ChecklistTemplate.objects.get(kind=ChecklistKind.ONBOARDING, is_default=True)


def _hire_via_view(client: Client, job_values: dict[str, Any], **extra: str) -> Employee:
    login_as(client, "HR")
    response = client.post("/employees/new/", add_payload(job_values, **extra))
    assert response.status_code == 302
    return Employee.objects.get(register_no="УК88010122")


def _onboarding(employee: Employee) -> list[Checklist]:
    return list(Checklist.objects.filter(employee=employee, kind=ChecklistKind.ONBOARDING).order_by("pk"))


def test_hire_without_template_succeeds_with_no_checklist(client: Client, job_values: dict[str, Any]) -> None:
    employee = _hire_via_view(client, job_values)  # the autouse fixture left every template inactive
    assert _onboarding(employee) == []


def test_hire_starts_open_checklist_on_start_date(
    client: Client, job_values: dict[str, Any], onboarding_on: ChecklistTemplate
) -> None:
    employee = _hire_via_view(client, job_values, start="2026-12-01")
    (checklist,) = _onboarding(employee)
    assert checklist.state == ChecklistState.OPEN
    assert checklist.anchor_day == date(2026, 12, 1)  # a future start date is the anchor
    assert checklist.template == onboarding_on


def test_hire_uses_template_of_the_employment_type(
    client: Client, job_values: dict[str, Any], onboarding_on: ChecklistTemplate
) -> None:
    full_time = ChecklistTemplate.objects.create(
        kind=ChecklistKind.ONBOARDING, name="Үндсэн ажилтан", reasons=["full_time"], active=True
    )
    employee = _hire_via_view(client, job_values)  # add_payload hires a full_time employee
    (checklist,) = _onboarding(employee)
    assert checklist.template == full_time  # the type-specific template wins over the default


def test_failure_in_start_does_not_fail_the_hire(
    client: Client, job_values: dict[str, Any], onboarding_on: ChecklistTemplate, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(lifecycle, "start", boom)
    employee = _hire_via_view(client, job_values)
    assert _onboarding(employee) == []


def _terminate(employee: Employee, actor: User, day: date) -> None:
    record_signed(
        employee,
        type="termination",
        effective=day,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )


def _rehire(employee: Employee, actor: User, day: date) -> None:
    record_signed(employee, type="rehire", effective=day, changes={}, salary=None, reason="", note="", by=actor)


def test_rehire_starts_new_checklist_after_completed_one(
    hired: Employee, actor: User, onboarding_on: ChecklistTemplate
) -> None:
    first = onboarding.start_for_hire(hired, start_date=date(2026, 1, 5), employee_type="full_time", by=actor)
    assert first is not None
    Checklist.objects.filter(pk=first.pk).update(state=ChecklistState.COMPLETED)
    _terminate(hired, actor, date(2026, 3, 1))
    _rehire(hired, actor, date(2026, 5, 1))
    checklists = _onboarding(hired)
    assert len(checklists) == 2
    assert checklists[1].state == ChecklistState.OPEN and checklists[1].anchor_day == date(2026, 5, 1)


def test_termination_cancels_open_onboarding_and_rehire_starts_a_new_one(
    hired: Employee, actor: User, onboarding_on: ChecklistTemplate
) -> None:
    first = onboarding.start_for_hire(hired, start_date=date(2026, 1, 5), employee_type="full_time", by=actor)
    assert first is not None
    _terminate(hired, actor, date(2026, 3, 1))
    first.refresh_from_db()
    assert first.state == ChecklistState.CANCELLED  # a leaver keeps no open onboarding
    _rehire(hired, actor, date(2026, 5, 1))
    checklists = _onboarding(hired)
    assert len(checklists) == 2
    assert checklists[1].state == ChecklistState.OPEN and checklists[1].anchor_day == date(2026, 5, 1)


def test_failure_cancelling_onboarding_does_not_fail_the_termination(
    hired: Employee, actor: User, onboarding_on: ChecklistTemplate, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = onboarding.start_for_hire(hired, start_date=date(2026, 1, 5), employee_type="full_time", by=actor)
    assert first is not None

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(lifecycle, "cancel_open", boom)
    _terminate(hired, actor, date(2026, 3, 1))
    first.refresh_from_db()
    assert first.state == ChecklistState.OPEN
    assert hired.events.filter(type="termination", applied_at__isnull=False).exists()


def test_cancelling_a_scheduled_rehire_cancels_its_onboarding(
    hired: Employee, actor: User, onboarding_on: ChecklistTemplate
) -> None:
    _terminate(hired, actor, date(2026, 3, 1))
    future = timezone.localdate() + timedelta(days=30)
    rehire = record_signed(
        hired, type="rehire", effective=future, changes={}, salary=None, reason="", note="", by=actor
    )
    (checklist,) = _onboarding(hired)
    assert checklist.state == ChecklistState.OPEN and checklist.anchor_day == future
    events.cancel(rehire, reason="Буцсан", by=actor, cancel_order_no="А/50")
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.CANCELLED


def test_cancelling_a_waiting_rehire_leaves_other_onboarding_alone(
    hired: Employee, actor: User, onboarding_on: ChecklistTemplate
) -> None:
    other = onboarding.start_for_hire(hired, start_date=date(2026, 1, 5), employee_type="full_time", by=actor)
    assert other is not None
    # A leaver whose termination predates the checklist keeps an open one only by hand: reopen it for the test.
    _terminate(hired, actor, date(2026, 3, 1))
    Checklist.objects.filter(pk=other.pk).update(state=ChecklistState.OPEN)
    rehire = events.record(
        hired, type="rehire", effective=date(2026, 5, 1), changes={}, salary=None, reason="", note="", by=actor
    )
    assert rehire.applied_at is None  # waiting for its order: it started no checklist
    events.cancel(rehire, reason="Буцсан", by=actor)
    other.refresh_from_db()
    assert other.state == ChecklistState.OPEN


def test_waiting_rehire_starts_only_when_applied(
    hired: Employee, actor: User, onboarding_on: ChecklistTemplate
) -> None:
    _terminate(hired, actor, date(2026, 3, 1))
    rehire = events.record(
        hired, type="rehire", effective=date(2026, 5, 1), changes={}, salary=None, reason="", note="", by=actor
    )
    assert rehire.applied_at is None  # a rehire waits for its signed order
    assert _onboarding(hired) == []
    sign_event(rehire, by=actor)
    (checklist,) = _onboarding(hired)
    assert checklist.anchor_day == date(2026, 5, 1)


def test_open_onboarding_never_blocks_events(hired: Employee, actor: User, onboarding_on: ChecklistTemplate) -> None:
    onboarding.start_for_hire(hired, start_date=date(2026, 1, 5), employee_type="full_time", by=actor)
    day = timezone.localdate() - timedelta(days=1)
    event = record_signed(
        hired, type="leave_start", effective=day, changes={}, salary=None, reason="unpaid", note="", by=actor
    )
    assert event.applied_at is not None
    _terminate(hired, actor, day + timedelta(days=1))  # no gate for a termination either
