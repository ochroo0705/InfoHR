"""Reserved words and non-letter names as SQL aliases (firebird3-foundation Task 11, R28 and R30).

Django names a SELECT alias after a field, so a many-to-many ``user.groups.add(group)`` emits
``... AS GROUP``, which Firebird rejects as an unquoted token. ``quote_name`` maps such a name to
a safe one. Django's aggregates use the alias ``__count``, which Firebird rejects because an
identifier must start with a letter; ``quote_name`` prefixes such names with ``U`` (R30).

These tests check the mapping, the word list against the server (as an alias, a column definition,
a table name and a column reference), the list against Firebird's own keyword changelog, that no
real HR or MACS name is on the list or starts with a non-letter, and the many-to-many and count
paths end to end.
"""

from pathlib import Path
from typing import Any

import pytest
from django.apps import apps
from django.db import DatabaseError, connections, models
from django.test.utils import isolate_apps
from firebird.driver import DatabaseError as DriverDatabaseError  # type: ignore[import-untyped]

from infohr_firebird.reserved import RESERVED_SUFFIX, RESERVED_WORDS

ORDINARY_WORDS = ["name", "code", "status", "kind", "note", "text", "amount", "qty", "title", "id"]
MUST_BE_RESERVED = {"GROUP", "AT", "DATE", "DAY", "ORDER", "POSITION", "SENSITIVE", "VALUE"}
MAX_NAME_LENGTH = 31
CHANGELOG = Path(r"C:\Program Files\Firebird\Firebird_3_0\doc\sql.extensions\README.keywords.txt")


def _accepted_as_alias(cursor: Any, word: str) -> bool:
    """True when Firebird accepts the word as an unquoted alias; False when it reports it as unknown."""
    try:
        cursor.execute(f"select 1 as {word} from rdb$database")  # noqa: S608 - word comes from our own list
    except DatabaseError as error:
        if "Token unknown" in str(error):
            return False
        raise
    return True


def _probe_sql(word: str) -> dict[str, str]:
    """One statement per grammar position where Django puts an identifier. Firebird only prepares them."""
    return {
        "alias": f"select 1 as {word} from rdb$database",  # noqa: S608 - words come from our own list
        "column definition": f"create table IHR_PROBE_RW ({word} integer)",  # noqa: S608 - our own list
        "table name": f"create table {word} (probe integer)",  # noqa: S608 - our own list
        "column reference": f"select 1 from rdb$database t where t.{word} = 1",  # noqa: S608 - our own list
    }


def _prepare_error(raw_connection: Any, sql: str) -> str | None:
    """Ask the server to prepare the statement without running it. None when it prepares."""
    try:
        statement = raw_connection.cursor().prepare(sql)
    except DriverDatabaseError as error:
        return str(error)
    statement.free()
    return None


def _rejected_by_grammar(error: str | None) -> bool:
    return error is not None and "Token unknown" in error


def _accepted_by_grammar(error: str | None) -> bool:
    """The word parsed: the statement prepares, or it fails only because a table or column is unknown."""
    return error is None or "Column unknown" in error or "Table unknown" in error


def _changelog_reserved_words(path: Path) -> set[str]:
    """Replay Firebird's keyword changelog (1.0 to 3.0) and return the words that end up reserved."""
    reserved: set[str] = set()
    mode: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("Firebird "):
            mode = None
        elif line.startswith(("Added as reserved words", "Moved from non-reserved words to reserved")):
            mode = "add"
        elif line.startswith(("Moved from reserved words to non-reserved", "Removed reserved words")):
            mode = "remove"
        elif line.startswith("Added as non-reserved words"):
            mode = None
        elif mode and line and raw.startswith("    "):
            word = line.split()[0]
            if mode == "add":
                reserved.add(word)
            else:
                reserved.discard(word)
    return reserved


def _drop_tables(connection: Any, *models_to_drop: Any) -> None:
    """Drop the tables of the given models that exist (a failed create must not leak a table)."""
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in models_to_drop:
            if model._meta.db_table in existing:
                editor.delete_model(model)


