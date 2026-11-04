"""Structure fingerprint of a Firebird database, and the pre-flight check for HR table names.

The fingerprint proves that HR only ADDED objects to the shared MACS database: the existing
objects must hash to the same value before and after HR creates its tables. Anything that
belongs to an HR table is left out, so creating ``IHR_`` tables does not change it. Anything
that belongs to an existing MACS table is hashed in full (columns with their types and
defaults, keys and their columns and rules, indices and their columns, check bodies, triggers).

What is excluded, and why:

- Relations, fields, constraints, check constraints (NOT NULL included), indices and triggers
  have an owning table. They are excluded by the OWNING RELATION's name only. A trigger named
  ``IHR_X`` on an existing MACS table is therefore still hashed.
- Generators, procedures (and their parameters) and user domains have no owning table. They are
  excluded by their OWN NAME: the ``IHR_`` namespace is reserved for HR, so an object named with
  the prefix is HR's, whatever it is attached to.

Names verified on the clone (``IHR_T_PARENT_TABLE_WITH_LONG_NAME`` and ``IHR_T_CHILD`` with a
foreign key, created with Django's schema editor):

- table: ``quote_name`` cuts the name to 31 characters and puts a hash in the last four, so the
  table is ``IHR_T_PARENT_TABLE_WITH_LON7C1A``. The prefix always survives the cut.
- sequence generator: ``<TABLE>_SQ``, e.g. ``IHR_T_CHILD_SQ`` and ``IHR_T_PARENT_TABLE_WITH_7C1A_SQ``.
- primary key trigger: ``<TABLE>_PK``, e.g. ``IHR_T_CHILD_PK``, owned by the ``IHR_`` relation.
- constraints, check constraints (NOT NULL included) and indices belong to their relation.

Known limit: dialect 1 stores no NUMERIC precision. ``rdb$field_precision`` is NULL for both
``NUMERIC(10,2)`` and ``NUMERIC(12,2)``, and their stored type, length and scale are the same, so a
precision-only change cannot be detected by any structure fingerprint. Scale and type changes are
detected.
"""

import hashlib
from collections.abc import Iterable
from typing import Any

from django.db.models import Model

CATEGORIES: tuple[str, ...] = (
    "relations",
    "fields",
    "constraints",
    "checks",
    "indices",
    "triggers",
    "procedures",
    "generators",
    "domains",
)

_RELATIONS_SQL = "select trim(rdb$relation_name), rdb$view_source from rdb$relations where rdb$system_flag = 0"
_FIELDS_SQL = (
    "select trim(rf.rdb$relation_name), trim(rf.rdb$field_name), trim(rf.rdb$field_source), "
    "rf.rdb$null_flag, rf.rdb$default_source, rf.rdb$field_position, "
    "f.rdb$field_type, f.rdb$field_length, f.rdb$field_scale, f.rdb$field_precision, f.rdb$field_sub_type, "
    "f.rdb$character_set_id, f.rdb$collation_id, f.rdb$default_source, f.rdb$computed_source, "
    "f.rdb$validation_source, f.rdb$segment_length "
    "from rdb$relation_fields rf join rdb$fields f on rf.rdb$field_source = f.rdb$field_name"
)
_CONSTRAINTS_SQL = (
    "select trim(rdb$relation_name), trim(rdb$constraint_name), trim(rdb$constraint_type), "
    "trim(rdb$index_name) from rdb$relation_constraints"
)
_REFS_SQL = (
    "select trim(rdb$constraint_name), trim(rdb$const_name_uq), trim(rdb$match_option), "
    "trim(rdb$update_rule), trim(rdb$delete_rule) from rdb$ref_constraints"
)
_SEGMENTS_SQL = "select trim(rdb$index_name), rdb$field_position, trim(rdb$field_name) from rdb$index_segments"
_CHECKS_SQL = (
    "select trim(rc.rdb$relation_name), trim(cc.rdb$constraint_name), trim(cc.rdb$trigger_name) "
    "from rdb$check_constraints cc "
    "join rdb$relation_constraints rc on rc.rdb$constraint_name = cc.rdb$constraint_name"
)
_TRIGGER_SOURCES_SQL = "select trim(rdb$trigger_name), rdb$trigger_source from rdb$triggers"
_INDICES_SQL = (
    "select trim(rdb$relation_name), trim(rdb$index_name), rdb$unique_flag, rdb$index_inactive, "
    "rdb$index_type, trim(rdb$foreign_key), rdb$expression_source from rdb$indices"
)
_TRIGGERS_SQL = (
    "select trim(rdb$relation_name), trim(rdb$trigger_name), rdb$trigger_type, rdb$trigger_inactive, "
    "rdb$trigger_source from rdb$triggers where rdb$system_flag = 0"
)
_PROCEDURES_SQL = "select trim(rdb$procedure_name), rdb$procedure_source from rdb$procedures"
_PROCEDURE_PARAMS_SQL = (
    "select trim(rdb$procedure_name), trim(rdb$parameter_name), rdb$parameter_number, rdb$parameter_type, "
    "trim(rdb$field_source) from rdb$procedure_parameters"
)
_GENERATORS_SQL = "select trim(rdb$generator_name) from rdb$generators where rdb$system_flag = 0"
_DOMAINS_SQL = (
    "select trim(rdb$field_name), rdb$field_type, rdb$field_length, rdb$field_scale, rdb$null_flag, "
    "rdb$default_source, rdb$validation_source, rdb$field_precision, rdb$field_sub_type, "
    "rdb$character_set_id, rdb$collation_id, rdb$computed_source, rdb$segment_length from rdb$fields"
)
_EXISTING_TABLES_SQL = "select trim(rdb$relation_name) from rdb$relations where rdb$system_flag = 0"


