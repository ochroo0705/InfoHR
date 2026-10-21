"""Plain (non-dated) edits and notes, each logged (spec §4)."""

from typing import Any

from accounts.models import User
from django.db import transaction
from django.db.models import Model
from lists.models import MONGOLIA, MeaningfulEntry

from employees.models import (
    EXT_FIELDS,
    PERSONAL_FIELDS,
    ActivityEntry,
    ActivityKind,
    Employee,
    ensure_ext,
)
from employees.services import macs_writes
from employees.services.display import shown


def _diff_values(instance: Model, data: dict[str, Any]) -> list[dict[str, str]]:
    changes = []
    for field, new in data.items():
        model_field = instance._meta.get_field(field)
        old = getattr(instance, field)
        if old != new:
            label = str(model_field.verbose_name)  # type: ignore[union-attr]
            changes.append({"field": label, "old": shown(model_field, old), "new": shown(model_field, new)})
            setattr(instance, field, new)
    return changes


@transaction.atomic
def update_employee(employee: Employee, data: dict[str, Any], by: User) -> list[dict[str, str]]:
    ext = ensure_ext(employee)
    ext_data = {k: v for k, v in data.items() if k in EXT_FIELDS}
    column_data = {k: v for k, v in data.items() if k not in EXT_FIELDS}
    changes_by_kind: dict[bool, list[dict[str, str]]] = {True: [], False: []}
    column_changed = {k for k, v in column_data.items() if getattr(employee, k) != v}
    ext_changed = False
    for target, values in ((ext, ext_data), (employee, column_data)):
        for is_personal in (False, True):
            subset = {k: v for k, v in values.items() if (k in PERSONAL_FIELDS) == is_personal}
            found = _diff_values(target, subset)
            if target is ext and found:
                ext_changed = True
            changes_by_kind[is_personal] += found
    changed_columns = {k: getattr(employee, k) for k in column_changed}
    # Probation months (production test_month) follow the probation end and the start date, in this same write.
    # A MACS-only employee with no probation end keeps the production value (it was not set in HR).
    if ext.probation_end is not None or macs_writes.hr_employment_start(employee) is not None:
        months = macs_writes.probation_months(macs_writes.current_employment_start(employee), ext.probation_end)
        if months != employee.probation_months:
            employee.probation_months = months
            changed_columns["probation_months"] = months
    if "citizenship" in column_changed:
        mongolia = MeaningfulEntry.get(MONGOLIA)
        employee.foreign_emp = None if mongolia is None or employee.citizenship_id == mongolia else 1
        changed_columns["foreign_emp"] = employee.foreign_emp
    if changed_columns:
        macs_writes.update_employee_columns(employee, changed_columns)
    if ext_changed:
        ext.updated_by = by
        ext.save()
    for is_personal, message in ((False, "Мэдээлэл өөрчилсөн"), (True, "Хувийн мэдээлэл өөрчилсөн")):
        if changes_by_kind[is_personal]:
            ActivityEntry.objects.create(
                employee=employee,
                by=by,
                kind=ActivityKind.CHANGED,
                personal=is_personal,
                message=message,
                changes=changes_by_kind[is_personal],
            )
    return changes_by_kind[False] + changes_by_kind[True]


def birth_place_text(employee: Employee) -> str:
    """The birth place as one line: «Аймаг, Сум — тайлбар», or "" when none is recorded."""
    from macs.models import BirthPlace

    place = BirthPlace.objects.filter(employee=employee).select_related("city", "district").order_by("id").first()
    if place is None:
        return ""
    where = ", ".join(str(p) for p in (place.city, place.district) if p is not None)
    return f"{where} — {place.description}" if place.description else where


@transaction.atomic
def set_birth_place(employee: Employee, city: Any, district: Any, text: str, by: User) -> None:
    """Change the birth place (production birth_place) and log it as a personal change."""
    old = birth_place_text(employee)
    macs_writes.save_birth_place(employee, city, district, text)
    new = birth_place_text(employee)
    if old != new:
        ActivityEntry.objects.create(
            employee=employee,
            by=by,
            kind=ActivityKind.CHANGED,
            personal=True,
            message="Хувийн мэдээлэл өөрчилсөн",
            changes=[{"field": "Төрсөн газар", "old": old, "new": new}],
        )


SALARY_FIELDS = (
    "account_no",
    "bank",
    "social_insurance_no",
    "health_insurance_no",
    "insured_category",
    "taxpayer_no",
    "has_disability",
)


@transaction.atomic
def update_salary_insurance(employee: Employee, data: dict[str, Any], by: User) -> list[dict[str, str]]:
    """Salary and insurance edits. All of them are production columns on Employee, written through
    macs_writes and logged as one sensitive entry."""
    changes: list[dict[str, str]] = []
    columns: dict[str, Any] = {}
    for name in SALARY_FIELDS:
        if name not in data:
            continue
        new = data[name]
        old = getattr(employee, name)
        if (old or None) != (new or None):
            field = Employee._meta.get_field(name)
            label = str(field.verbose_name)  # type: ignore[union-attr]
            changes.append({"field": label, "old": shown(field, old), "new": shown(field, new)})
            columns[name] = new
    if columns:
        macs_writes.update_employee_columns(employee, columns)
    if changes:
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


@transaction.atomic
def set_photo(employee: Employee, jpeg: bytes | None, *, by: User) -> None:
    """Replace the photo (jpeg bytes) or remove it (None), and log it like other changes.

    Nothing is logged when there is no photo to remove.
    """
    from macs.models import EmployeePhoto

    had_photo = EmployeePhoto.objects.filter(employee=employee).exists()
    if jpeg is None and not had_photo:
        return
    macs_writes.save_photo(employee, jpeg)
    message = "Зураг өөрчилсөн" if jpeg else "Зураг устгасан"
    ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.CHANGED, message=message)
