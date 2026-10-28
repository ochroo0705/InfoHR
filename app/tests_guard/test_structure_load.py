"""The production structure loads into test databases in small committed chunks, so parallel loads
(xdist workers, two sessions at once) fit in the server's lock table and a broken load resumes."""

import pytest
import sqlparse
from django.db import connection

from tests_guard.structure_load import (
    STRUCTURE_CHUNK,
    STRUCTURE_SQL,
    StructureChanged,
    chunked,
    chunks_left,
    is_complete,
    loaded_note,
    split_sql,
)


def test_split_matches_sqlparse_on_the_real_structure() -> None:
    script = STRUCTURE_SQL.read_text(encoding="utf-8")
    assert split_sql(script) == [s.strip() for s in sqlparse.split(script) if s.strip()]


def test_split_ignores_semicolons_in_quotes_and_comments() -> None:
    script = "-- note; with a semicolon\nselect ';';\nselect \"a;b\" from t;\nselect 'it''s; fine';\n"
    assert split_sql(script) == [
        "-- note; with a semicolon\nselect ';';",
        'select "a;b" from t;',
        "select 'it''s; fine';",
    ]


def test_chunks_hold_at_most_the_chunk_size() -> None:
    _, chunks = chunked("select 1;\n" * (STRUCTURE_CHUNK * 2 + 1))
    assert [len(split_sql(c)) for c in chunks] == [STRUCTURE_CHUNK, STRUCTURE_CHUNK, 1]


@pytest.mark.parametrize(
    ("note", "loaded_whole", "expected"),
    [
        (None, False, range(5)),  # fresh database
        ("standard public schema", False, range(5)),  # PostgreSQL's own comment on a new database
        (loaded_note("abc123abc123", 2, 5), True, range(2, 5)),  # an earlier load stopped after chunk 2
        (loaded_note("abc123abc123", 5, 5), True, range(0)),  # done
        (loaded_note("000000000000", 5, 5), True, range(0)),  # done from an older file: kept, like before
        (None, True, range(0)),  # loaded in one go before chunks existed
    ],
)
def test_chunks_left(note: str | None, loaded_whole: bool, expected: range) -> None:
    assert chunks_left(note, loaded_whole, "abc123abc123", 5) == expected


@pytest.mark.parametrize("note", [loaded_note("000000000000", 2, 5), loaded_note("abc123abc123", 2, 6)])
def test_partial_load_of_another_file_is_refused(note: str) -> None:
    with pytest.raises(StructureChanged, match="--create-db"):
        chunks_left(note, True, "abc123abc123", 5)


def test_is_complete() -> None:
    assert is_complete(loaded_note("abc123abc123", 5, 5))
    assert not is_complete(loaded_note("abc123abc123", 4, 5))
    assert not is_complete(None)
    assert not is_complete("standard public schema")


@pytest.mark.django_db
def test_test_database_is_marked_fully_loaded() -> None:
    digest, chunks = chunked(STRUCTURE_SQL.read_text(encoding="utf-8"))
    with connection.cursor() as c:
        c.execute("select obj_description('public'::regnamespace, 'pg_namespace')")
        assert c.fetchone()[0] == loaded_note(digest, len(chunks), len(chunks))
