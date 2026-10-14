"""Plain (non-dated) edits and notes, each logged (spec §4)."""

from typing import Any

from accounts.models import User
from django.db import transaction
from django.db.models import FileField, Model

from employees.models import PERSONAL_FIELDS, ActivityEntry, ActivityKind, Employee, SalaryInsurance


def _diff(instance: Model, data: dict[str, Any]) -> list[dict[str, str]]:
    changes = []
    for field, new in data.items():
        model_field = instance._meta.get_field(field)
        old = getattr(instance, field)
        if isinstance(model_field, FileField):
            # A ticked "clear" box arrives as False; an upload as a File. Compare/log by file name.
            new = new or None
            old_name, new_name = (old.name if old else ""), (new.name if new else "")
            if old_name != new_name or new is not None:
                changes.append({"field": str(model_field.verbose_name), "old": old_name, "new": new_name})
                model_field.save_form_data(instance, new if new is not None else False)
            continue
        if old != new:
            label = str(model_field.verbose_name)  # type: ignore[union-attr]
            changes.append(
                {"field": label, "old": "" if old is None else str(old), "new": "" if new is None else str(new)}
            )
            setattr(instance, field, new)
    return changes


@transaction.atomic
def update_employee(employee: Employee, data: dict[str, Any], by: User) -> list[dict[str, str]]:
    personal = _diff(employee, {k: v for k, v in data.items() if k in PERSONAL_FIELDS})
    work = _diff(employee, {k: v for k, v in data.items() if k not in PERSONAL_FIELDS})
    if work or personal:
        employee.updated_by = by
        employee.save()
    for changes, is_personal, message in (
        (work, False, "Мэдээлэл өөрчилсөн"),
        (personal, True, "Хувийн мэдээлэл өөрчилсөн"),
    ):
        if changes:
            ActivityEntry.objects.create(
                employee=employee,
                by=by,
                kind=ActivityKind.CHANGED,
                personal=is_personal,
                message=message,
                changes=changes,
            )
    return work + personal


@transaction.atomic
def update_salary_insurance(employee: Employee, data: dict[str, Any], by: User) -> list[dict[str, str]]:
    details, _ = SalaryInsurance.objects.get_or_create(employee=employee)
    changes = _diff(details, data)
    if changes:
        details.save()
        ActivityEntry.objects.create(
            employee=employee,
            by=by,
            kind=ActivityKind.CHANGED,
            sensitive=True,
            message="Цалин, даатгалын мэдээлэл өөрчилсөн",
            changes=changes,
        )
    return changes


def add_note(employee: Employee, *, text: str, by: User) -> ActivityEntry:
    text = text.strip()
    if not text:
        raise ValueError("Note text is empty")
    return ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.NOTE, message=text)