def _plain(value: Any) -> Any:
    """Plain Python value: blobs read fully, text trimmed (CHAR padding), None kept as None."""
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value.strip()
    return value


def _rows(cursor: Any, sql: str) -> list[tuple[Any, ...]]:
    cursor.execute(sql)
    return [tuple(_plain(value) for value in row) for row in cursor.fetchall()]


def _hr_owned(name: Any, prefixes: tuple[str, ...]) -> bool:
    """True when name starts with an ignored prefix. prefixes must already be upper-case."""
    return isinstance(name, str) and name.upper().startswith(prefixes)


def _kept(cursor: Any, sql: str, prefixes: tuple[str, ...]) -> list[tuple[Any, ...]]:
    """Rows of sql whose first column (the owner or the object's own name) is not HR-owned."""
    return [row for row in _rows(cursor, sql) if not _hr_owned(row[0], prefixes)]


def _digest(rows: list[tuple[Any, ...]]) -> tuple[int, str]:
    ordered = sorted(rows, key=repr)  # repr sorts safely even when a column holds None
    return len(ordered), hashlib.sha256(repr(ordered).encode("utf-8")).hexdigest()[:12]


def _segments(cursor: Any) -> dict[str, tuple[str, ...]]:
    """Index name -> its field names in key order."""
    grouped: dict[str, list[tuple[int, str]]] = {}
    for index_name, position, field in _rows(cursor, _SEGMENTS_SQL):
        grouped.setdefault(str(index_name), []).append((int(position), str(field)))
    return {name: tuple(field for _, field in sorted(pairs)) for name, pairs in grouped.items()}


def _constraint_rows(cursor: Any, prefixes: tuple[str, ...]) -> list[tuple[Any, ...]]:
    """Each constraint with its own key columns and, for a foreign key, the rule and the referenced key."""
    columns = _segments(cursor)
    refs: dict[str, tuple[Any, Any, Any, Any]] = {}
    for name, referenced, match, update, delete in _rows(cursor, _REFS_SQL):
        refs[str(name)] = (referenced, match, update, delete)
    all_rows = _rows(cursor, _CONSTRAINTS_SQL)
    by_name = {str(row[1]): row for row in all_rows}
    out: list[tuple[Any, ...]] = []
    for relation, name, kind, index in all_rows:
        if _hr_owned(relation, prefixes):
            continue
        own_columns = columns.get(str(index), ()) if index else ()
        ref = refs.get(str(name))
        if ref is None:
            ref_part: tuple[Any, ...] = (None, None, None, None, None)
        else:
            referenced, match, update, delete = ref
            target = by_name.get(str(referenced))
            target_columns = columns.get(str(target[3]), ()) if target and target[3] else ()
            ref_part = (match, update, delete, target[0] if target else None, target_columns)
        out.append((relation, name, kind, index, own_columns, *ref_part))
    return out


