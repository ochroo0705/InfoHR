"""The inline editors of a report cell, as plain data (decision D-080, step 5f).

The rules stay where they are (reports.cell_edit, reports.row_edit: who may edit, the stale check, the write).
This module turns their forms into an EditorModel the React editor draws, and runs the same checks in the same
order as the Django views (reports.views.cell_edit, row_cell): 404 for an unknown field or kind, 404 for an unseen
employee, then 403 for no right. It takes plain values and never an HttpRequest.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from accounts.models import User
from django import forms
from django.core.exceptions import PermissionDenied
from django.forms.boundfield import BoundField
from django.http import Http404, QueryDict
from django.shortcuts import get_object_or_404
from employees import access, stale
from employees.models import Employee
from employees.services.report_corrections import Record

from reports import cell_edit, corrections, row_edit


@dataclass(frozen=True)
class EditorChoice:
    value: str
    label: str


@dataclass(frozen=True)
class EditorModel:
    """One open editor: what the field is, what it shows, and the tokens the save posts back."""

    kind: Literal["text", "choice", "date", "number"]
    name: str
    value: str  # the bound value as shown: a date as ISO, a choice as its option value
    label: str  # a choice's label for the value ("" for the empty option), "" for other kinds
    choices: list[EditorChoice]  # a choice's options, the empty option included; [] for other kinds
    required: bool
    maxlength: int | None  # text only
    loaded: str  # the stale token of a cell (stale.snapshot of its form); "" for a row, whose tokens are in `hidden`
    hidden: dict[str, str] = field(default_factory=dict)  # a row editor: the other fields of the row form
    reason: bool = False  # the correction editor asks for a reason
    old: str = ""  # the correction editor: the value it replaces
    note: str = ""  # the correction editor: the note shown under the input
    reason_text: str = ""  # the correction editor: the reason the user typed, kept after a failed save
    blocked: str = ""  # the correction editor: why no input is shown
    error: str = ""  # the message of a failed save


@dataclass(frozen=True)
class EditResult:
    """A save's outcome. `editor` is the editor to show after a failed save: the current stored value with a fresh
    token after a clash, the typed text with the posted token after any other error."""

    ok: bool
    text: str = ""
    error: str = ""
    editor: EditorModel | None = None
    conflict: bool = False  # a row changed after its editor opened (the fresh editor shows the current values)


CLASH = cell_edit.CLASH


def _text(value: object) -> str:
    """A bound value as the editor shows it: None as empty, a date as ISO, anything else as its text."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _choices(bound_field: BoundField) -> list[EditorChoice]:
    """The options of a choice field, the empty option kept; an option group is flattened into the list."""
    options: list[EditorChoice] = []
    for value, label in bound_field.field.choices:
        if isinstance(label, (list, tuple)):  # an option group
            options.extend(EditorChoice(value=_text(inner), label=str(text)) for inner, text in label)
        else:
            options.append(EditorChoice(value=_text(value), label=str(label)))
    return options


def model_of(
    bound_field: BoundField,
    *,
    loaded: str = "",
    hidden: dict[str, str] | None = None,
    error: str = "",
) -> EditorModel:
    """The editor of one bound form field: the kind by the field's class, the value as shown, the choices."""
    form_field = bound_field.field
    value = _text(bound_field.value())
    choices: list[EditorChoice] = []
    label = ""
    maxlength: int | None = None
    if isinstance(form_field, forms.ChoiceField):
        kind: Literal["text", "choice", "date", "number"] = "choice"
        choices = _choices(bound_field)
        if value:
            label = next((option.label for option in choices if option.value == value), value)
    elif isinstance(form_field, forms.DateField):
        kind = "date"
    elif isinstance(form_field, (forms.IntegerField, forms.DecimalField)):
        kind = "number"
    else:
        kind = "text"
        raw = form_field.widget.attrs.get("maxlength", getattr(form_field, "max_length", None))
        maxlength = int(raw) if raw not in (None, "") else None
    return EditorModel(
        kind=kind,
        name=bound_field.name,
        value=value,
        label=label,
        choices=choices,
        required=form_field.required,
        maxlength=maxlength,
        loaded=loaded,
        hidden=dict(hidden or {}),
        error=error,
    )


def _hidden_of(form: forms.Form, name: str) -> dict[str, str]:
    """The other fields of a row form at their current bound values: the row's values and the loaded_* tokens."""
    return {other: _text(form[other].value()) for other in form.fields if other != name}


def _cell_employee(user: User, person: int, field_name: str) -> Employee:
    """The employee of a cell editor, after the checks the cell_edit view makes: 404 for an unknown field or an unseen
    employee, 403 when the user may not change the field."""
    if field_name not in cell_edit.EDITABLE and field_name not in cell_edit.SALARY_EDITABLE:
        raise Http404
    employee = get_object_or_404(access.visible_employees(user), pk=person)
    if not cell_edit.can_edit(user, employee, field_name):
        raise PermissionDenied
    return employee


def _row_employee(user: User, person: int, kind: str, field_name: str) -> Employee:
    """The employee of a row editor: 404 for an unknown kind or field, then 404 for an unseen employee."""
    if kind not in row_edit.KINDS or field_name not in row_edit.KINDS[kind]:
        raise Http404
    return get_object_or_404(access.visible_employees(user), pk=person)


def open_cell(user: User, person: int, field_name: str) -> EditorModel:
    """The editor of one employee field in a report cell, with the stored value and the stale token."""
    employee = _cell_employee(user, person, field_name)
    form = cell_edit.editor_form(user, employee, field_name)
    return model_of(form[field_name], loaded=stale.snapshot(form))


