"""Bulk edit of report cells (decision D-080, phase 3): many cells, one preview, then one save per cell.

Every cell goes through `reports.cell_edit.save`, so the rules, the rights and the activity log are the phase 2 ones.
This module only turns the text the user sees into the value the form takes, and runs the per-cell checks.
"""

import re
from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django import forms
from django.http import QueryDict
from employees import access

from reports import cell_edit

MAX_CELLS = 500
BAD_REQUEST = "Буруу хүсэлт"
TOO_MANY = "Нэг удаад 500 хүртэл нүд"
NOT_ALLOWED = "Энэ нүдийг засах эрхгүй"
NO_CHOICE = '"{}" гэсэн сонголт алга'
AMBIGUOUS = '"{}" гэсэн сонголт давхардсан'
BAD_DATE = "Огноог ЖЖЖЖ-СС-ӨӨ хэлбэрээр бичнэ үү"

# Year first, then month and day; the same separator twice: 2001-02-03, 2001.02.03 or 2001/02/03.
_DATE_RE = re.compile(r"^(\d{4})([.\-/])(\d{1,2})\2(\d{1,2})$")


def _same(a: str, b: str) -> bool:
    """Equal after collapsing runs of whitespace: a stored «А  Б» and the shown «А Б» are the same text."""
    return " ".join(a.split()) == " ".join(b.split())


@dataclass(frozen=True)
class BulkCell:
    """One cell of the batch: the employee (`person`), the field, the text the user typed and the text the cell
    showed before (`old`, for the stale check)."""

    person: int
    field: str
    text: str
    old: str


@dataclass
class BulkOutcome:
    """What happened to one cell: `text` is the shown value when ok, `error` the reason when not."""

    person: int
    field: str
    ok: bool
    text: str = ""
    error: str = ""


def _key(value: object) -> str:
    """A choice key as the browser posts it: a ModelChoiceIteratorValue gives its pk, a plain key is itself."""
    return str(getattr(value, "value", value))


def to_posted(form: forms.Form, field: str, text: str) -> tuple[str, str]:
    """The posted value for the text of a cell, and an error message when the text cannot be a value of the field.
    Empty text is the empty value (the form decides whether that is allowed).
    A choice is matched by its label (case and outer spaces ignored). A plain choice field also takes its key; a
    ModelChoiceField does not (a pk is not something the user types). Two choices with the same label are refused."""
    value = text.strip()
    if value == "":
        return "", ""
    bound = form.fields.get(field)
    if isinstance(bound, forms.ChoiceField):  # includes ModelChoiceField
        options = [(_key(key), str(label)) for key, label in bound.choices if _key(key) != ""]
        wanted = value.casefold()
        matches = [key for key, label in options if label.strip().casefold() == wanted]
        if len(matches) > 1:
            return "", AMBIGUOUS.format(value)
        if matches:
            return matches[0], ""
        if not isinstance(bound, forms.ModelChoiceField):
            for key, _label in options:
                if key.casefold() == wanted:
                    return key, ""
        return "", NO_CHOICE.format(value)
    if isinstance(bound, forms.DateField):
        match = _DATE_RE.match(value)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(3)), int(match.group(4))).isoformat(), ""
            except ValueError:  # a day or month that does not exist
                pass
        return "", BAD_DATE
    return value, ""


def parse_body(body: object) -> tuple[bool, list[BulkCell]]:
    """The decoded JSON body of a bulk request: `apply` (a real bool) and the cells. Raises ValueError with the text of
    the answer: BAD_REQUEST for a body of the wrong shape (an object with a bool `apply` and a list of objects, each
    with an int `person` and string `field`, `text`, `old`), TOO_MANY over MAX_CELLS. A field that is not editable is
    not a shape error: `run` refuses that cell."""
    if not isinstance(body, dict) or not isinstance(body.get("apply"), bool) or not isinstance(body.get("cells"), list):
        raise ValueError(BAD_REQUEST)
    cells: list[BulkCell] = []
    for raw in body["cells"]:
        if not isinstance(raw, dict):
            raise ValueError(BAD_REQUEST)
        person, field, text, old = raw.get("person"), raw.get("field"), raw.get("text"), raw.get("old")
        if type(person) is not int or not all(isinstance(v, str) for v in (field, text, old)):
            raise ValueError(BAD_REQUEST)
        cells.append(BulkCell(person=person, field=field, text=text, old=old))
    if len(cells) > MAX_CELLS:
        raise ValueError(TOO_MANY)
    return body["apply"], cells


def run(user: User, cells: list[BulkCell], apply: bool) -> list[BulkOutcome]:
    """Check every cell and, when `apply`, save the ok ones; when not, roll each write back (dry run). Raises
    ValueError(TOO_MANY) over MAX_CELLS. Nothing is saved for a refused cell."""
    if len(cells) > MAX_CELLS:
        raise ValueError(TOO_MANY)
    visible = access.visible_employees(user)
    editors: dict[str, forms.Form] = {}  # one form per field: the text is matched against its choices
    outcomes: list[BulkOutcome] = []
    for cell in cells:
        outcomes.append(_one(user, visible, editors, cell, apply))
    return outcomes


def _one(user: User, visible, editors: dict[str, forms.Form], cell: BulkCell, apply: bool) -> BulkOutcome:
    def fail(message: str) -> BulkOutcome:
        return BulkOutcome(person=cell.person, field=cell.field, ok=False, error=message)

    employee = visible.filter(pk=cell.person).first()
    if employee is None or not cell_edit.can_edit(user, employee, cell.field):
        return fail(NOT_ALLOWED)
    shown = cell_edit._shown_value(employee, cell.field)
    if not _same(shown, cell.old):
        return fail(cell_edit.CLASH)
    if _same(cell.text, shown):  # unchanged (whitespace aside): nothing to write
        return BulkOutcome(person=cell.person, field=cell.field, ok=True, text=shown)
    if cell.field not in editors:
        editors[cell.field] = cell_edit.editor_form(user, employee, cell.field)
    posted, error = to_posted(editors[cell.field], cell.field, cell.text)
    if error:
        return fail(error)
    post = QueryDict(mutable=True)
    post[cell.field] = posted  # no `loaded`: every posted change is written (no stale check)
    result = cell_edit.save(user, cell.person, cell.field, post, dry_run=not apply)
    return BulkOutcome(person=cell.person, field=cell.field, ok=result.ok, text=result.text, error=result.error)