def _define_group_user() -> tuple[Any, Any]:
    """Throwaway pair: Group(name) and RwUser(name) with groups = M2M(Group); the through table has an FK named group.

    Call it inside an @isolate_apps("infohr_firebird") test.
    """

    class Group(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        name = models.CharField(max_length=50)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_RW_GROUP"

    class RwUser(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        name = models.CharField(max_length=50)
        groups = models.ManyToManyField(Group, db_table="IHR_T_RW_UG")

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_RW_USER"

    return Group, RwUser


def test_quote_name_mangles_reserved_words(fb_alias: str) -> None:
    ops = connections[fb_alias].ops
    assert ops.quote_name("group") == "GROUP_RW"
    assert ops.quote_name('"value"') == "VALUE_RW"
    assert ops.quote_name("name") == "NAME"
    assert ops.quote_name("RDB$DB_KEY") == "RDB$DB_KEY"
    for word in sorted(RESERVED_WORDS):
        mangled = ops.quote_name(word)
        assert len(mangled) <= MAX_NAME_LENGTH, mangled
        assert mangled == word + RESERVED_SUFFIX, mangled
        assert mangled not in RESERVED_WORDS, mangled


def test_quote_name_prefixes_non_letter_names(fb_alias: str) -> None:
    ops = connections[fb_alias].ops
    assert ops.quote_name("__count") == "U__COUNT"
    assert ops.quote_name("1st") == "U1ST"
    assert ops.quote_name("name") == "NAME"
    assert ops.quote_name("Ab") == "AB"
    long_name = ops.quote_name("_" + "a" * 40)
    assert len(long_name) <= MAX_NAME_LENGTH, long_name
    assert long_name.startswith("U_"), long_name
    assert long_name == ops.quote_name("_" + "a" * 40), "the mapping must be deterministic"


def test_quote_name_empty_name_stays_empty(fb_alias: str) -> None:
    assert connections[fb_alias].ops.quote_name("") == ""


def test_quote_name_upper_expansion_fits(fb_alias: str) -> None:
    ops = connections[fb_alias].ops
    name = "a" * 30 + "ß"  # 31 characters; upper-casing turns the ß into SS, making 32
    result = ops.quote_name(name)
    assert len(result) <= MAX_NAME_LENGTH, result
    assert result == ops.quote_name(name), "the mapping must be deterministic"
    assert ops.quote_name("a" * 31) == "A" * 31, "an ASCII name of 31 characters is unchanged"


def test_reserved_list_matches_the_server(fb_alias: str) -> None:
    accepted_reserved: list[str] = []
    rejected_ordinary: list[str] = []
    with connections[fb_alias].cursor() as cursor:
        for word in sorted(RESERVED_WORDS):
            if _accepted_as_alias(cursor, word):
                accepted_reserved.append(word)
        for word in ORDINARY_WORDS:
            if not _accepted_as_alias(cursor, word):
                rejected_ordinary.append(word)
    assert accepted_reserved == [], f"listed but accepted by Firebird as aliases: {accepted_reserved}"
    assert rejected_ordinary == [], f"ordinary words rejected by Firebird: {rejected_ordinary}"
    missing = sorted(MUST_BE_RESERVED - RESERVED_WORDS)
    assert missing == [], f"known reserved words missing from the list: {missing}"


def test_reserved_words_are_rejected_in_every_position(fb_alias: str) -> None:
    connections[fb_alias].ensure_connection()
    raw = connections[fb_alias].connection
    accepted: list[str] = []
    for word in sorted(RESERVED_WORDS):
        for position, sql in _probe_sql(word).items():
            error = _prepare_error(raw, sql)
            if not _rejected_by_grammar(error):
                first = (error or "prepared").splitlines()[0] if error else "prepared"
                accepted.append(f"{word} as {position}: {first}")
    assert accepted == [], f"reserved words the server accepts in some position: {accepted}"


def test_ordinary_words_are_accepted_in_every_position(fb_alias: str) -> None:
    connections[fb_alias].ensure_connection()
    raw = connections[fb_alias].connection
    rejected: list[str] = []
    for word in ORDINARY_WORDS:
        for position, sql in _probe_sql(word).items():
            error = _prepare_error(raw, sql)
            if not _accepted_by_grammar(error):
                rejected.append(f"{word} as {position}: {(error or '').splitlines()[0]}")
    assert rejected == [], f"ordinary words the server rejects: {rejected}"


def test_reserved_list_covers_firebird_changelog() -> None:
    if not CHANGELOG.is_file():
        pytest.skip(f"Firebird keyword changelog not found: {CHANGELOG}")
    expected = {word for word in _changelog_reserved_words(CHANGELOG) if "$" not in word}
    assert {"CURRENT_USER", "BIGINT", "SIMILAR", "REGR_R2"} <= expected, "the changelog parser misses known words"
    missing = sorted(expected - RESERVED_WORDS)
    assert missing == [], f"reserved in Firebird's keyword changelog but not in the list: {missing}"


def test_no_hr_or_macs_table_or_column_is_reserved(fb_alias: str) -> None:
    names: dict[str, str] = {}
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not (meta.managed or meta.app_label == "macs"):
            continue
        names.setdefault(meta.db_table.upper(), f"table {meta.label}")
        for field in meta.concrete_fields:
            names.setdefault(field.column.upper(), f"column {meta.label}.{field.name}")

    with connections[fb_alias].cursor() as cursor:
        cursor.execute(
            "select r.rdb$relation_name, f.rdb$field_name "
            "from rdb$relations r "
            "left join rdb$relation_fields f on f.rdb$relation_name = r.rdb$relation_name "
            "where coalesce(r.rdb$system_flag, 0) = 0"
        )
        for relation, column in cursor.fetchall():
            names.setdefault(str(relation).strip().upper(), "template table")
            if column is not None:
                names.setdefault(str(column).strip().upper(), f"template column of {str(relation).strip()}")

    violations = [f"{name} ({where})" for name, where in sorted(names.items()) if name in RESERVED_WORDS]
    assert violations == [], f"names that are Firebird reserved words: {violations}"
    # R30: an identifier must start with a letter, or Firebird rejects it; quote_name would prefix it with U.
    non_letter = [f"{name} ({where})" for name, where in sorted(names.items()) if not "A" <= name[:1] <= "Z"]
    assert non_letter == [], f"names that do not start with a letter: {non_letter}"


@isolate_apps("infohr_firebird")
def test_many_to_many_add_with_reserved_alias(fb_alias: str) -> None:
    Group, RwUser = _define_group_user()
    connection = connections[fb_alias]
    try:
        with connection.schema_editor() as editor:
            editor.create_model(Group)
            editor.create_model(RwUser)  # also creates the auto through table IHR_T_RW_UG
        group = Group(name="Staff")
        group.save(using=fb_alias)
        user = RwUser(name="Ulzii")
        user.save(using=fb_alias)
        user.groups.add(group)
        user.groups.add(group)  # the second add must not fail or duplicate the row
        assert list(user.groups.all()) == [group]
        assert len(user.groups.all()) == 1
        user.groups.remove(group)
        assert len(user.groups.all()) == 0
    finally:
        _drop_tables(connection, RwUser, Group)


@isolate_apps("infohr_firebird")
def test_count_and_aggregates_work(fb_alias: str) -> None:
    Group, RwUser = _define_group_user()
    connection = connections[fb_alias]
    try:
        with connection.schema_editor() as editor:
            editor.create_model(Group)
            editor.create_model(RwUser)
        for name in ("Staff", "Sales", "Admin"):
            Group(name=name).save(using=fb_alias)
        user = RwUser(name="Ulzii")
        user.save(using=fb_alias)
        user.groups.add(*Group.objects.using(fb_alias).filter(name__in=["Staff", "Sales"]))

        assert Group.objects.using(fb_alias).count() == 3
        assert Group.objects.using(fb_alias).filter(name__startswith="S").count() == 2
        assert user.groups.count() == 2
        assert user.groups.exists()
        assert Group.objects.using(fb_alias).exists()
        assert not Group.objects.using(fb_alias).filter(name="Nobody").exists()
    finally:
        _drop_tables(connection, RwUser, Group)
