"""Pure helpers for the Firebird cut-over routine (backup, restore check, report).

No Django imports on purpose: these functions are tested without a database.
Nothing here opens a database or runs a program; callers do that.
"""

from __future__ import annotations

SCRATCH_MARKERS: tuple[str, ...] = ("clone", "scratch", "restore-check")


def _file_name(path: str) -> str:
    """Return the file name part of a Windows or POSIX path."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def is_scratch_name(path: str) -> bool:
    """True when the file name (not the folder) contains a scratch marker.

    Case-insensitive. Only the file name is checked, so a folder called
    'clone_tests' does not make a live file look like a scratch copy.
    """
    name = _file_name(path).lower()
    return any(marker in name for marker in SCRATCH_MARKERS)


def refuse_live(path: str) -> None:
    """Raise ValueError unless the file name says it is a scratch copy."""
    if not is_scratch_name(path):
        raise ValueError(
            f"Refused: '{_file_name(path)}' does not look like a test copy. "
            "Only file names that contain 'clone', 'scratch' or 'restore-check' may be used, "
            "so the live MACS database is never touched."
        )


def gbak_database_name(host: str, port: str, name: str) -> str:
    """The name gbak connects with: 'host/port:path' when a port is set, 'host:path' otherwise, the bare path when
    there is no host (an embedded, local-file database)."""
    if not host:
        return name
    if port:
        return f"{host}/{port}:{name}"
    return f"{host}:{name}"


def gbak_backup_args(source: str, target: str, user: str) -> list[str]:
    """Argument list for a gbak backup. The password is NOT included; it goes in ISC_PASSWORD."""
    return ["-b", "-user", user, source, target]


def gbak_restore_args(source: str, target: str, user: str) -> list[str]:
    """Argument list for a gbak restore into a new scratch file.

    Raises ValueError if the target is not a scratch name, so a restore can
    never overwrite a live database.
    """
    refuse_live(target)
    return ["-c", "-user", user, source, target]


def compare_counts(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """One line per table whose row count differs or that is missing on either side.

    An empty list means the two sets of counts are equal.
    """
    lines: list[str] = []
    for table in sorted(set(before) | set(after)):
        if table not in after:
            lines.append(f"{table}: missing after restore (was {before[table]} rows)")
        elif table not in before:
            lines.append(f"{table}: not in the original backup (now {after[table]} rows)")
        elif before[table] != after[table]:
            lines.append(f"{table}: {before[table]} rows before, {after[table]} rows after")
    return lines


def redact(text: str, secret: str) -> str:
    """Replace every occurrence of a non-empty secret with '***'."""
    if not secret:
        return text
    return text.replace(secret, "***")
