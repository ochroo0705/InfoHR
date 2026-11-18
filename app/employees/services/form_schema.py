"""Describe a Django form's fields as plain dicts, for the React screens (the API) and for tests.

One dict per visible field: its HTML name, label, the kind of box it draws, the text a browser would post for it, and
the select's options. The rules here are the ones the Django templates follow (employees/_field.html and select.js), so
the API shows the same boxes the page does. Nothing here touches the request or the database beyond what the form
already holds.
"""

from collections.abc import Iterable
from typing import Any, TypedDict

from django.forms import (
    BoundField,
    CheckboxInput,
    DateInput,
    FileInput,
    Form,
    HiddenInput,
    NumberInput,
    Select,
    Textarea,
    Widget,
)

from employees.sections import _as_posted

# select.js SEARCH_FROM: a select with this many options (blank entry included) is a typing box.
SEARCH_FROM = 8


class FormChoice(TypedDict):
    value: str
    label: str


def _kind(widget: Widget) -> str:
    """The box kind a field's widget draws (the same mapping as the _field.html templates)."""
    if isinstance(widget, CheckboxInput):
        return "checkbox"
    if isinstance(widget, Select):
        return "select"
    if isinstance(widget, Textarea):
        return "textarea"
    if isinstance(widget, DateInput):
        return "date"
    if isinstance(widget, NumberInput):
        return "number"
    if isinstance(widget, FileInput):  # ClearableFileInput subclasses FileInput
        return "file"
    return "text"


def _choice_value(value: Any) -> str:
    raw = getattr(value, "value", value)  # a ModelChoiceIteratorValue carries the pk in .value
    return "" if raw is None else str(raw)


def _box_placeholder(widget: Any, kind: str) -> str:
    """A select's data-placeholder (the birth place pickers), a text box's placeholder or «—», "" for a checkbox."""
    if kind == "select":
        return str(widget.attrs.get("data-placeholder", ""))
    if kind == "checkbox":
        return ""
    return str(widget.attrs.get("placeholder", "—"))


def combo_rule(widget: Select, choice_count: int) -> bool:
    """select.js draws the select as a combo text box: a quick-add list, data-search on, or 8+ options (not off)."""
    search = widget.attrs.get("data-search")
    return "data-add-url" in widget.attrs or search == "on" or (search != "off" and choice_count >= SEARCH_FROM)


def describe_field(bound: BoundField) -> dict[str, Any]:
    """One field's description (see describe_form). Keys: name, label, required, kind, value, checked, placeholder,
    choice, combo, choices, help, max_length, errors."""
    widget = bound.field.widget
    kind = _kind(widget)
    value = bound.value()
    choices: list[FormChoice] = []
    choice = ""
    combo = False
    if kind == "select":
        field_choices: Iterable[tuple[Any, Any]] = getattr(bound.field, "choices", ())
        choices = [{"value": _choice_value(v), "label": str(label)} for v, label in field_choices]
        posted = _as_posted(value)
        choice = next((c["label"] for c in choices if posted and c["value"] == posted), "")
        combo = combo_rule(widget, len(choices))
    return {
        "name": bound.html_name,
        "label": str(bound.label),
        "required": bool(bound.field.required),
        "kind": kind,
        "value": _as_posted(value),
        "checked": bool(value) if kind == "checkbox" else False,
        "placeholder": _box_placeholder(widget, kind),
        "choice": choice,
        "combo": combo,
        "choices": choices,
        "help": str(bound.help_text or ""),
        "max_length": getattr(bound.field, "max_length", None),
        "errors": [str(message) for message in bound.errors],
    }


def describe_form(form: Form, *, names: Iterable[str] | None = None) -> list[dict[str, object]]:
    """One dict per visible field, in `names` order when given, else in form order. Hidden inputs are skipped."""
    bound_fields = [form[name] for name in names] if names is not None else list(form)
    return [describe_field(bound) for bound in bound_fields if not isinstance(bound.field.widget, HiddenInput)]


def hidden_values(form: Form) -> dict[str, str]:
    """The form's hidden fields by HTML name, as the browser would post them (the loaded_* snapshots)."""
    return {bound.html_name: _as_posted(bound.value()) for bound in form if isinstance(bound.field.widget, HiddenInput)}


def empty_lists(form: Form) -> list[dict[str, str]]:
    """The code lists the form needs that have no entries yet, as {slug, label}; [] when the form has none to report."""
    method = getattr(form, "empty_lists", None)
    if method is None:
        return []
    return [{"slug": slug, "label": label} for slug, label in method()]
