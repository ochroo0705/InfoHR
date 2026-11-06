"""Firebird emulation of Django's conditional (partial) unique constraints (checklists, plan Task 6).

Firebird cannot create a partial unique index, so Django skips a UniqueConstraint with a condition and
warns models.W036. Each such rule is emulated by a UNIQUE index over a COMPUTED BY expression:

    CREATE UNIQUE INDEX <index_name> ON <table> COMPUTED BY (IIF(<condition>, <key>, NULL))

A row that fails the condition gets NULL as its key, and a unique index allows many NULLs, so only
rows that meet the condition can collide. A NULL in a key column also makes the key NULL.

Dialect 1 has no quoted identifiers, so the column names are written as plain Firebird identifiers
(Django's Field.column names, which Firebird compares case-insensitively). A key of several columns
is built as text: CAST(col AS VARCHAR(20)) || ':' || col2. Each column is cast to 20 characters, so
every key column must be short (an id or a choice value); a longer text column needs its own rule.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_INDEX_NAME = 31  # Firebird identifier limit for an index name
KEY_CAST_WIDTH = 20  # VARCHAR width for each key column of a multi-column key


@dataclass(frozen=True)
class EmulatedUnique:
    name: str  # the Django UniqueConstraint name (the key in EMULATED)
    model_label: str  # "app_label.ModelName" that declares the constraint
    columns: tuple[str, ...]  # key columns, as Firebird column names
    condition_sql: str  # the Django condition, written in SQL with the same column names
    index_name: str  # the Firebird index name, at most 31 characters

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError(f"{self.name}: a unique rule needs at least one key column")
        if len(self.index_name) > MAX_INDEX_NAME:
            raise ValueError(f"{self.name}: index name {self.index_name!r} is longer than {MAX_INDEX_NAME} characters")
        if not self.index_name.replace("_", "").isalnum() or not self.index_name[0].isalpha():
            raise ValueError(f"{self.name}: index name {self.index_name!r} must be letters, digits and underscores")


EMULATED: dict[str, EmulatedUnique] = {
    "checklist_tpl_one_default": EmulatedUnique(
        name="checklist_tpl_one_default",
        model_label="checklists.ChecklistTemplate",
        columns=("kind",),
        condition_sql="is_default = TRUE",
        index_name="IHR_CKL_TPL_DEFAULT",
    ),
    "checklist_one_open_emp_kind": EmulatedUnique(
        name="checklist_one_open_emp_kind",
        model_label="checklists.Checklist",
        columns=("employee_id", "kind"),
        condition_sql="state = 'open'",
        index_name="IHR_CKL_ONE_OPEN",
    ),
}


def _key_sql(columns: tuple[str, ...]) -> str:
    if len(columns) == 1:
        return columns[0]
    parts = [f"CAST({column} AS VARCHAR({KEY_CAST_WIDTH}))" for column in columns]
    return " || ':' || ".join(parts)


def create_sql(db_table: str, spec: EmulatedUnique) -> str:
    """CREATE UNIQUE INDEX statement for one rule. db_table is the real, already-prefixed table name."""
    return (
        f"CREATE UNIQUE INDEX {spec.index_name} ON {db_table} "
        f"COMPUTED BY (IIF({spec.condition_sql}, {_key_sql(spec.columns)}, NULL))"
    )


def drop_sql(spec: EmulatedUnique) -> str:
    """DROP INDEX statement for one rule."""
    return f"DROP INDEX {spec.index_name}"
