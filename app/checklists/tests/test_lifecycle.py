from datetime import date, timedelta

import pytest
from accounts.audit import ACTIONS, Category
from accounts.models import SystemLogEntry, User
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, Event
from macs.models import Employee, FiredReason

from checklists.models import (
    Checklist,
    ChecklistKind,
    ChecklistState,
    ChecklistTask,
    ChecklistTemplate,
    ChecklistTemplateTask,
)
from checklists.services import lifecycle
from checklists.services.lifecycle import ChecklistError

LAST_DAY = date(2026, 11, 30)
STARTER = "Ажлаас гарах (үндсэн)"


def _starter() -> ChecklistTemplate:
    return ChecklistTemplate.objects.get(kind=ChecklistKind.OFFBOARDING, is_default=True)


def _tasks(checklist: Checklist) -> list[ChecklistTask]:
    return list(checklist.tasks.order_by("position", "pk"))


@pytest.mark.django_db
def test_start_copies_template_tasks(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    assert checklist.state == ChecklistState.OPEN
    assert checklist.template_name == STARTER
    assert checklist.template == _starter()
    template_tasks = list(_starter().tasks.order_by("position", "pk"))
    tasks = _tasks(checklist)
    assert [t.title for t in tasks] == [t.title for t in template_tasks]
    assert [t.required for t in tasks] == [t.required for t in template_tasks]
    assert [t.due_on for t in tasks] == [LAST_DAY + timedelta(days=t.due_offset_days) for t in template_tasks]
    assert [(t.group_id, t.manager) for t in tasks] == [(t.group_id, t.manager) for t in template_tasks]


@pytest.mark.django_db
def test_start_returns_none_without_template(hired: Employee, actor: User) -> None:
    ChecklistTemplate.objects.filter(pk=_starter().pk).update(active=False)
    assert lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor) is None
    assert not Checklist.objects.filter(employee=hired).exists()


@pytest.mark.django_db
def test_start_uses_reason_template_before_default(hired: Employee, actor: User, fired_reason: FiredReason) -> None:
    reason_template = ChecklistTemplate.objects.create(
        kind=ChecklistKind.OFFBOARDING,
        name="Нас барсан",
        reasons=[str(fired_reason.pk)],
        active=True,
    )
    ChecklistTemplateTask.objects.create(
        template=reason_template, position=1, title="Зөвхөн энэ", manager=True, due_offset_days=0
    )
    checklist = lifecycle.start(
        hired, ChecklistKind.OFFBOARDING, reason=str(fired_reason.pk), anchor_day=LAST_DAY, by=actor
    )
    assert checklist is not None
    assert checklist.template == reason_template
    assert [t.title for t in _tasks(checklist)] == ["Зөвхөн энэ"]


@pytest.mark.django_db
def test_template_for_reason_then_default() -> None:
    # Same three lookups as the Firebird scenario test_template_for_reason_on_firebird.
    resigned = ChecklistTemplate.objects.create(
        kind=ChecklistKind.OFFBOARDING, name="Өөрөө гарсан", reasons=["resigned"], active=True
    )
    assert lifecycle.template_for("offboarding", "resigned") == resigned
    assert lifecycle.template_for("offboarding", "retired") == _starter()
    assert lifecycle.template_for("offboarding", None) == _starter()


@pytest.mark.django_db
def test_template_for_reason_takes_first_active_by_pk_and_ignores_inactive() -> None:
    first = ChecklistTemplate.objects.create(kind=ChecklistKind.OFFBOARDING, name="Нэг", reasons=["moved"], active=True)
    ChecklistTemplate.objects.create(kind=ChecklistKind.OFFBOARDING, name="Хоёр", reasons=["moved"], active=True)
    ChecklistTemplate.objects.create(kind=ChecklistKind.OFFBOARDING, name="Идэвхгүй", reasons=["retired"], active=False)
    # Two active templates list "moved": the lower pk wins. The inactive one lists "retired" and is never used.
    assert lifecycle.template_for("offboarding", "moved") == first
    assert lifecycle.template_for("offboarding", "retired") == _starter()


