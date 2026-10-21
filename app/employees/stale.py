"""Stale check for the employee page save: production columns the old MACS program also writes.

The page posts back, in a hidden `loaded` field, the values it showed when it was opened. On save:
- a field HR left as loaded is not written, so a change the old program made meanwhile stays;
- a field HR changed is written when the stored value is still the loaded one;
- a field both changed is a clash: nothing is saved and the field asks which value to keep
  (`resolve-<name>` = "mine" or "theirs"). The page is then re-rendered with the current values as loaded.
A POST without `loaded` (old page, tests) keeps the earlier behaviour: every posted change is written.
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

from django import forms
from django.db.models import Model

from employees.models import Employee, EmployeeExt
from employees.services.display import shown

LOADED = "loaded"
RESOLVE = "resolve-"
SKIP = frozenset({"photo", "photo_clear"})


def norm(value: Any) -> Any:
    """A JSON-safe value that compares equal for the same stored value however the form produced it."""
    if isinstance(value, Model):
        return value.pk
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip() or None
    return value


def _current(form: forms.Form, name: str) -> Any:
    return norm(form.get_initial_for_field(form.fields[name], name))


def snapshot(form: forms.Form) -> str:
    """The hidden `loaded` value: what the form shows as stored, field by field."""
    return json.dumps({name: _current(form, name) for name in form.fields if name not in SKIP})


def _loaded(form: forms.Form) -> dict[str, Any] | None:
    raw = form.data.get(form.add_prefix(LOADED))
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except ValueError:
        return {}  # unreadable: every changed field is checked against nothing, so clashes are asked
    return found if isinstance(found, dict) else {}


def _theirs(employee: Employee, name: str) -> str:
    """The stored value as the user reads it."""
    for model, obj in ((Employee, employee), (EmployeeExt, getattr(employee, "ext", None))):
        try:
            field = model._meta.get_field(name)
        except Exception:  # noqa: S112 - not a field of this model, try the next one
            continue
        value = getattr(obj, field.name, None) if obj is not None else None
        return str(shown(field, value)) or "хоосон"
    return "—"


def resolve(form: forms.Form, employee: Employee, changes: dict[str, Any]) -> dict[str, Any]:
    """The changes to write. Clashes become field errors on `form` (and `form.conflicts`); write nothing then."""
    loaded = _loaded(form)
    if loaded is None:
        return changes
    conflicts: dict[str, str] = {}
    write: dict[str, Any] = {}
    for name, value in changes.items():
        choice = form.data.get(RESOLVE + form.add_prefix(name))
        if choice == "theirs":
            continue
        if name in loaded and _current(form, name) == loaded[name]:
            write[name] = value  # nobody else changed it: HR's change
        elif name in loaded and norm(value) == loaded[name]:
            continue  # HR left it as shown; the other program's value stays
        elif choice == "mine":
            write[name] = value
        else:
            conflicts[name] = _theirs(employee, name)
    form.conflicts = conflicts  # type: ignore[attr-defined]
    for name, theirs in conflicts.items():
        form.add_error(name, f"Энэ утгыг өөр газар (хуучин программ) «{theirs}» болгож өөрчилсөн байна.")
    return write
