"""SQL that differs between PostgreSQL and Firebird (plan 3, Task 9).

The write functions run raw SQL in both databases. Two statements differ:
- a generator (sequence) value: PostgreSQL `nextval`, Firebird `gen_id`;
- a row lock on a select: PostgreSQL `FOR UPDATE`, Firebird `WITH LOCK` (placed at the end of the statement).

The mode is `settings.DB_ENGINE`, as in `macs.triggers`. Generator names come from a fixed allow-list in this
module, never from user input.
"""

from __future__ import annotations

import functools
import operator
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import CharField, Q, TextField
from django.db.models.lookups import Contains, IContains, PatternLookup, StartsWith
from django.db.models.sql.compiler import SQLCompiler

# PostgreSQL sequence name -> Firebird generator name.
GENERATORS: dict[str, str] = {
    "gen_employee_history_id": "GEN_EMPLOYEE_HISTORY_ID",
}


def is_firebird() -> bool:
    return bool(settings.DB_ENGINE == "firebird")


_LIKE_ESCAPE = "!"  # the escape character of the Firebird-safe LIKE (Firebird refuses a backslash in this clause)


def _escape(word: str) -> str:
    """The typed word with the escape character, % and _ escaped, so the typed text is plain text (as Django does)."""
    escaped = word.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
    return escaped.replace("%", _LIKE_ESCAPE + "%").replace("_", _LIKE_ESCAPE + "_")


class _FirebirdLikeMixin(PatternLookup):
    """Firebird LIKE with the pattern cast to its own size. Firebird binds a LIKE pattern at the declared length of
    the column it is compared with, so a pattern longer than that column (a 10-character code, a 9-character word)
    raises -303 (string truncation). The cast removes that limit; the match itself is the same as Django's."""

    def _pattern(self, word: str) -> str:
        return f"%{_escape(word)}%"

    def process_rhs(self, compiler: SQLCompiler, connection: BaseDatabaseWrapper) -> tuple[str, Any]:
        if not self.rhs_is_direct_value():
            return super().process_rhs(compiler, connection)
        pattern = self._pattern(str(self.rhs))
        return f"CAST(%s AS VARCHAR({len(pattern)}))", [pattern]


class _FirebirdContains(_FirebirdLikeMixin, Contains):
    lookup_name = "fb_contains"

    def get_rhs_op(self, connection: BaseDatabaseWrapper, rhs: str) -> str:
        if not self.rhs_is_direct_value():
            return super().get_rhs_op(connection, rhs)
        return f"LIKE {rhs} ESCAPE '{_LIKE_ESCAPE}'"


class _FirebirdIContains(_FirebirdLikeMixin, IContains):
    lookup_name = "fb_icontains"

    def process_lhs(
        self, compiler: SQLCompiler, connection: BaseDatabaseWrapper, lhs: Any = None
    ) -> tuple[str, list[Any]]:
        # Django upper-cases the column only for the built-in name "icontains"; this name needs it added here.
        lhs_sql, params = super().process_lhs(compiler, connection, lhs)
        return f"UPPER({lhs_sql})", list(params)

    def get_rhs_op(self, connection: BaseDatabaseWrapper, rhs: str) -> str:
        if not self.rhs_is_direct_value():
            return super().get_rhs_op(connection, rhs)
        return f"LIKE UPPER({rhs}) ESCAPE '{_LIKE_ESCAPE}'"


class _FirebirdStartsWith(_FirebirdLikeMixin, StartsWith):
    lookup_name = "fb_startswith"

    def _pattern(self, word: str) -> str:
        return f"{_escape(word)}%"

    def get_rhs_op(self, connection: BaseDatabaseWrapper, rhs: str) -> str:
        if not self.rhs_is_direct_value():
            return super().get_rhs_op(connection, rhs)
        return f"LIKE {rhs} ESCAPE '{_LIKE_ESCAPE}'"


for _field in (CharField, TextField):
    _field.register_lookup(_FirebirdContains)
    _field.register_lookup(_FirebirdIContains)
    _field.register_lookup(_FirebirdStartsWith)


# A search word longer than this cannot be in any column (every column is shorter), so it matches nothing. The cut-off
# also keeps the pattern well inside Firebird's VARCHAR limit (about 8191 UTF8 characters), which the CAST in
# _FirebirdLikeMixin would otherwise exceed (Dynamic SQL Error, implementation limit exceeded).
MAX_SEARCH_CHARS = 4000


def _no_match() -> Q:
    """A condition that matches no row on either database, and that combines with | and & like any other Q."""
    return Q(pk__in=[])


def search_match(word: str, *fields: str, icase: bool = False) -> Q:
    """Rows where any of `fields` contains the typed `word` (ignoring case when `icase`). Same lookups as `contains` /
    `icontains` on PostgreSQL; on Firebird the Firebird-safe lookups above. The word is still escaped as before, so
    % and _ are plain text. A word longer than MAX_SEARCH_CHARS matches nothing on both databases."""
    if len(word) > MAX_SEARCH_CHARS:
        return _no_match()
    name = ("fb_" if is_firebird() else "") + ("icontains" if icase else "contains")
    return functools.reduce(operator.or_, (Q(**{f"{field}__{name}": word}) for field in fields))


def search_prefix(word: str, *fields: str) -> Q:
    """Rows where any of `fields` starts with the typed `word` (`startswith` on PostgreSQL, Firebird-safe there).
    A word longer than MAX_SEARCH_CHARS matches nothing, as in search_match."""
    if len(word) > MAX_SEARCH_CHARS:
        return _no_match()
    name = "fb_startswith" if is_firebird() else "startswith"
    return functools.reduce(operator.or_, (Q(**{f"{field}__{name}": word}) for field in fields))


def next_value(generator: str) -> int:
    """Take the next value of a generator. The name must be in GENERATORS (ValueError otherwise)."""
    if generator not in GENERATORS:
        raise ValueError(f"unknown generator: {generator!r}; add it to macs.dialect.GENERATORS")
    with connection.cursor() as cur:
        if is_firebird():
            # The name is a constant from GENERATORS, so interpolating it is safe.
            cur.execute(f"select gen_id({GENERATORS[generator]}, 1) from rdb$database")
        else:
            cur.execute("select nextval(%s)", [generator])
        return int(cur.fetchone()[0])


def lock_suffix() -> str:
    """The clause that locks the rows a SELECT returns, appended to the statement (after ORDER BY)."""
    return " WITH LOCK" if is_firebird() else " FOR UPDATE"


def physical_order() -> str:
    """The ORDER BY expression for a table's rows in the order they were stored: `ctid` on PostgreSQL, `RDB$DB_KEY`
    on Firebird. A constant string, never user input."""
    return "RDB$DB_KEY" if is_firebird() else "ctid"
