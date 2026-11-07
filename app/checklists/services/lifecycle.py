"""Start, tick and untick checklists. No permission checks here: the callers (views, the gate) check.

A started checklist copies its tasks from the template, so a later template edit never changes it. Every tick and
start is written to the employee's activity chatter and to the system log.
"""

from datetime import date, timedelta

from accounts.audit import Category, record_safe
from accounts.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, Event
from macs.models import Employee

from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask, ChecklistTemplate

AUDIT_ACTION_STARTED = "checklist_started"
AUDIT_ACTION_TICKED = "checklist_task_ticked"
AUDIT_ACTION_UNTICKED = "checklist_task_unticked"
AUDIT_ACTION_CANCELLED = "checklist_cancelled"


# What the anchor day is called in the log, per kind.
_ANCHOR_LABEL: dict[str, str] = {
    ChecklistKind.OFFBOARDING.value: "сүүлийн ажлын өдөр",
    ChecklistKind.ONBOARDING.value: "ажилд орох өдөр",
}


class ChecklistError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def template_for(kind: str, reason: str | None) -> ChecklistTemplate | None:
    """The active template of `kind` that lists `reason`, else the active default of that kind, else None.

    The reasons are checked in Python, in pk order: there are only a few templates per kind, and a JSON contains
    lookup is not portable (Firebird has none).
    """
    if reason:
        for template in ChecklistTemplate.objects.filter(kind=kind, active=True).order_by("pk"):
            if reason in (template.reasons or []):
                return template
    return ChecklistTemplate.objects.filter(kind=kind, active=True, is_default=True).first()


def open_checklist(employee: Employee, kind: str) -> Checklist | None:
    return Checklist.objects.filter(employee=employee, kind=kind, state=ChecklistState.OPEN).first()


def start(employee: Employee, kind: str, *, reason: str | None, anchor_day: date, by: User) -> Checklist | None:
    """Start a checklist for `employee`, or return the open one.

    An open checklist is returned at once: its anchor day moves to `anchor_day`, and the due dates of its tasks that are
    not done move by the same number of days (done tasks keep theirs). Otherwise None when no template applies;
    else the tasks are copied from the template.
    """
    existing = open_checklist(employee, kind)
    if existing is not None:
        if existing.anchor_day != anchor_day:
            _move_anchor_day(existing, anchor_day, by=by)
        return existing

    template = template_for(kind, reason)
    if template is None:
        return None
    try:
        with transaction.atomic():
            checklist = Checklist.objects.create(
                employee=employee,
                kind=kind,
                template=template,
                template_name=template.name,
                anchor_day=anchor_day,
                created_by=by,
            )
            ChecklistTask.objects.bulk_create(
                [
                    ChecklistTask(
                        checklist=checklist,
                        position=task.position,
                        title=task.title,
                        group=task.group,
                        manager=task.manager,
                        due_on=anchor_day + timedelta(days=task.due_offset_days),
                        required=task.required,
                    )
                    for task in template.tasks.all()
                ]
            )
            ActivityEntry.objects.create(
                employee=employee,
                by=by,
                kind=ActivityKind.ADDED,
                message=(
                    f"{ChecklistKind(kind).label} жагсаалт эхэллээ: {template.name} "
                    f"· {_ANCHOR_LABEL[kind]} {anchor_day:%Y-%m-%d}"
                ),
            )
            record_safe(
                Category.HR,
                AUDIT_ACTION_STARTED,
                actor=by,
                message=f"{template.name} · {_employee_code(employee)}",
                target_type="checklist",
                target_label=template.name,
            )
    except IntegrityError:
        # Another request started the same checklist at the same moment: the open one is the answer.
        return open_checklist(employee, kind)
    return checklist


def _move_anchor_day(checklist: Checklist, anchor_day: date, *, by: User) -> None:
    with transaction.atomic():
        checklist = Checklist.objects.select_for_update().get(pk=checklist.pk)
        shift = anchor_day - checklist.anchor_day
        for task in checklist.tasks.filter(done_at__isnull=True):
            task.due_on = task.due_on + shift
            task.save(update_fields=["due_on"])
        old_day = checklist.anchor_day
        checklist.anchor_day = anchor_day
        checklist.save(update_fields=["anchor_day"])
        ActivityEntry.objects.create(
            employee=checklist.employee,
            by=by,
            kind=ActivityKind.CHANGED,
            message=(
                f"{_ANCHOR_LABEL[checklist.kind].capitalize()} өөрчлөгдлөө: {old_day:%Y-%m-%d} → {anchor_day:%Y-%m-%d}"
            ),
        )


def tick(task: ChecklistTask, *, by: User) -> ChecklistTask:
    """Mark `task` done. A task already done is returned unchanged and nothing is logged."""
    with transaction.atomic():
        # One table per locking statement: Firebird refuses FOR UPDATE on a join. The checklist row is locked too.
        task = ChecklistTask.objects.select_for_update().get(pk=task.pk)
        task.checklist = Checklist.objects.select_for_update().get(pk=task.checklist_id)
        if task.done_at is not None:
            return task
        if task.checklist.state != ChecklistState.OPEN:
            raise ChecklistError("Жагсаалт аль хэдийн дууссан байна.")
        task.done_at = timezone.now()
        task.done_by = by
        task.save(update_fields=["done_at", "done_by"])
        _log_task(task, by, "Даалгавар биелсэн", AUDIT_ACTION_TICKED)
        checklist = task.checklist
        # Onboarding is never linked to an event: the last required tick finishes it. Offboarding finishes only once
        # the termination is linked (after an override, the last required tick then finishes it).
        finishes_alone = checklist.kind == ChecklistKind.ONBOARDING and checklist.event_id is None
        if (checklist.event_id is not None or finishes_alone) and not open_required(checklist):
            checklist.state = ChecklistState.COMPLETED
            checklist.completed_at = timezone.now()
            checklist.save(update_fields=["state", "completed_at"])
    return task


