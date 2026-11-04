"""Firebird dialect 1 rejects unquoted reserved words, so no column may be named one of them.

The model-metadata tests only inspect the app registry and never touch a database. The MACS
test asks the Firebird server itself whether each MACS column name can be used unquoted.
"""

import pytest
from django.apps import apps
from django.db import DatabaseError, connections

RESERVED_WORDS = {"AT", "DATE", "DAY", "ORDER", "POSITION", "SENSITIVE", "VALUE"}

# (app_label, model class name, Python field name) -> the database column the field must use.
RULED_COLUMNS: dict[tuple[str, str, str], str] = {
    ("accounts", "SystemLogEntry", "at"): "at_time",
    ("employees", "ActivityEntry", "at"): "at_time",
    ("employees", "ActivityEntry", "sensitive"): "is_sensitive",
    ("employees", "HrOrder", "date"): "order_date",
    ("employees", "DailySync", "day"): "sync_day",
    ("leave", "LeaveRequestAction", "at"): "at_time",
    ("leave", "LeaveTypeExt", "order"): "sort_order",
    ("recruitment", "CandidateEvent", "at"): "at_time",
    ("recruitment", "CandidateComment", "at"): "at_time",
    ("checklists", "ChecklistTemplateTask", "position"): "position_no",
    ("checklists", "ChecklistTask", "position"): "position_no",
    ("lists", "MeaningfulEntry", "value"): "entry_value",
}


def test_no_model_column_is_a_reserved_word() -> None:
    offenders: list[str] = []
    for model in apps.get_models(include_auto_created=True):
        if not model._meta.managed or model._meta.app_label == "macs":
            continue
        for field in model._meta.concrete_fields:
            if field.column.upper() in RESERVED_WORDS:
                offenders.append(f"{model._meta.label}.{field.name} -> {field.column}")
    assert offenders == [], f"columns named after Firebird reserved words: {offenders}"


def test_columns_match_the_ruled_list() -> None:
    for (app_label, model_name, field_name), column in RULED_COLUMNS.items():
        model = apps.get_model(app_label, model_name)
        field = model._meta.get_field(field_name)
        assert field.column == column, f"{app_label}.{model_name}.{field_name} uses {field.column}, expected {column}"


def test_macs_columns_are_accepted_unquoted(fb_alias: str) -> None:
    # Where each distinct MACS column is used, so a rejected name can be traced back to its fields.
    users: dict[str, list[str]] = {}
    for model in apps.get_models(include_auto_created=True):
        if model._meta.app_label != "macs" or model._meta.managed:
            continue
        for field in model._meta.concrete_fields:
            users.setdefault(field.column, []).append(f"{model._meta.label}.{field.name}")

    # The ORM writes identifiers through ops.quote_name (no quotes, upper-cased on Firebird),
    # so the same form is used here: it is what the ORM would send to the server.
    ops = connections[fb_alias].ops
    rejected: list[str] = []
    with connections[fb_alias].cursor() as cursor:
        for column in sorted(users):
            name = ops.quote_name(column)
            try:
                cursor.execute(f"select 1 as {name} from rdb$database")  # noqa: S608 - names come from model metadata
            except DatabaseError as error:
                first_line = str(error).splitlines()[0] if str(error) else type(error).__name__
                rejected.append(f"{name} ({column}) used by {', '.join(users[column])}: {first_line}")

    if rejected:
        print("\nMACS columns Firebird rejects unquoted:")
        for line in rejected:
            print(f"  {line}")
        pytest.fail("MACS columns rejected unquoted by Firebird: " + "; ".join(rejected))
    assert rejected == []
