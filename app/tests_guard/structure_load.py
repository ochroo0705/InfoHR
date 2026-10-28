"""Loading the production structure (D-018) into a test database in small committed chunks.

Loaded in one transaction, the script held ~5,300 of the server's 6,400 lock slots, so two loads at the
same moment (xdist workers, or two sessions running the suite) ran out of shared memory. Each chunk is
committed together with a note on the public schema saying how far the load got, so a load that stops
halfway carries on from there on the next run (--reuse-db) instead of failing on existing tables.
"""

import hashlib
import re
from pathlib import Path

STRUCTURE_SQL = Path(__file__).resolve().parents[2] / "db" / "schema" / "macs_public.sql"
STRUCTURE_CHUNK = 100  # statements per transaction: at most ~400 locks, so 8 loads at once still fit

_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|--[^\n]*|;")  # quoted text and comments are skipped whole
_NOTE = re.compile(r"info_hr structure ([0-9a-f]{12}): (\d+)/(\d+)")


class StructureChanged(Exception):
    """A half-finished load came from a different version of the structure script."""


def split_sql(script: str) -> list[str]:
    """The statements of a SQL script, split on semicolons outside quotes and comments."""
    statements, start = [], 0
    for token in _TOKEN.finditer(script):
        if token.group() == ";":
            statements.append(script[start : token.end()].strip())
            start = token.end()
    return statements


def chunked(script: str) -> tuple[str, list[str]]:
    """The script's short hash and its statements joined into chunks of STRUCTURE_CHUNK."""
    statements = split_sql(script)
    digest = hashlib.sha256(script.encode("utf-8")).hexdigest()[:12]
    return digest, ["\n".join(statements[i : i + STRUCTURE_CHUNK]) for i in range(0, len(statements), STRUCTURE_CHUNK)]


def loaded_note(digest: str, done: int, total: int) -> str:
    return f"info_hr structure {digest}: {done}/{total}"


def is_complete(note: str | None) -> bool:
    found = _NOTE.fullmatch(note or "")
    return found is not None and found[2] == found[3]


def chunks_left(note: str | None, loaded_whole: bool, digest: str, total: int) -> range:
    """Which chunks still need loading, from the schema note and whether production tables exist."""
    found = _NOTE.fullmatch(note or "")
    if found is None:
        # No note: a new database, or one loaded in a single transaction before chunks existed.
        return range(0) if loaded_whole else range(total)
    done, of = int(found[2]), int(found[3])
    if done == of:
        return range(0)
    if found[1] != digest or of != total:
        raise StructureChanged(
            "The test database holds a half-finished load of an older structure script. Rerun with --create-db."
        )
    return range(done, total)