@pytest.mark.django_db
def test_start_again_moves_open_due_dates_keeps_done(hired: Employee, actor: User) -> None:
    first = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert first is not None
    done_task = _tasks(first)[1]
    lifecycle.tick(done_task, by=actor)
    done_task.refresh_from_db()
    done_due = done_task.due_on
    open_before = {t.pk: t.due_on for t in _tasks(first) if t.done_at is None}

    moved_day = LAST_DAY + timedelta(days=5)
    second = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=moved_day, by=actor)

    assert second is not None and second.pk == first.pk
    first.refresh_from_db()
    assert first.anchor_day == moved_day
    assert ChecklistTask.objects.get(pk=done_task.pk).due_on == done_due
    for task in _tasks(first):
        if task.pk in open_before:
            assert task.due_on == open_before[task.pk] + timedelta(days=5)


@pytest.mark.django_db
def test_template_edit_does_not_change_running_checklist(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    before = [(t.title, t.due_on, t.required) for t in _tasks(checklist)]

    template_task = _starter().tasks.order_by("position").first()
    assert template_task is not None
    template_task.title = "Өөрчлөгдсөн гарчиг"
    template_task.due_offset_days = 40
    template_task.save()
    _starter().tasks.exclude(pk=template_task.pk).delete()

    assert [(t.title, t.due_on, t.required) for t in _tasks(checklist)] == before


@pytest.mark.django_db
def test_tick_untick_log_entries(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    task = _tasks(checklist)[0]
    entries_before = ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CHANGED).count()
    audit_before = SystemLogEntry.objects.filter(action="checklist_task_ticked").count()

    ticked = lifecycle.tick(task, by=actor)
    assert ticked.done_at is not None and ticked.done_by == actor
    assert ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CHANGED).count() == entries_before + 1
    assert SystemLogEntry.objects.filter(action="checklist_task_ticked").count() == audit_before + 1

    unticked = lifecycle.untick(ticked, by=actor)
    assert unticked.done_at is None and unticked.done_by is None
    assert ActivityEntry.objects.filter(employee=hired, kind=ActivityKind.CHANGED).count() == entries_before + 2
    assert SystemLogEntry.objects.filter(action="checklist_task_unticked").count() == 1


@pytest.mark.django_db
def test_untick_refused_after_event(hired: Employee, actor: User, termination: Event) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    task = _tasks(checklist)[0]
    lifecycle.tick(task, by=actor)
    lifecycle.complete_for_event(hired, termination)

    with pytest.raises(ChecklistError) as exc:
        lifecycle.untick(ChecklistTask.objects.get(pk=task.pk), by=actor)
    assert exc.value.message
    assert ChecklistTask.objects.get(pk=task.pk).done_at is not None