def untick(task: ChecklistTask, *, by: User) -> ChecklistTask:
    """Undo a tick. Refused once the checklist was used for a termination (its event is set).

    A completed checklist without an event (a finished onboarding one) is reopened.
    """
    with transaction.atomic():
        task = ChecklistTask.objects.select_for_update().get(pk=task.pk)
        checklist = Checklist.objects.select_for_update().get(pk=task.checklist_id)
        if checklist.event_id is not None:
            raise ChecklistError("Ажлаас гаргасан жагсаалтын даалгаврыг буцаах боломжгүй.")
        if task.done_at is None:
            return task
        task.done_at = None
        task.done_by = None
        task.save(update_fields=["done_at", "done_by"])
        if checklist.state == ChecklistState.COMPLETED:
            try:
                # Nested atomic: the IntegrityError rolls back only this save, then the outer block is rolled back too.
                with transaction.atomic():
                    checklist.state = ChecklistState.OPEN
                    checklist.completed_at = None
                    checklist.save(update_fields=["state", "completed_at"])
            except IntegrityError:
                # A newer open checklist of this kind exists: two open ones are not allowed.
                raise ChecklistError(
                    "Энэ ажилтанд шинэ нээлттэй жагсаалт байгаа тул энэ даалгаврын биелэлтийг буцаах боломжгүй."
                ) from None
        _log_task(task, by, "Даалгаврын биелэлтийг буцаасан", AUDIT_ACTION_UNTICKED)
    return task


def open_required(checklist: Checklist) -> list[ChecklistTask]:
    """Required tasks of `checklist` that are not done yet, in order."""
    return list(checklist.tasks.filter(required=True, done_at__isnull=True))


def complete_for_event(employee: Employee, event: Event) -> None:
    """Link the employee's open offboarding checklist to `event`. Does nothing when there is none.

    The checklist is completed only when no required task is open. After an override it stays open, so owners can
    still tick (for example closing access once the leaver is gone); the last required tick then completes it.
    """
    checklist = open_checklist(employee, ChecklistKind.OFFBOARDING)
    if checklist is None:
        return
    checklist.event = event
    fields = ["event"]
    if not open_required(checklist):
        checklist.state = ChecklistState.COMPLETED
        checklist.completed_at = timezone.now()
        fields += ["state", "completed_at"]
    checklist.save(update_fields=fields)


def cancel(checklist: Checklist, *, by: User) -> Checklist:
    """Close an open checklist that no termination used (for example one started by a refused attempt).

    Refused when it is not open or already linked to an event. A new checklist can start afterwards.
    """
    with transaction.atomic():
        checklist = Checklist.objects.select_for_update().get(pk=checklist.pk)
        if checklist.state != ChecklistState.OPEN:
            raise ChecklistError("Жагсаалт нээлттэй биш байна.")
        if checklist.event_id is not None:
            raise ChecklistError("Ажлаас гаргасан жагсаалтыг цуцлах боломжгүй.")
        checklist.state = ChecklistState.CANCELLED
        checklist.save(update_fields=["state"])
        ActivityEntry.objects.create(
            employee=checklist.employee,
            by=by,
            kind=ActivityKind.CHANGED,
            message=f"{ChecklistKind(checklist.kind).label} жагсаалтыг цуцалсан: {checklist.template_name}",
        )
        record_safe(
            Category.HR,
            AUDIT_ACTION_CANCELLED,
            actor=by,
            message=f"{checklist.template_name} · {_employee_code(checklist.employee)}",
            target_type="checklist",
            target_label=checklist.template_name,
        )
    return checklist


def cancel_open(
    employee: Employee, kind: str, *, by: User, reason: str, anchor_day: date | None = None
) -> Checklist | None:
    """Cancel the employee's open checklist of `kind`, logged like `cancel` with the reason added. Returns it, or None
    when there is none (or, with `anchor_day`, when the open one is anchored on another day). An open checklist that
    is linked to an event is left alone."""
    with transaction.atomic():
        checklist = (
            Checklist.objects.select_for_update()
            .filter(employee=employee, kind=kind, state=ChecklistState.OPEN, event__isnull=True)
            .first()
        )
        if checklist is None or (anchor_day is not None and checklist.anchor_day != anchor_day):
            return None
        checklist.state = ChecklistState.CANCELLED
        checklist.save(update_fields=["state"])
        ActivityEntry.objects.create(
            employee=checklist.employee,
            by=by,
            kind=ActivityKind.CHANGED,
            message=f"{ChecklistKind(kind).label} жагсаалтыг цуцалсан: {checklist.template_name} — {reason}",
        )
        record_safe(
            Category.HR,
            AUDIT_ACTION_CANCELLED,
            actor=by,
            message=f"{checklist.template_name} · {_employee_code(checklist.employee)} · {reason}",
            target_type="checklist",
            target_label=checklist.template_name,
        )
    return checklist


def _log_task(task: ChecklistTask, by: User, text: str, audit_action: str) -> None:
    employee = task.checklist.employee
    ActivityEntry.objects.create(
        employee=employee,
        by=by,
        kind=ActivityKind.CHANGED,
        message=f"{text}: {task.title}",
    )
    record_safe(
        Category.HR,
        audit_action,
        actor=by,
        message=f"{task.title} · {_employee_code(employee)}",
        target_type="checklist_task",
        target_label=task.title,
    )


def _employee_code(employee: Employee) -> str:
    return employee.code or str(employee.pk)
