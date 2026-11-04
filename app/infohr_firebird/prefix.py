"""Table-name prefix for the tables the HR app creates in a shared database (plan Task 6).

The MACS Firebird database already has tables named HR_*, so HR-owned tables get the
prefix from settings.HR_TABLE_PREFIX (IHR_ on Firebird; empty on PostgreSQL = no change).
The receiver runs when each model class is prepared, so the name is set before any
table is created, queried or rendered in a migration.
"""

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models.signals import class_prepared

PREFIX_RECEIVER_UID = "infohr_table_prefix"
MACS_APP_LABEL = "macs"  # MACS owns its own tables; never rename them


def apply_prefix(model: type[models.Model], prefix: str) -> None:
    """Prefix the model's table name once. Unmanaged and MACS models are left alone."""
    meta = model._meta
    # A proxy has no table of its own: it shares its concrete model's table name.
    if not prefix or not meta.managed or meta.proxy or meta.app_label == MACS_APP_LABEL:
        return
    # Django's convention is a lower-case db_table: introspection.table_names() reports lower case
    # (Firebird stores upper case), and Django compares the two. A mixed-case name never matches.
    table = meta.db_table.lower()
    if table.startswith(prefix.lower()):  # already prefixed: keeps this idempotent
        meta.db_table = table
        return
    meta.db_table = (prefix + table).lower()


def _on_class_prepared(sender: type[models.Model], **kwargs: Any) -> None:
    apply_prefix(sender, getattr(settings, "HR_TABLE_PREFIX", ""))


def connect_prefix_receiver() -> None:
    """Connect the class_prepared receiver. Safe to call twice (dispatch_uid)."""
    class_prepared.connect(_on_class_prepared, dispatch_uid=PREFIX_RECEIVER_UID)
