from datetime import date, timedelta
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import ActivityEntry, Employee, Event
from employees.services import events
from macs.models import FiredReason

from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTemplate
from checklists.services import lifecycle

pytestmark = pytest.mark.django_db


def _login(client: Client, role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def _url(employee: Employee) -> str:
    return f"/employees/{employee.pk}/event/termination/"


def _data(fired_reason: FiredReason, **extra: Any) -> dict[str, Any]:
    day = timezone.localdate() + timedelta(days=30)
    return {"effective": day.isoformat(), "fired_reason": fired_reason.pk, "note": "", **extra}


def _record(employee: Employee, actor: User, fired_reason: FiredReason, **kw: Any) -> Event:
    return events.record(
        employee,
        type="termination",
        effective=timezone.localdate() + timedelta(days=30),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=fired_reason,
        **kw,
    )


def test_no_template_records_as_before(client: Client, hired: Employee, fired_reason: FiredReason) -> None:
    ChecklistTemplate.objects.update(active=False)
    _login(client, "HR", "hr1")
    assert client.post(_url(hired), _data(fired_reason)).status_code == 204
    assert Event.objects.filter(type="termination").count() == 1
    assert not Checklist.objects.exists()


def test_refused_attempt_starts_checklist_and_lists_open_tasks(
    client: Client, hired: Employee, fired_reason: FiredReason
) -> None:
    _login(client, "HR", "hr1")
    response = client.post(_url(hired), _data(fired_reason))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Ажлаа хүлээлгэн өгөх — Шууд удирдлага" in body
    assert "Нэвтрэх эрх хаах — Admin" in body
    assert "Ажлаас гарах ярилцлага" not in body  # optional task is not listed
    assert not Event.objects.filter(type="termination").exists()
    checklist = Checklist.objects.get(employee=hired)
    assert checklist.state == ChecklistState.OPEN


def test_all_required_ticked_records_and_completes_checklist(
    hired: Employee, actor: User, fired_reason: FiredReason
) -> None:
    from checklists.services import gate, lifecycle

    day = timezone.localdate() + timedelta(days=30)
    gate.prepare(hired, reason=str(fired_reason.pk), anchor_day=day, by=actor)
    checklist = lifecycle.open_checklist(hired, ChecklistKind.OFFBOARDING)
    assert checklist is not None
    for task in lifecycle.open_required(checklist):
        lifecycle.tick(task, by=actor)
    event = _record(hired, actor, fired_reason)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.COMPLETED and checklist.event_id == event.pk


def test_optional_task_open_does_not_block(hired: Employee, actor: User, fired_reason: FiredReason) -> None:
    from checklists.services import gate, lifecycle

    gate.prepare(hired, reason=str(fired_reason.pk), anchor_day=date.today(), by=actor)
    checklist = lifecycle.open_checklist(hired, ChecklistKind.OFFBOARDING)
    assert checklist is not None
    for task in lifecycle.open_required(checklist):
        lifecycle.tick(task, by=actor)
    assert checklist.tasks.filter(required=False, done_at__isnull=True).exists()
    _record(hired, actor, fired_reason)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.COMPLETED


def test_override_needs_right_and_reason_and_is_logged(
    client: Client, hired: Employee, fired_reason: FiredReason
) -> None:
    admin = _login(client, "Admin", "adm1")
    assert client.post(_url(hired), _data(fired_reason, offboarding_override="")).status_code == 200
    assert not Event.objects.filter(type="termination").exists()
    assert client.post(_url(hired), _data(fired_reason, offboarding_override="Яаралтай")).status_code == 204
    assert Event.objects.filter(type="termination").count() == 1
    assert ActivityEntry.objects.filter(employee=hired, by=admin, message__contains="Яаралтай").exists()
    checklist = Checklist.objects.get(employee=hired)
    assert checklist.event_id is not None
    assert checklist.state == ChecklistState.OPEN  # the override leaves open tasks open (spec)
    assert lifecycle.open_required(checklist)


def test_override_without_right_is_refused(hired: Employee, actor: User, fired_reason: FiredReason) -> None:
    from checklists.services import gate

    gate.prepare(hired, reason=str(fired_reason.pk), anchor_day=date.today(), by=actor)
    with pytest.raises(events.EventError):
        _record(hired, actor, fired_reason, offboarding_override="Яаралтай")
    assert not Event.objects.filter(type="termination").exists()


def test_override_field_hidden_without_right(client: Client, hired: Employee) -> None:
    _login(client, "HR", "hr1")
    assert "offboarding_override" not in client.get(_url(hired)).content.decode()
    _login(client, "Admin", "adm1")
    assert "offboarding_override" in client.get(_url(hired)).content.decode()


def test_override_keeps_tasks_in_owner_list_then_last_tick_completes(
    client: Client, hired: Employee, fired_reason: FiredReason
) -> None:
    from checklists.services import owners

    admin = _login(client, "Admin", "adm1")
    assert client.post(_url(hired), _data(fired_reason, offboarding_override="Яаралтай")).status_code == 204
    assert owners.my_tasks(admin, timezone.localdate())  # admin fallback tasks are still waiting
    checklist = Checklist.objects.get(employee=hired)
    for task in lifecycle.open_required(checklist):
        lifecycle.tick(task, by=admin)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.COMPLETED


def test_signed_order_path_refused_then_waiting_and_completed(
    hired: Employee, actor: User, fired_reason: FiredReason
) -> None:
    from employees.models import CompanySettings

    from checklists.services import gate

    CompanySettings.objects.update_or_create(pk=1, defaults={"order_fired": True})
    day = timezone.localdate() + timedelta(days=30)
    gate.prepare(hired, reason=str(fired_reason.pk), anchor_day=day, by=actor)
    with pytest.raises(events.EventError):
        _record(hired, actor, fired_reason)
    assert not Event.objects.filter(type="termination").exists()
    checklist = lifecycle.open_checklist(hired, ChecklistKind.OFFBOARDING)
    assert checklist is not None
    for task in lifecycle.open_required(checklist):
        lifecycle.tick(task, by=actor)
    event = _record(hired, actor, fired_reason)
    assert event.applied_at is None  # waits for its signed order
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.COMPLETED and checklist.event_id == event.pk


def test_orphan_task_blocked_message_names_admin(hired: Employee, actor: User, fired_reason: FiredReason) -> None:
    from checklists.models import ChecklistTask
    from checklists.services import gate

    gate.prepare(hired, reason=str(fired_reason.pk), anchor_day=date.today(), by=actor)
    checklist = lifecycle.open_checklist(hired, ChecklistKind.OFFBOARDING)
    assert checklist is not None
    ChecklistTask.objects.filter(checklist=checklist, required=True).update(group=None, manager=False)
    with pytest.raises(events.EventError) as exc:
        _record(hired, actor, fired_reason)
    text = str(exc.value.errors)
    assert "Админ (эзэн олдсонгүй)" in text and "Шууд удирдлага" not in text


def test_invalid_form_does_not_start_checklist(client: Client, hired: Employee, fired_reason: FiredReason) -> None:
    _login(client, "HR", "hr1")
    response = client.post(_url(hired), {"effective": "", "fired_reason": fired_reason.pk, "note": ""})
    assert response.status_code == 200
    assert not Checklist.objects.exists()
