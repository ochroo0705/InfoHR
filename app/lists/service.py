"""The Lists screen's rules without HTTP (docs/UI_RULES.md §11): the index search and the meaning page.

The Django views and the /api/v1/lists routes call these functions; nothing here reads a request.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from config.converters import INT4_MAX, INT4_MIN
from django import forms
from django.http import Http404
from employees.services import macs_writes
from employees.services.macs_writes import ListEntryInUse

from lists.forms import entry_form, list_fields
from lists.models import MeaningfulEntry
from lists.registry import LISTS, MEANINGS, ListSpec

_SIGNED_INT = re.compile(r"-?[0-9]{1,10}")


@dataclass(frozen=True)
class IndexItem:
    slug: str
    label: str
    count: int
    hits: int


@dataclass(frozen=True)
class MeaningRow:
    key: str
    label: str
    hint: str
    options: list[tuple[int, str]]  # (pk, name); an empty name is shown as the pk
    current: int | None


@dataclass(frozen=True)
class ColumnOut:
    name: str
    label: str


@dataclass(frozen=True)
class RowOut:
    pk: int
    cells: list[str]


@dataclass(frozen=True)
class ListPageData:
    slug: str
    label: str
    columns: list[ColumnOut]
    rows: list[RowOut]


@dataclass(frozen=True)
class FieldOut:
    name: str
    label: str
    kind: Literal["text", "select", "number"]
    required: bool
    max_length: int | None
    value: str
    choices: list[tuple[str, str]]  # [] unless kind is "select"; blank option first
    errors: list[str]


def parse_id(value: str | None) -> int | None:
    """A lookup-table id from a form. Negative ids are valid (MACS test data, QC 2b)."""
    if not value or not _SIGNED_INT.fullmatch(value) or not INT4_MIN <= int(value) <= INT4_MAX:
        return None
    return int(value)


def _words(q: str) -> list[str]:
    return q.strip().lower().split()


def index_items(q: str) -> list[IndexItem]:
    """The lists to show for a search. A list matches by its own name, or by an entry whose name has every word."""
    words = _words(q)
    items: list[IndexItem] = []
    for spec in LISTS.values():
        count = spec.model.objects.count()
        hits = 0
        if words and not all(w in spec.label.lower() for w in words):
            entries = spec.model.objects.all()
            for w in words:
                entries = entries.filter(name__icontains=w)
            hits = entries.count()
            if not hits:
                continue
        items.append(IndexItem(slug=spec.slug, label=spec.label, count=count, hits=hits))
    return items


def show_meanings(q: str) -> bool:
    """The «Утгын холбоо» card shows with no search, or when every word is in its name."""
    words = _words(q)
    return not words or all(w in "утгын холбоо" for w in words)


def meaning_rows() -> list[MeaningRow]:
    rows: list[MeaningRow] = []
    for key, spec in MEANINGS.items():
        options = [(pk, name) for pk, name in spec.model.objects.values_list("pk", "name")]
        rows.append(
            MeaningRow(key=key, label=spec.label, hint=spec.hint, options=options, current=MeaningfulEntry.get(key))
        )
    return rows


def save_meanings(post: Mapping[str, str]) -> None:
    """Set each meaning to the chosen entry. An empty choice deletes it; a junk or unknown pk changes nothing."""
    for key, spec in MEANINGS.items():
        raw = post.get(key, "")
        pk = parse_id(raw)
        if pk is not None and spec.model.objects.filter(pk=pk).exists():
            MeaningfulEntry.objects.update_or_create(key=key, defaults={"value": pk})
        elif not raw:
            MeaningfulEntry.objects.filter(key=key).delete()


def cell_text(entry: Any, field: str) -> str:
    """The text a list table shows for one column: a choice field shows its label, a None value shows nothing."""
    display = getattr(entry, f"get_{field}_display", None)  # choice fields show their label
    value = display() if display else getattr(entry, field)
    return "" if value is None else str(value)


def list_page(slug: str) -> ListPageData:
    """One list: its label, the columns (name first) and every entry ordered by name."""
    spec = LISTS.get(slug)
    if spec is None:
        raise Http404
    form_class = entry_form(spec)
    names = list_fields(spec)
    columns = [ColumnOut(name=name, label=str(form_class.base_fields[name].label)) for name in names]
    rows = [
        RowOut(pk=entry.pk, cells=[cell_text(entry, name) for name in names])
        for entry in spec.model.objects.all().order_by("name")
    ]
    return ListPageData(slug=spec.slug, label=spec.label, columns=columns, rows=rows)


def _choices(field: forms.Field) -> list[tuple[str, str]]:
    """Blank option first, then every option as (pk or code, label). A model choice shows str(obj), as the form does."""
    if isinstance(field, forms.ModelChoiceField):
        options = [(str(obj.pk), field.label_from_instance(obj)) for obj in field.queryset]
    else:
        choices = cast("list[tuple[Any, Any]]", field.choices)
        options = [(str(value), str(label)) for value, label in choices if value not in ("", None)]
    return [("", ""), *options]


def _kind(field: forms.Field) -> Literal["text", "select", "number"]:
    if isinstance(field, forms.ChoiceField):  # ModelChoiceField is a ChoiceField too
        return "select"
    if isinstance(field, forms.IntegerField):  # DecimalField and FloatField inherit from IntegerField
        return "number"
    return "text"


def entry_fields(spec: ListSpec, form: forms.BaseForm) -> list[FieldOut]:
    """The fields of an entry pop-up, in list_fields order, with the kind the React pop-up draws."""
    out: list[FieldOut] = []
    for name in list_fields(spec):
        field = form.fields[name]
        kind = _kind(field)
        value = form[name].value()
        out.append(
            FieldOut(
                name=name,
                label=str(field.label or name),
                kind=kind,
                required=field.required,
                max_length=getattr(field, "max_length", None),
                value="" if value is None else str(value),
                choices=_choices(field) if kind == "select" else [],
                errors=[str(error) for error in form.errors.get(name, [])],
            )
        )
    return out


@dataclass(frozen=True)
class SaveResult:
    ok: bool
    entry: Any | None
    form: Any  # the bound form: it carries the errors when ok is False


@dataclass(frozen=True)
class DeleteResult:
    ok: bool
    error: str  # the «in use» message when ok is False, else ""


def save_entry(spec: ListSpec, post: Mapping[str, str], *, entry: Any | None = None) -> SaveResult:
    """Add (entry None) or edit one list entry from a form. An invalid form writes nothing."""
    form_class = entry_form(spec)
    form = form_class(post, instance=entry) if entry is not None else form_class(post)
    if not form.is_valid():
        return SaveResult(ok=False, entry=None, form=form)
    saved = macs_writes.save_list_entry(spec.model, form.cleaned_data, entry=entry)
    return SaveResult(ok=True, entry=saved, form=form)


def delete_entry(entry: Any) -> DeleteResult:
    """Remove a list entry. An entry still used by an employee or record is refused with the Django message."""
    try:
        macs_writes.delete_list_entry(entry)
    except ListEntryInUse as exc:
        return DeleteResult(ok=False, error=str(exc))
    return DeleteResult(ok=True, error="")


@dataclass(frozen=True)
class QuickResult:
    ok: bool
    id: int | None  # the entry picked or created; None when ok is False
    name: str  # the entry's stored name; "" when ok is False
    existed: bool  # True when a matching entry was found (and reactivated) instead of creating one
    form: Any  # the bound form when ok is False (it carries the errors); the form used when created, else None


def existing_entry(spec: ListSpec, name: str, parent: str = "") -> Any | None:
    """The entry with the same name (trimmed, case-insensitive), so the add never makes a duplicate.
    A list with a parent (district -> city) matches only inside the same parent."""
    if not name:
        return None
    # A name longer than the column cannot be stored, so it cannot match. Firebird raises SQL -303 on
    # the lookup itself; returning None here lets the form report the length error.
    if len(name) > spec.model._meta.get_field("name").max_length:
        return None
    qs = spec.model.objects.filter(name__iexact=name)
    if spec.parent:
        parent_id = parse_id(parent)
        if parent_id is None:
            return None
        qs = qs.filter(**{f"{spec.parent}_id": parent_id})
    return qs.order_by("pk").first()


def reactivate(spec: ListSpec, entry: Any) -> None:
    """Department and Position keep an HR extension row with an active flag; a duplicate that was
    switched off is shown again instead of being left out of the dropdowns."""
    if spec.slug == "department":
        macs_writes.reactivate_department(entry)
    elif spec.slug == "position":
        macs_writes.reactivate_position(entry)


def create_entry(spec: ListSpec, values: dict[str, Any]) -> Any:
    if spec.slug == "department":
        return macs_writes.save_department(values["name"])
    if spec.slug == "position":
        return macs_writes.save_position(values["name"])
    return macs_writes.save_list_entry(spec.model, values)


def first_error(form: Any) -> str:
    for errors in form.errors.values():
        return str(errors[0])
    return "Алдаа гарлаа."


def quick_add(spec: ListSpec, post: Mapping[str, str]) -> QuickResult:
    """Pick the entry with the same name, or create it from a form dropdown. An invalid form writes nothing."""
    existing = existing_entry(spec, post.get("name", "").strip(), post.get(spec.parent or "", ""))
    if existing is not None:
        reactivate(spec, existing)
        return QuickResult(ok=True, id=existing.pk, name=existing.name, existed=True, form=None)
    form = entry_form(spec)(post)
    if form.is_valid():
        entry = create_entry(spec, form.cleaned_data)
        return QuickResult(ok=True, id=entry.pk, name=entry.name, existed=False, form=form)
    return QuickResult(ok=False, id=None, name="", existed=False, form=form)


def quick_initial(spec: ListSpec, get: Mapping[str, str]) -> dict[str, str]:
    """The pop-up's starting values: the list's own fields that the GET carried (the typed name, a parent)."""
    return {name: get[name] for name in list_fields(spec) if get.get(name)}
