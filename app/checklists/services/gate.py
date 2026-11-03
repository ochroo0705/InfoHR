"""The offboarding gate used by `employees.services.events.record` for a termination.

The gate sits at recording time: with a template that applies, the termination is only recorded when every required
task is done (or an Admin overrides with a reason). A refused attempt still leaves the checklist started, because the
view calls `prepare` outside the record transaction.
"""

from datetime import date

from accounts.audit import Category, record_safe
from accounts.models import User
from employees.models import ActivityEntry, ActivityKind
from macs.models import Employee

from checklists.models import ChecklistKind, ChecklistTask
from checklists.services import lifecycle, owners

AUDIT_ACTION_OVERRIDE = "offboarding_override"
START_FIRST = "Эхлээд ажлаас гарах жагсаалтыг эхлүүлнэ үү."


class GateBlocked(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def prepare(employee: Employee, *, reason: str | None, anchor_day: date, by: User) -> None:
    """Start (or move) the offboarding checklist before the termination is attempted."""
    lifecycle.start(employee, ChecklistKind.OFFBOARDING, reason=reason, anchor_day=anchor_day, by=by)


def check(employee: Employee, *, reason: str | None, override_reason: str, by: User) -> None:
    if lifecycle.template_for(ChecklistKind.OFFBOARDING, reason) is None:
        return
    checklist = lifecycle.open_checklist(employee, ChecklistKind.OFFBOARDING)
    if checklist is None:
        raise GateBlocked(START_FIRST)
    open_tasks = lifecycle.open_required(checklist)
    if not open_tasks:
        return
    override_reason = override_reason.strip()
    if override_reason and by.has_perm("checklists.override_offboarding"):
        titles = "; ".join(task.title for task in open_tasks)
        ActivityEntry.objects.create(
            employee=employee,
            by=by,
            kind=ActivityKind.CHANGED,
            message=f"Ажлаас гарах жагсаалтыг алгассан ({titles}) — {override_reason}",
        )
        record_safe(
            Category.HR,
            AUDIT_ACTION_OVERRIDE,
            actor=by,
            message=f"{employee.code or employee.pk} · {titles} — {override_reason}",
            target_type="checklist",
            target_label=checklist.template_name,
        )
        return
    labels = _owner_labels(open_tasks)
    lines = "; ".join(f"{task.title} — {labels[task.pk]}" for task in open_tasks)
    raise GateBlocked(f"Ажлаас гарах жагсаалт дуусаагүй байна: {lines}.")


def _owner_labels(tasks: list[ChecklistTask]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for task in tasks:
        if task.group is not None:
            labels[task.pk] = task.group.name
        elif task.manager:
            labels[task.pk] = owners.RULE_LABELS[owners.RULE_MANAGER]
        else:  # the role was deleted: the task falls to Admin
            labels[task.pk] = owners.ADMIN_FALLBACK_LABEL
    return labels
