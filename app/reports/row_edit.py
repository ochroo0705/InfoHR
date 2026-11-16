"""Inline edit of one row of a personal list from a report cell: the children (family) and emergency contacts report
(D-080 follow-up). The save follows the employee page's list-row save (employees.views.personal_edit): the row's form
(FORMS[kind]), the loaded values the editor carries (the form's loaded_* hidden fields, the stale check), the same
write (personal_writes.update) and the same activity entry.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import Http404
from employees import access
from employees.forms import FORMS, PersonalRowForm
from employees.models import Employee
from employees.services import personal_rows
from employees.services import personal_writes as pw

from reports.cell_edit import CellResult

# kind -> the row fields a report cell may edit (the others of the row stay as they are, and read-only in the report)
KINDS: dict[str, tuple[str, ...]] = {
    "family": ("given_name", "relation", "birth_date"),
    "contact": ("contact_type", "value", "name", "relative"),
}


def can_edit(user: User, employee: Employee) -> bool:
    """The employee page's list-row rule (employees.views._personal_access) as a boolean: the user manages employees
    and may see the personal data of this employee, and the employee is visible to the user."""
    return (
        access.can_manage(user)
        and access.can_view_personal(user, employee)
        and access.visible_employees(user).filter(pk=employee.pk).exists()
    )


def _guard(user: User, employee: Employee, kind: str, key: int, field: str) -> personal_rows.PersonalRow:
    """The row to edit. 404 for an unknown kind or field or a row that is not this employee's; 403 without rights."""
    if kind not in KINDS or field not in KINDS[kind]:
        raise Http404
    if not can_edit(user, employee):
        raise PermissionDenied
    row = personal_rows.row(kind, employee, key)
    if row is None:
        raise Http404
    return row


def _stored_data(form_cls: type[PersonalRowForm], row: personal_rows.PersonalRow) -> dict[str, Any]:
    """Every field of the row's form at its stored value, as the form would post it (the loaded_* keys excluded: the
    editor posts those back, they are the values the editor was opened with)."""
    unbound = form_cls(initial=form_cls.from_snapshot(row.snapshot, row.ext))
    return {name: unbound[name].value() for name in unbound.fields if not name.startswith("loaded_")}


def _posted_data(
    form_cls: type[PersonalRowForm], row: personal_rows.PersonalRow, field: str, post: Mapping[str, str]
) -> dict[str, Any]:
    """The POST the row form is validated with: the stored values, overridden by the loaded_* keys the editor posted
    (the stale check needs them) and by the one posted field. A missing loaded_* key makes the save stale."""
    data = _stored_data(form_cls, row)
    for name in post:
        if name.startswith("loaded_"):
            data[name] = post[name]
    data[field] = post.get(field, "")
    return data


def editor(
    user: User,
    employee: Employee,
    kind: str,
    key: int,
    field: str,
    post: Mapping[str, str] | None = None,
) -> tuple[PersonalRowForm, personal_rows.PersonalRow]:
    """The row's form for the editor: unbound with the stored values when `post` is None, else bound to the posted
    data (the editor again after a failed save)."""
    row = _guard(user, employee, kind, key, field)
    form_cls = FORMS[kind]
    if post is None:
        return form_cls(initial=form_cls.from_snapshot(row.snapshot, row.ext), auto_id=False), row
    return form_cls(_posted_data(form_cls, row, field, post), auto_id=False), row


def _first_error(form: PersonalRowForm, field: str) -> str:
    """The first message for this field, else the first form-wide message, else the first of any field."""
    errors = form.errors.get(field) or form.non_field_errors()
    if errors:
        return str(errors[0])
    for messages in form.errors.values():
        return str(messages[0])
    return ""


def _text(value: object) -> str:
    """A value as the report cell shows it: dates as ISO, empty as an empty string."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@dataclass
class RowResult(CellResult):
    """A row save's outcome. `conflict` is True when the row changed after the editor opened (the stale check refused
    the save): the view then shows the editor again from the row's current values, so a retry can succeed."""

    conflict: bool = False


def save(
    user: User,
    employee: Employee,
    kind: str,
    key: int,
    field: str,
    post: Mapping[str, str],
) -> RowResult:
    """Validate and save one field of one row. Returns the new shown text when ok, else the message for the editor."""
    row = _guard(user, employee, kind, key, field)
    form_cls = FORMS[kind]
    form = form_cls(_posted_data(form_cls, row, field, post), auto_id=False)
    if not form.is_valid():
        return RowResult(ok=False, error=_first_error(form, field))
    columns, ext = form.values()
    try:
        pw.update(kind, employee, key, form.snapshot(), columns, ext, by=user)
    except pw.PersonalConflict as conflict:
        return RowResult(ok=False, error=str(conflict), conflict=True)
    current = personal_rows.row(kind, employee, key)
    return RowResult(ok=True, text=_text(current.values.get(field)) if current is not None else "")
