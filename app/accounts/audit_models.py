"""Audit receivers for settings, lookup lists and leave rules: the models listed in audit_registry.audited_models().

pre_save takes one query (the row as it is now), post_save compares it with the new values and writes one
system-log line, post_delete writes a delete line. A save without a real change writes nothing.

The receivers use record(), not record_safe(): they run inside the save or delete transaction, so a failed
log write rolls the change back. Note that Django sends post_save after the save's own atomic block, so every
write path that reaches a receiver must be atomic itself (see macs_writes.save_list_entry).

Files and binary content are never written to the log, only the field name and a fixed marker.
Writes with no request user (management commands, seeds) are not logged.
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F
from django.db.models.signals import post_delete, post_save, pre_save

from . import audit_context
from .audit import Category, record
from .audit_registry import audited_models

_BEFORE = "_audit_setting_before"  # where pre_save leaves the old row for post_save
_PARENT_LABEL = "audit_parent_label"  # the parent's name, read in the same snapshot query
_FILE_MARK = "(файл)"
_CHANGED_MARK = "(өөрчлөгдсөн)"  # a masked value changed; the value itself is never logged
# Fields whose values are never logged (the log is readable by everyone with view_audit, without the salary right).
# Every JSONField on an audited model is masked too, so a future JSON setting cannot leak through this path.
MASKED_FIELDS: dict[str, set[str]] = {
    "employees.staffimportsettings": {"defaults", "mapping"},
}
_YES = "Тийм"
_NO = "Үгүй"

# Rows that only exist because of a parent row: the HR flag of a department or position, the extension of a leave
# type. They log changes under the parent's name, and their creation is covered by the parent's setting_added.
_PARENT_FIELDS: dict[str, str] = {
    "employees.departmentext": "department",
    "employees.positionext": "position",
    "leave.leavetypeext": "leave_type",
}

# Singleton default rows: created the first time something reads them, not by a user. They get no setting_added line.
_SILENT_CREATE = {
    "employees.staffimportsettings",
    "employees.ordertemplate",
    "leave.leavesettings",
}

# Who or when stamped the row. They change on every save and are not a setting.
_BOOKKEEPING = {"updated_by", "created_by"}

# Target type shown for models whose verbose name is not in Mongolian (changing it would need a migration).
_TYPE_NAMES = {"lists.meaningfulentry": "Утгатай жагсаалтын сонголт"}


def _snapshot_before_save(sender: type[models.Model], instance: models.Model, raw: bool = False, **kwargs: Any) -> None:
    instance.__dict__[_BEFORE] = None
    if raw or instance.pk is None or audit_context.current_user() is None:
        return  # a new row has nothing to compare with; an unattributed write is not logged
    queryset = sender._base_manager.filter(pk=instance.pk)
    parent = _PARENT_FIELDS.get(sender._meta.label_lower)
    if parent is not None:
        queryset = queryset.annotate(**{_PARENT_LABEL: F(f"{parent}__name")})
    instance.__dict__[_BEFORE] = queryset.values().first()  # one query


def _text(field: models.Field[Any, Any], value: Any, related: dict[Any, Any]) -> str:
    if value is None:
        return ""
    if isinstance(field, models.BooleanField):
        return _YES if value else _NO
    if related and related.get(value) is not None:  # a foreign key or a meaning's entry: show its name
        return str(related[value])
    if field.choices:
        return str(dict(field.flatchoices).get(value, value))
    return str(value)


def _same(field: models.Field[Any, Any], old: Any, new: Any) -> bool:
    """Compare as the field would store them, so 5 and "5" count as the same value."""
    try:
        return bool(field.to_python(old) == field.to_python(new))
    except ValidationError:
        return bool(old == new)


def _stored_same(field: models.Field[Any, Any], old: Any, new: Any) -> bool:
    """Files and binary content: compare what is stored, never print it."""
    if isinstance(field, models.BinaryField):
        return bytes(old or b"") == bytes(new or b"")
    return str(old or "") == str(new or "")


def _changes(sender: type[models.Model], instance: models.Model, before: dict[str, Any]) -> list[dict[str, str]]:
    pending: list[tuple[models.Field[Any, Any], Any, Any]] = []
    masked_changes: list[dict[str, str]] = []
    for field in sender._meta.concrete_fields:
        if field.primary_key or field.name in _BOOKKEEPING:
            continue
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            continue  # bookkeeping stamps change on every save and are not a setting change
        old = before.get(field.attname)
        new = getattr(instance, field.attname)
        masked = field.name in MASKED_FIELDS.get(sender._meta.label_lower, set())
        if masked or isinstance(field, models.JSONField):
            if old != new:  # the stored JSON as Python values; only "it changed" is logged
                masked_changes.append({"field": str(field.verbose_name), "old": "", "new": _CHANGED_MARK})
            continue
        if isinstance(field, (models.FileField, models.BinaryField)):
            if not _stored_same(field, old, new):
                masked_changes.append(
                    {
                        "field": str(field.verbose_name),
                        "old": _FILE_MARK if old else "",
                        "new": _FILE_MARK if new else "",
                    }
                )
            continue
        if not _same(field, old, new):
            pending.append((field, old, new))

    # One lookup per changed reference (a foreign key, or a meaning's value), so the log shows names, not ids.
    changes = list(masked_changes)
    meaning = _meaning_of(sender, instance)
    for field, old, new in pending:
        lookup = _lookup_model(sender, field, meaning)
        found: dict[Any, Any] = {}
        if lookup is not None:
            found = lookup._base_manager.in_bulk([value for value in (old, new) if value is not None])
        label = str(field.verbose_name)
        if meaning is not None and field.attname == "value":
            label = meaning.label
        changes.append({"field": label, "old": _text(field, old, found), "new": _text(field, new, found)})
    return changes


def _meaning_of(sender: type[models.Model], instance: models.Model) -> Any:
    """The meaning a MeaningfulEntry row carries (lists.registry.MEANINGS), or None for any other model."""
    if sender._meta.label_lower != "lists.meaningfulentry":
        return None
    from lists.registry import MEANINGS

    return MEANINGS.get(str(getattr(instance, "key", "")))


def _lookup_model(sender: type[models.Model], field: models.Field[Any, Any], meaning: Any) -> Any:
    """The model whose names replace the ids in a change line: the related model, or the meaning's list."""
    if field.is_relation:
        related_model: Any = field.related_model  # Django types this as a union; it is a model class here
        return related_model
    if meaning is not None and field.attname == "value":
        return meaning.model
    return None


