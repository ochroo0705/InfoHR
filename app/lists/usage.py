"""How many rows point at a list entry, across every table that has a foreign key to it
(production and hr). Read from the database catalogue so no link is missed (spec §5)."""

from collections.abc import Iterable

from django.db import connection
from django.db.models import Model

REFERENCES_SQL = """
select n.nspname, c.relname, a.attname
from pg_constraint k
join pg_class c on c.oid = k.conrelid
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = k.conrelid and a.attnum = k.conkey[1]
where k.contype = 'f' and k.confrelid = to_regclass(%s) and array_length(k.conkey, 1) = 1
"""

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


def usage_count(model: type[Model], pk: int, *, exclude_tables: Iterable[str] = ()) -> int:
    """Rows in any table referencing this list entry. `exclude_tables` names tables to leave out,
    such as the entry's own HR extension row, which is removed together with the entry."""
    table = model._meta.db_table
    skip = set(exclude_tables)
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
