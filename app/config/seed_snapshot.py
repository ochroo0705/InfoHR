"""Plain-data snapshot of the state the seeds create, for the seeded apps.

Ids and row order are ignored, so two databases compare equal when they hold the same seeded state.
Every value is plain JSON data (strings, numbers, lists, dicts), so the snapshot can be written to the
golden file (app/infohr_firebird/tests/seed_golden.json) and compared with a snapshot taken on Firebird.
Used by the seed tests (PostgreSQL and Firebird).
"""

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Q

from config.seed_firebird import EMPLOYEE_CONTENT_TYPE

SEEDED_APPS = ("accounts", "lists", "leave", "recruitment", "reports", "employees", "checklists", "assistant")
RULE_FIELDS = (
    "effective_from",
    "base_days",
    "base_days_minor_or_disabled",
    "brackets",
    "min_continuous_part",
    "eligibility_months",
)


def _plain(value: Any) -> Any:
    """Turn a model value into JSON data: Decimal to a plain number string, date to ISO text."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")  # 15.00 and 15 both become "15"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def permission_scope() -> Q:
    """The permissions the seeds own: every permission of the seeded apps, plus the employee content type."""
    label, model = EMPLOYEE_CONTENT_TYPE
    return Q(content_type__app_label__in=SEEDED_APPS) | Q(content_type__app_label=label, content_type__model=model)


def _template_state(template: Any) -> dict[str, Any]:
    return {
        "is_default": template.is_default,
        "active": template.active,
        "reasons": _plain(template.reasons),
        "tasks": [
            {
                "position": task.position,
                "title": task.title,
                "group": task.group.name if task.group_id else None,
                "manager": task.manager,
                "due_offset_days": task.due_offset_days,
                "required": task.required,
            }
            for task in template.tasks.select_related("group").order_by("position", "pk")
        ],
    }


def snapshot_state() -> dict[str, Any]:
    from checklists.models import ChecklistTemplate
    from django.contrib.auth.models import Group, Permission
    from leave.models import AnnualLeaveRule

    groups = {
        group.name: sorted(
            f"{perm.content_type.app_label}.{perm.codename}"
            for perm in group.permissions.filter(permission_scope()).select_related("content_type")
        )
        for group in Group.objects.all()
    }
    permissions = {
        f"{perm.content_type.app_label}.{perm.codename}": perm.name
        for perm in Permission.objects.filter(permission_scope()).select_related("content_type")
    }
    annual_rules = {
        rule.effective_from.isoformat(): {field: _plain(getattr(rule, field)) for field in RULE_FIELDS}
        for rule in AnnualLeaveRule.objects.all()
    }
    templates = {
        f"{template.kind}:{template.name}": _template_state(template) for template in ChecklistTemplate.objects.all()
    }
    return {
        "groups": groups,
        "permissions": permissions,
        "annual_leave_rules": annual_rules,
        "checklist_templates": templates,
    }
