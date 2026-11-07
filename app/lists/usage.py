"""How many rows point at a list entry, across every table that has a foreign key to it
(production and hr). Read from the database catalogue so no link is missed (spec §5)."""

import re
from collections.abc import Iterable

from django.db import connection
from django.db.models import Model
from macs.dialect import is_firebird

REFERENCES_SQL = """
select n.nspname, c.relname, a.attname
from pg_constraint k
join pg_class c on c.oid = k.conrelid
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = k.conrelid and a.attnum = k.conkey[1]
where k.contype = 'f' and k.confrelid = to_regclass(%s) and array_length(k.conkey, 1) = 1
"""

# Firebird: a foreign key is a RDB$REF_CONSTRAINTS row that links the referencing constraint to the unique or
# primary key of the referenced table. Only single-column keys count, as in the PostgreSQL query. The table
# name is a bound parameter; the result is the referencing table and column as the catalogue stores them.
FIREBIRD_REFERENCES_SQL = """
select trim(fk.RDB$RELATION_NAME), trim(seg.RDB$FIELD_NAME)
from RDB$REF_CONSTRAINTS ref
join RDB$RELATION_CONSTRAINTS fk on fk.RDB$CONSTRAINT_NAME = ref.RDB$CONSTRAINT_NAME
join RDB$RELATION_CONSTRAINTS uq on uq.RDB$CONSTRAINT_NAME = ref.RDB$CONST_NAME_UQ
join RDB$INDEX_SEGMENTS seg on seg.RDB$INDEX_NAME = fk.RDB$INDEX_NAME
where trim(fk.RDB$CONSTRAINT_TYPE) = 'FOREIGN KEY'
  and trim(uq.RDB$RELATION_NAME) = %s
  and (select count(*) from RDB$INDEX_SEGMENTS s2 where s2.RDB$INDEX_NAME = fk.RDB$INDEX_NAME) = 1
"""

# A plain Firebird identifier (letters, digits, underscore). Catalogue names are checked against it before they
# are put into SQL text; a name that does not match is an error, never silently skipped.
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# Columns with no foreign key in the production schema (Firebird never declared them),
# keyed by the list table's db_table. These are checked in addition to the catalogue.
EXTRA_REFERENCES: dict[str, list[tuple[str, str]]] = {
    "deps": [("employee_history", "dep_ident"), ("movement", "old_depid"), ("movement", "new_depid")],
    "occupation": [
        ("employee_history", "occupation_ident"),
        ("movement", "old_occupid"),
        ("movement", "new_occupid"),
    ],
    "education": [("employee_history", "education_ident")],
    "graduate": [("employee_history", "graduate_ident")],
    "fired_reason": [("employee_history", "firedreason_ident")],
}


def _declared_references(table: str) -> list[tuple[str, str, str]]:
    """Production columns that the macs models declare as a foreign key to this table, even where the
    schema itself has none (the employee's marital status, nationality, ... were never constrained)."""
    from django.apps import apps
    from django.db.models import ForeignKey

    found = []
    for model in apps.get_models():
        if model._meta.app_label != "macs":
            continue
        for field in model._meta.concrete_fields:
            related = field.related_model
            if isinstance(field, ForeignKey) and isinstance(related, type) and related._meta.db_table == table:
                found.append(("public", model._meta.db_table, field.column))
    return found


def _firebird_name(name: str) -> str:
    """A Firebird identifier as the catalogue stores it (upper case when unquoted), checked before use in SQL."""
    if not _SAFE_NAME.match(name):
        raise ValueError(f"unexpected identifier in the Firebird catalogue: {name!r}")
    return name.lower()


def _firebird_references(table: str) -> list[tuple[str, str]]:
    """(table, column) pairs of every single-column foreign key that points at `table`, as lower-case names."""
    with connection.cursor() as c:
        c.execute(FIREBIRD_REFERENCES_SQL, [connection.ops.quote_name(table)])
        return [(_firebird_name(t), _firebird_name(col)) for t, col in c.fetchall()]


def _usage_count_firebird(table: str, pk: int, skip: set[str]) -> int:
    references = _firebird_references(table)
    references += EXTRA_REFERENCES.get(table, [])
    references += [(t, col) for _, t, col in _declared_references(table)]
    total = 0
    with connection.cursor() as c:
        for ref_table, column in sorted(set(references)):
            if ref_table in skip:
                continue
            # Both names are validated above and quoted by the backend; the value is a bound parameter.
            c.execute(
                f"select count(*) from {connection.ops.quote_name(ref_table)} "  # noqa: S608
                f"where {connection.ops.quote_name(column)} = %s",
                [pk],
            )
            total += c.fetchone()[0]
    return total


def usage_count(model: type[Model], pk: int, *, exclude_tables: Iterable[str] = ()) -> int:
    """Rows in any table referencing this list entry. `exclude_tables` names tables to leave out,
    such as the entry's own HR extension row, which is removed together with the entry."""
    table = model._meta.db_table
    skip = set(exclude_tables)
    if is_firebird():
        return _usage_count_firebird(table, pk, skip)
    total = 0
    with connection.cursor() as c:
        c.execute(REFERENCES_SQL, [table])
        references = [(s, t, col) for s, t, col in c.fetchall() if t not in skip]
        references += [("public", t, col) for t, col in EXTRA_REFERENCES.get(table, []) if t not in skip]
        references += [ref for ref in _declared_references(table) if ref[1] not in skip]
        for schema, ref_table, column in sorted(set(references)):
            c.execute(f'select count(*) from "{schema}"."{ref_table}" where "{column}" = %s', [pk])  # noqa: S608
            total += c.fetchone()[0]
    return total