def _index_rows(cursor: Any, prefixes: tuple[str, ...]) -> list[tuple[Any, ...]]:
    columns = _segments(cursor)
    return [
        (*row, columns.get(str(row[1]), ())) for row in _rows(cursor, _INDICES_SQL) if not _hr_owned(row[0], prefixes)
    ]


def _check_rows(cursor: Any, prefixes: tuple[str, ...]) -> list[tuple[Any, ...]]:
    """Each check with the body (source) of the trigger that implements it."""
    sources = {str(row[0]): row[1] for row in _rows(cursor, _TRIGGER_SOURCES_SQL)}
    return [
        (relation, name, trigger, sources.get(str(trigger)) if trigger else None)
        for relation, name, trigger in _rows(cursor, _CHECKS_SQL)
        if not _hr_owned(relation, prefixes)
    ]


def existing_tables(cursor: Any) -> set[str]:
    """Upper-case names of all non-system tables and views in the database."""
    cursor.execute(_EXISTING_TABLES_SQL)
    return {str(row[0]).strip().upper() for row in cursor.fetchall()}


def fingerprint(cursor: Any, ignore_prefixes: tuple[str, ...]) -> dict[str, tuple[int, str]]:
    """Map each category to (row count, first 12 hex chars of sha256 of the sorted rows).

    Rows owned by an HR table are left out (see the module docstring for which rows are owned by
    their table and which by their own name). Prefix matching is case-insensitive.
    """
    prefixes = tuple(prefix.upper() for prefix in ignore_prefixes)
    procedure_rows = [("PROCEDURE", *row) for row in _kept(cursor, _PROCEDURES_SQL, prefixes)]
    parameter_rows = [("PARAMETER", *row) for row in _kept(cursor, _PROCEDURE_PARAMS_SQL, prefixes)]
    domains = [row for row in _kept(cursor, _DOMAINS_SQL, prefixes) if not str(row[0]).startswith("RDB$")]
    return {
        "relations": _digest(_kept(cursor, _RELATIONS_SQL, prefixes)),
        "fields": _digest(_kept(cursor, _FIELDS_SQL, prefixes)),
        "constraints": _digest(_constraint_rows(cursor, prefixes)),
        "checks": _digest(_check_rows(cursor, prefixes)),
        "indices": _digest(_index_rows(cursor, prefixes)),
        "triggers": _digest(_kept(cursor, _TRIGGERS_SQL, prefixes)),
        "procedures": _digest(procedure_rows + parameter_rows),
        "generators": _digest(_kept(cursor, _GENERATORS_SQL, prefixes)),
        "domains": _digest(domains),
    }


def preflight(connection: Any, models: Iterable[type[Model]], prefix: str) -> list[str]:
    """One message per model table that would collide. An empty list means it is safe to create them.

    A table collides when it already exists and its name does not start with prefix (the prefix
    namespace is HR's own, so re-running over HR tables is fine). An empty prefix makes every
    existing name a collision. Two models that map to the same table name also collide.
    Names are compared as Django would create them (quote_name), so long names get their hashed form.
    """
    own = prefix.upper()
    with connection.cursor() as cursor:
        existing = existing_tables(cursor)
    problems: list[str] = []
    owner_of: dict[str, str] = {}
    for model in models:
        table = str(connection.ops.quote_name(model._meta.db_table))
        label = model._meta.label
        if table in owner_of:
            problems.append(f"{label} and {owner_of[table]} both map to table {table}")
            continue
        owner_of[table] = label
        if table in existing and not (own and table.startswith(own)):
            problems.append(f"{label} would create table {table}, which already exists in the database")
    return problems