def _entry_name(meaning: Any, pk: Any) -> str:
    entry = meaning.model._base_manager.filter(pk=pk).first() if pk is not None else None
    return str(entry) if entry is not None else str(pk or "")


def _subject(sender: type[models.Model], instance: models.Model, before: dict[str, Any]) -> tuple[str, str]:
    """(target type, target label) of a line. Extension rows are shown under their parent's name."""
    key = sender._meta.label_lower
    target_type = _TYPE_NAMES.get(key) or str(sender._meta.verbose_name)
    parent = _PARENT_FIELDS.get(key)
    if parent is not None:
        parent_model: Any = sender._meta.get_field(parent).related_model
        return str(parent_model._meta.verbose_name), str(before.get(_PARENT_LABEL) or "")
    meaning = _meaning_of(sender, instance)
    if meaning is not None:
        return target_type, f"{meaning.label}: {_entry_name(meaning, getattr(instance, 'value', None))}"
    return target_type, str(instance)


def _log_saved(
    sender: type[models.Model], instance: models.Model, created: bool, raw: bool = False, **kwargs: Any
) -> None:
    before = instance.__dict__.pop(_BEFORE, None)
    if raw or audit_context.current_user() is None:
        return
    key = sender._meta.label_lower
    if created:
        if key in _PARENT_FIELDS or key in _SILENT_CREATE:
            return
        target_type, target_label = _subject(sender, instance, {})
        record(Category.SETTINGS, "setting_added", target_type=target_type, target_label=target_label)
        return
    if before is None:
        return  # the row was not there before the save: nothing to compare
    changes = _changes(sender, instance, before)
    if changes:
        target_type, target_label = _subject(sender, instance, before)
        record(
            Category.SETTINGS,
            "setting_changed",
            target_type=target_type,
            target_label=target_label,
            changes=changes,
        )


def _log_deleted(sender: type[models.Model], instance: models.Model, **kwargs: Any) -> None:
    if audit_context.current_user() is None:
        return
    target_type, target_label = _subject(sender, instance, {})
    record(Category.SETTINGS, "setting_deleted", target_type=target_type, target_label=target_label)


# One set of receivers per audited model. dispatch_uid keeps each connection unique if the module is imported twice.
# Extension rows get no delete receiver: deleting them is part of deleting the parent, which is logged once.
for _model in audited_models():
    _key = _model._meta.label_lower
    pre_save.connect(_snapshot_before_save, sender=_model, dispatch_uid=f"audit_setting_before_{_key}")
    post_save.connect(_log_saved, sender=_model, dispatch_uid=f"audit_setting_saved_{_key}")
    if _key not in _PARENT_FIELDS:
        post_delete.connect(_log_deleted, sender=_model, dispatch_uid=f"audit_setting_deleted_{_key}")