@pytest.mark.django_db
def test_open_required_lists_open_required_tasks(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    required = [t for t in _tasks(checklist) if t.required]
    lifecycle.tick(required[0], by=actor)
    open_titles = [t.title for t in lifecycle.open_required(checklist)]
    assert open_titles == [t.title for t in required[1:]]


@pytest.mark.django_db
def test_complete_for_event_marks_checklist_and_is_noop_without_one(
    hired: Employee, actor: User, termination: Event
) -> None:
    lifecycle.complete_for_event(hired, termination)  # no checklist yet: nothing happens
    assert not Checklist.objects.filter(employee=hired).exists()

    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    for task in lifecycle.open_required(checklist):
        lifecycle.tick(task, by=actor)
    lifecycle.complete_for_event(hired, termination)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.COMPLETED
    assert checklist.event == termination
    assert checklist.completed_at is not None


@pytest.mark.django_db
def test_complete_for_event_with_open_required_tasks_links_event_but_stays_open(
    hired: Employee, actor: User, termination: Event
) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    lifecycle.complete_for_event(hired, termination)  # an override: required tasks are still open
    checklist.refresh_from_db()
    assert checklist.event == termination
    assert checklist.state == ChecklistState.OPEN
    assert checklist.completed_at is None
    # Owners can go on ticking; the last required tick completes it.
    for task in lifecycle.open_required(checklist):
        lifecycle.tick(task, by=actor)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.COMPLETED
    assert checklist.completed_at is not None


@pytest.mark.django_db
def test_untick_still_refused_while_event_linked_and_open(hired: Employee, actor: User, termination: Event) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    task = lifecycle.open_required(checklist)[0]
    lifecycle.tick(task, by=actor)
    lifecycle.complete_for_event(hired, termination)
    with pytest.raises(ChecklistError):
        lifecycle.untick(ChecklistTask.objects.get(pk=task.pk), by=actor)


@pytest.mark.django_db
def test_cancel_closes_open_checklist_without_event_and_logs(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    before = ActivityEntry.objects.filter(employee=hired).count()
    lifecycle.cancel(checklist, by=actor)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.CANCELLED
    assert ActivityEntry.objects.filter(employee=hired).count() == before + 1
    assert SystemLogEntry.objects.filter(action="checklist_cancelled").count() == 1
    assert lifecycle.open_checklist(hired, ChecklistKind.OFFBOARDING) is None
    # A new one can start again: the one-open-per-employee rule still holds.
    again = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert again is not None and again.pk != checklist.pk
    assert Checklist.objects.filter(employee=hired, state=ChecklistState.OPEN).count() == 1


@pytest.mark.django_db
def test_cancel_refused_with_event_or_not_open(hired: Employee, actor: User, termination: Event) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    lifecycle.complete_for_event(hired, termination)  # open, but linked to an event
    with pytest.raises(ChecklistError):
        lifecycle.cancel(checklist, by=actor)
    Checklist.objects.filter(pk=checklist.pk).update(event=None, state=ChecklistState.COMPLETED)
    checklist.refresh_from_db()
    with pytest.raises(ChecklistError):
        lifecycle.cancel(checklist, by=actor)
    assert Checklist.objects.get(pk=checklist.pk).state == ChecklistState.COMPLETED


@pytest.mark.django_db
def test_tick_on_cancelled_checklist_is_refused(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    lifecycle.cancel(checklist, by=actor)
    first = checklist.tasks.first()
    assert first is not None
    with pytest.raises(ChecklistError):
        lifecycle.tick(first, by=actor)


@pytest.mark.django_db
def test_untick_reopens_completed_checklist_without_event(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    task = _tasks(checklist)[0]
    lifecycle.tick(task, by=actor)
    # Completed without an event (not the normal flow): the reopen path is the only way to get here.
    Checklist.objects.filter(pk=checklist.pk).update(state=ChecklistState.COMPLETED, completed_at=timezone.now())

    lifecycle.untick(ChecklistTask.objects.get(pk=task.pk), by=actor)

    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN
    assert checklist.completed_at is None
    assert ChecklistTask.objects.get(pk=task.pk).done_at is None


@pytest.mark.django_db
def test_untick_refused_when_a_newer_open_checklist_exists(hired: Employee, actor: User) -> None:
    first = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert first is not None
    task = _tasks(first)[0]
    lifecycle.tick(task, by=actor)
    Checklist.objects.filter(pk=first.pk).update(state=ChecklistState.COMPLETED, completed_at=timezone.now())
    newer = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert newer is not None and newer.pk != first.pk

    with pytest.raises(ChecklistError) as exc:
        lifecycle.untick(ChecklistTask.objects.get(pk=task.pk), by=actor)

    assert exc.value.message
    # Rolled back as a whole: the tick stands, the old checklist stays completed, the new one stays open.
    assert ChecklistTask.objects.get(pk=task.pk).done_at is not None
    assert Checklist.objects.get(pk=first.pk).state == ChecklistState.COMPLETED
    assert Checklist.objects.get(pk=newer.pk).state == ChecklistState.OPEN


@pytest.mark.django_db
def test_checklist_audit_lines_use_hr_category_and_labels(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    ticked = lifecycle.tick(_tasks(checklist)[0], by=actor)
    lifecycle.untick(ticked, by=actor)

    for action in ("checklist_started", "checklist_task_ticked", "checklist_task_unticked"):
        entry = SystemLogEntry.objects.filter(action=action).latest("pk")
        assert entry.category == Category.HR
        assert ACTIONS[action]


def _start_onboarding(employee: Employee, actor: User, day: date = date(2026, 1, 5)) -> Checklist:
    checklist = lifecycle.start(employee, ChecklistKind.ONBOARDING, reason=None, anchor_day=day, by=actor)
    assert checklist is not None
    return checklist


@pytest.mark.django_db
def test_onboarding_completes_on_last_required_tick(hired: Employee, actor: User) -> None:
    checklist = _start_onboarding(hired, actor)
    required = [t for t in _tasks(checklist) if t.required]
    assert required
    for task in required[:-1]:
        lifecycle.tick(task, by=actor)
        assert Checklist.objects.get(pk=checklist.pk).state == ChecklistState.OPEN
    lifecycle.tick(required[-1], by=actor)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.COMPLETED
    assert checklist.completed_at is not None
    assert checklist.event_id is None


@pytest.mark.django_db
def test_onboarding_completes_with_optional_tasks_left_open(hired: Employee, actor: User) -> None:
    checklist = _start_onboarding(hired, actor)
    ChecklistTask.objects.filter(checklist=checklist).update(required=False)
    first = _tasks(checklist)[0]
    ChecklistTask.objects.filter(pk=first.pk).update(required=True)
    lifecycle.tick(ChecklistTask.objects.get(pk=first.pk), by=actor)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.COMPLETED
    assert checklist.tasks.filter(done_at__isnull=True).exists()


@pytest.mark.django_db
def test_onboarding_untick_reopens_completed(hired: Employee, actor: User) -> None:
    checklist = _start_onboarding(hired, actor)
    tasks = _tasks(checklist)
    ChecklistTask.objects.filter(checklist=checklist).update(required=False)
    ChecklistTask.objects.filter(pk=tasks[0].pk).update(required=True)
    lifecycle.tick(ChecklistTask.objects.get(pk=tasks[0].pk), by=actor)
    assert Checklist.objects.get(pk=checklist.pk).state == ChecklistState.COMPLETED
    lifecycle.untick(ChecklistTask.objects.get(pk=tasks[0].pk), by=actor)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN
    assert checklist.completed_at is None


@pytest.mark.django_db
def test_onboarding_untick_refused_when_newer_open_exists(hired: Employee, actor: User) -> None:
    first = _start_onboarding(hired, actor)
    tasks = _tasks(first)
    ChecklistTask.objects.filter(checklist=first).update(required=False)
    ChecklistTask.objects.filter(pk=tasks[0].pk).update(required=True)
    lifecycle.tick(ChecklistTask.objects.get(pk=tasks[0].pk), by=actor)
    newer = _start_onboarding(hired, actor, date(2027, 1, 4))
    assert newer.pk != first.pk
    with pytest.raises(ChecklistError):
        lifecycle.untick(ChecklistTask.objects.get(pk=tasks[0].pk), by=actor)
    assert Checklist.objects.get(pk=first.pk).state == ChecklistState.COMPLETED
    assert ChecklistTask.objects.get(pk=tasks[0].pk).done_at is not None


@pytest.mark.django_db
def test_offboarding_stays_open_when_everything_ticked_without_event(hired: Employee, actor: User) -> None:
    checklist = lifecycle.start(hired, ChecklistKind.OFFBOARDING, reason=None, anchor_day=LAST_DAY, by=actor)
    assert checklist is not None
    for task in _tasks(checklist):
        lifecycle.tick(task, by=actor)
    checklist.refresh_from_db()
    assert checklist.state == ChecklistState.OPEN
    assert checklist.completed_at is None


@pytest.mark.django_db
def test_rehire_after_completed_onboarding_makes_new_checklist_and_open_one_is_reused(
    hired: Employee, actor: User
) -> None:
    first = _start_onboarding(hired, actor)
    reused = _start_onboarding(hired, actor)
    assert reused.pk == first.pk
    Checklist.objects.filter(pk=first.pk).update(state=ChecklistState.COMPLETED, completed_at=timezone.now())
    second = _start_onboarding(hired, actor, date(2027, 3, 1))
    assert second.pk != first.pk
    assert second.state == ChecklistState.OPEN
    assert Checklist.objects.filter(employee=hired, kind=ChecklistKind.ONBOARDING).count() == 2