def save_cell(user: User, person: int, field_name: str, value: str, loaded: str) -> EditResult:
    """Save one employee field through cell_edit.save. A clash shows the current stored value with a fresh token; any
    other error keeps the typed text and the loaded token that was posted."""
    employee = _cell_employee(user, person, field_name)
    post = QueryDict(mutable=True)
    post[field_name] = value
    post["loaded"] = loaded
    result = cell_edit.save(user, person, field_name, post)
    if result.ok:
        return EditResult(ok=True, text=result.text)
    if result.error == CLASH:
        current = cell_edit.editor_form(user, Employee.objects.get(pk=person), field_name)
        editor = model_of(current[field_name], loaded=stale.snapshot(current), error=result.error)
        return EditResult(ok=False, error=result.error, editor=editor)
    bound = cell_edit.editor_form(user, employee, field_name, cell_edit.posted_data(user, employee, field_name, post))
    editor = model_of(bound[field_name], loaded=loaded, error=result.error)
    return EditResult(ok=False, error=result.error, editor=editor)


def open_row(user: User, person: int, kind: str, key: int, field_name: str) -> EditorModel:
    """The editor of one cell of a children or contacts row: the visible field and the other fields as hidden."""
    employee = _row_employee(user, person, kind, field_name)
    form, _ = row_edit.editor(user, employee, kind, key, field_name)
    return model_of(form[field_name], hidden=_hidden_of(form, field_name))


def save_row(user: User, person: int, kind: str, key: int, field_name: str, values: dict[str, str]) -> EditResult:
    """Save one field of one row through row_edit.save. `values` is the posted visible field plus the hidden fields
    open_row returned (the loaded_* tokens included). A row changed meanwhile gives conflict and a fresh editor."""
    employee = _row_employee(user, person, kind, field_name)
    result = row_edit.save(user, employee, kind, key, field_name, dict(values))
    if result.ok:
        return EditResult(ok=True, text=result.text)
    if result.conflict:
        form, _ = row_edit.editor(user, employee, kind, key, field_name)
    else:
        form, _ = row_edit.editor(user, employee, kind, key, field_name, dict(values))
    editor = model_of(form[field_name], hidden=_hidden_of(form, field_name), error=result.error)
    return EditResult(ok=False, error=result.error, editor=editor, conflict=result.conflict)


CORRECT_NOTE = "Анхны утгыг засна. Шилжүүлэх, цалин нэмэх бол тушаалаар."


def _correct_cell(user: User, person: int, key: str, record_id: int | None) -> tuple[Employee, Record, str]:
    """The employee, the record and the blocking message of a correction cell, after the checks the reports:correct
    view makes in its order: 404 for an unknown key, a job key without a record or an unseen employee, 403 when the
    user may not correct the cell (checked before the record is looked up), then 404 when there is no such record."""
    if key not in corrections.KEYS:
        raise Http404
    if corrections.KEYS[key] == "job" and record_id is None:
        raise Http404
    employee = get_object_or_404(access.visible_employees(user), pk=person)
    if not corrections.can_correct(user, employee, key):
        raise PermissionDenied
    record, blocked = corrections.lookup(employee, key, record_id)
    if record is None:
        raise Http404
    return employee, record, blocked


def _correct_model(
    user: User,
    record: Record,
    key: str,
    *,
    old: str,
    blocked: str = "",
    reason_text: str = "",
    error: str = "",
    data: QueryDict | None = None,
) -> EditorModel:
    """The correction editor of one cell. A blocked cell has no inputs: the kind stays, the choices are empty."""
    bound = corrections.form_for(user, record, key, data)[corrections.field_of(key)]
    model = model_of(bound, error=error)
    if blocked:
        return replace(model, value="", label="", choices=[], reason=False, old=old, note="", blocked=blocked)
    return replace(model, reason=True, old=old, note=CORRECT_NOTE, reason_text=reason_text)


def open_correct(user: User, person: int, key: str, record: int | None) -> EditorModel:
    """The editor of one job field (department, position, manager; `record` is the job record) or of today's base
    salary (`record` None) in a report cell. A cell that may not be corrected now gets only its message in `blocked`."""
    _, shown, blocked = _correct_cell(user, person, key, record)
    return _correct_model(user, shown, key, old=corrections.shown_text(shown, key), blocked=blocked)


def save_correct(
    user: User, person: int, key: str, record: int | None, value: str, old: str, reason: str
) -> EditResult:
    """Save one correction through corrections.save (the activity log, the stale check). A blocked cell writes nothing
    and returns its message. A clash gives the current text in a fresh editor; any other error keeps the typed reason
    and the posted old text."""
    employee, shown, blocked = _correct_cell(user, person, key, record)
    if blocked:
        editor = _correct_model(user, shown, key, old=corrections.shown_text(shown, key), blocked=blocked)
        return EditResult(ok=False, error=blocked, editor=editor)
    post = QueryDict(mutable=True)
    post["old"] = old
    post["reason"] = reason
    post[corrections.field_of(key)] = value
    result = corrections.save(user, employee, key, shown, post)
    if result.ok:
        return EditResult(ok=True, text=result.text)
    if result.error == CLASH:
        fresh, fresh_blocked = corrections.lookup(employee, key, record)
        if fresh is None:
            raise Http404
        editor = _correct_model(
            user,
            fresh,
            key,
            old=corrections.shown_text(fresh, key),
            blocked=fresh_blocked,
            error=result.error,
        )
        return EditResult(ok=False, error=result.error, editor=editor)
    editor = _correct_model(
        user,
        shown,
        key,
        old=old,
        reason_text=reason,
        error=result.error,
        data=post,
    )
    return EditResult(ok=False, error=result.error, editor=editor)
