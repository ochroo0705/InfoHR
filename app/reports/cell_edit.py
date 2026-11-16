"""Inline edit of one employee field from a report cell (decision D-080, phase 2).

The save follows the employee page section save (employees.views.personal_section): the same form, the same
section helpers, the same stale check and the same write, so an edit from a report logs the same activity entry.
"""

import logging
from dataclasses import dataclass
from typing import Any

from accounts.models import User
from django import forms
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, DataError, IntegrityError, transaction
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from employees import access, sections, stale
from employees.forms import EmployeeForm, SalaryInsuranceForm
from employees.models import EXT_FIELDS, Employee, EmployeeExt, ext_of
from employees.models import PERSONAL_FIELDS as MODEL_PERSONAL_FIELDS
from employees.services import records
from employees.services.display import shown

logger = logging.getLogger(__name__)

EDITABLE = (
    "family_name",
    "given_name",
    "clan_name",
    "register_no",
    "birth_date",
    "gender",
    "work_phone",
    "private_phone",
    "phone2",
    "email",
    "citizenship",
    "nationality",
    "passport_no",
    "marital_status",
    "social_origin",
    "blood_type",
    "blood_rh",
    "military_service",
    "housing_condition",
    "living_standard",
    "car_ownership",
    "clothing_size",
    "shoe_size",
    "elected_position",
    "education_level",
    "academic_degree",
)
# Salary and insurance columns (D-080 phase 2b): the Employee fields of SalaryInsuranceForm. They need the salary right
# (can_manage_salary) instead of the employee-management right, so an accountant can correct them from a report.
SALARY_EDITABLE = (
    "account_no",
    "bank",
    "social_insurance_no",
    "health_insurance_no",
    "insured_category",
    "taxpayer_no",
)
# Every personal field: the model's list (it has `nationality`, which no personal section shows) plus the sections'
# fields (the education fields are on the personal tab but not in the model's list). A field missing here is editable
# without can_view_personal, so both sources are needed.
PERSONAL_FIELDS = frozenset(MODEL_PERSONAL_FIELDS) | frozenset(
    f for k in ("identity", "contact", "education", "other") for f in sections.SECTIONS[k]
)
CLASH = "Өөр хэрэглэгч энэ утгыг өөрчилсөн байна. Хуудсаа шинэчилнэ үү."


@dataclass
class CellResult:
    """Outcome of a cell save: `text` is the value as shown when ok, `error` the message to show otherwise."""

    ok: bool
    text: str = ""
    error: str = ""


def can_edit(user: User, employee: Employee, field: str) -> bool:
    """May this user change this field of this employee from a report: a manager who sees the employee, and for a
    personal field also the right to see personal data. A salary or insurance field needs the salary right
    (can_manage_salary) instead. Governed fields (job, salary amount, dates) are never editable here."""
    if field in SALARY_EDITABLE:
        allowed = access.can_manage_salary(user)
    else:
        allowed = field in EDITABLE and access.can_manage(user)
    if not allowed or not access.visible_employees(user).filter(pk=employee.pk).exists():
        return False
    return field not in PERSONAL_FIELDS or access.can_view_personal(user, employee)


def _shown_value(employee: Employee, field: str) -> str:
    """The stored value of a field as the activity log and the report show it."""
    if field in EXT_FIELDS:
        ext = ext_of(employee)
        return shown(EmployeeExt._meta.get_field(field), getattr(ext, field, None) if ext is not None else None)
    return shown(Employee._meta.get_field(field), getattr(employee, field))


def _first_error(form: forms.Form, field: str) -> str:
    """The first message for this field, else the first form-wide message."""
    errors = form.errors.get(field) or form.non_field_errors()
    return str(errors[0]) if errors else ""


def editor_form(
    user: User, employee: Employee, field: str, data: dict[str, Any] | QueryDict | None = None
) -> EmployeeForm | SalaryInsuranceForm:
    """The form of one field's editor: SalaryInsuranceForm for a SALARY_EDITABLE field, else the EmployeeForm. Used for
    the GET editor, the error re-render, the save and the bulk edit (to_posted), so all of them see the same form."""
    if field in SALARY_EDITABLE:
        return SalaryInsuranceForm(data, employee=employee)
    return EmployeeForm(data, employee=employee, user=user)


def posted_data(user: User, employee: Employee, field: str, post: QueryDict) -> dict[str, Any]:
    """The POST the field's form is validated with: every field at its stored value, overridden by the posted field and
    the stale-check keys (`loaded`, `resolve-*`). Salary fields use the salary form, the others the section helper."""
    if field not in SALARY_EDITABLE:
        return sections.section_data(EmployeeForm(employee=employee, user=user), post, (field,))
    blank = SalaryInsuranceForm(employee=employee)
    data: dict[str, Any] = {
        name: sections._as_posted(blank.get_initial_for_field(f, name)) for name, f in blank.fields.items()
    }
    data[field] = post.get(field, "")
    for key in post:
        if key == "loaded" or key.startswith("resolve-"):
            data[key] = post[key]
    return data


def _write(employee: Employee, field: str, changes: dict[str, Any], user: User) -> None:
    """The write of the changes: salary and insurance go through update_salary_insurance (one sensitive entry)."""
    if field in SALARY_EDITABLE:
        records.update_salary_insurance(employee, changes, user)
    else:
        records.update_employee(employee, changes, user)


def save(user: User, employee_pk: int, field: str, post: QueryDict, dry_run: bool = False) -> CellResult:
    """Validate and save one field the way the employee page section save does. Refuses with PermissionDenied when
    `can_edit` is False. Returns the new shown value, or the error to show in the cell editor.
    With `dry_run` the whole write runs and is then rolled back: the result is what a real save would return, and
    nothing (no value, no activity entry) stays written."""
    employee = get_object_or_404(access.visible_employees(user), pk=employee_pk)
    if not can_edit(user, employee, field):
        raise PermissionDenied
    from employees.views import DB_REFUSED  # local import: employees.views is large, and keeps reports importable first

    # Same flow as personal_section: fresh instance for the form, the visible one for the stale check and the write.
    stored = Employee.objects.get(pk=employee_pk)
    form = editor_form(user, stored, field, posted_data(user, stored, field, post))
    if isinstance(form, EmployeeForm):
        sections.only_section_required(form, (field,))
    if not form.is_valid():
        return CellResult(ok=False, error=_first_error(form, field))
    if isinstance(form, SalaryInsuranceForm):
        changes = stale.resolve(form, employee, {field: form.cleaned_data[field]})
    else:
        columns, ext = form.values()
        changes = stale.resolve(form, employee, {**columns, **ext})
    if getattr(form, "conflicts", None):
        return CellResult(ok=False, error=CLASH)
    text = ""
    try:
        with transaction.atomic():
            _write(employee, field, changes, user)
            text = _shown_value(Employee.objects.get(pk=employee_pk), field)
            if dry_run:
                transaction.set_rollback(True)
    except (IntegrityError, DataError) as exc:
        logger.warning("cell edit write refused: %s", exc)
        return CellResult(ok=False, error=DB_REFUSED)
    except DatabaseError as exc:  # the database is down or busy: the cell says so instead of the page failing
        logger.warning("cell edit write failed: %s", exc)
        return CellResult(ok=False, error=DB_REFUSED)
    return CellResult(ok=True, text=text)
