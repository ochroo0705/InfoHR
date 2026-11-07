"""fb_cutover: back up the MACS Firebird database, prove that the backup restores, and print the cut-over report.

    manage.py fb_cutover backup --to FILE.fbk [--database ALIAS]
    manage.py fb_cutover restore-check --backup FILE.fbk --scratch FILE.fdb [--database ALIAS]
    manage.py fb_cutover report [--snapshot FILE]

backup counts the rows of every user table before gbak starts and writes them to FILE.fbk.counts.json once gbak
has succeeded. restore-check compares the restored copy with that file, so MACS saves made after the backup do not
make it differ. Without that file it counts the live database instead and says so.

gbak is found through settings.FB_GBAK. The login is FB_ADMIN_USER (default SYSDBA) and the password is
FB_ADMIN_PASSWORD; the password reaches gbak only through the ISC_PASSWORD variable of its environment, never on
the command line. Every line this command prints, and every error text, goes through redact().

The pure helpers (scratch-name guard, gbak argument lists, count comparison, redaction) live in infohr_firebird.cutover.
The structure, trigger and clock checks are the existing fb_guard verify, macs.triggers EXPECTED through
check_macs_triggers, and check_server_time_zone; this command only calls them.
"""

import json
import os
import re
import subprocess
from io import StringIO
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError
from django.db.utils import ConnectionHandler
from macs.triggers import EXPECTED as MACS_TRIGGERS

from infohr_firebird.checks import check_macs_triggers, check_server_time_zone
from infohr_firebird.cutover import (
    compare_counts,
    gbak_backup_args,
    gbak_database_name,
    gbak_restore_args,
    redact,
    refuse_live,
)

ENGINE = "infohr_firebird"
# Dialect 1 names are plain upper-case identifiers. A name outside this form is refused before it goes into SQL.
PLAIN_NAME = re.compile(r"[A-Z][A-Z0-9_$]*")
# Every user table: not a system table, not a view. rdb$view_source is null for tables.
USER_TABLES_SQL = (
    "select trim(rdb$relation_name) from rdb$relations"
    " where coalesce(rdb$system_flag, 0) = 0 and rdb$view_source is null order by 1"
)

CheckResult = tuple[str, bool, str]  # (check name, passed, one-line detail)
# The row counts taken at backup time sit next to the backup file, under this suffix.
COUNTS_SUFFIX = ".counts.json"


def _counts_path(backup_path: str) -> str:
    return backup_path + COUNTS_SUFFIX


def _write_counts(path: str, counts: dict[str, int]) -> None:
    """Write the counts file as new (never overwrites). The counts are row numbers only, no customer data."""
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(counts, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _read_counts(path: str) -> dict[str, int]:
    """Read a counts file written by _write_counts. Anything else is refused, with no fallback to the live database."""
    if not Path(path).is_file():
        raise CommandError(f"restore-check refused: {path} exists but is not a regular file.")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CommandError(f"restore-check refused: the counts file {path} cannot be read ({exc}).") from None
    valid = (
        isinstance(data, dict)
        and bool(data)
        and all(
            isinstance(name, str) and isinstance(count, int) and not isinstance(count, bool)
            for name, count in data.items()
        )
    )
    if not valid:
        raise CommandError(
            f"restore-check refused: the counts file {path} is empty or does not hold table row counts. "
            "It is not replaced by a live count; take a new backup."
        )
    return dict(data)


def _gbak_name(config: dict[str, Any], path: str) -> str:
    """The name gbak uses for a Firebird file: through the server (host and port) when the settings have a host."""
    return gbak_database_name(str(config.get("HOST") or ""), str(config.get("PORT") or ""), path)


def _admin_user() -> str:
    return os.environ.get("FB_ADMIN_USER", "").strip() or "SYSDBA"


def _admin_password() -> str:
    return os.environ.get("FB_ADMIN_PASSWORD", "")


def _is_firebird_default() -> bool:
    return str(settings.DATABASES["default"]["ENGINE"]) == ENGINE


def _firebird_config(alias: str) -> dict[str, Any]:
    """A copy of the settings of one Firebird database alias. Refuses any other engine."""
    if alias not in settings.DATABASES:
        raise CommandError(f"no database alias {alias!r} in the settings")
    config: dict[str, Any] = dict(settings.DATABASES[alias])
    if config.get("ENGINE") != ENGINE:
        raise CommandError(f"database alias {alias!r} is not a Firebird database (ENGINE is {config.get('ENGINE')})")
    return config


def _run_gbak(args: list[str], password: str) -> tuple[int, str]:
    """Run gbak with the password in ISC_PASSWORD. Returns the exit code and the redacted output."""
    gbak = str(settings.FB_GBAK)
    if not Path(gbak).is_file():
        raise CommandError(f"gbak not found at {gbak}. Set FB_GBAK to the full path of gbak.exe.")
    env = {**os.environ, "ISC_PASSWORD": password}
    proc = subprocess.run(  # noqa: S603 (fixed program from settings; arguments built here, password not among them)
        [gbak, *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = "\n".join(line for line in (proc.stdout + proc.stderr).splitlines() if line.strip())
    return proc.returncode, redact(output, password)


def _row_counts(config: dict[str, Any]) -> dict[str, int]:
    """Row count of every user table, with plain select count(*) over a direct connection built from the settings."""
    handler = ConnectionHandler({"default": dict(config)})  # Django's handler insists on a 'default' alias
    connection = handler["default"]
    try:
        with connection.cursor() as cursor:
            cursor.execute(USER_TABLES_SQL)
            names = [str(row[0]) for row in cursor.fetchall()]
            counts: dict[str, int] = {}
            for name in names:
                if PLAIN_NAME.fullmatch(name) is None:
                    raise CommandError(f"table name {name!r} is not a plain identifier; cannot count it safely")
                cursor.execute(f"select count(*) from {name}")  # noqa: S608 (name checked above)
                counts[name] = int(cursor.fetchone()[0])
        return counts
    finally:
        connection.close()


def _guarded(name: str, check: Any) -> CheckResult:
    """Run one report check. A failure becomes a FAIL line with its reason, so the report itself never crashes."""
    try:
        result: CheckResult = check()
    except Exception as exc:  # a report must not crash; the reason is printed and the result is NOT READY
        return (name, False, f"could not run: {exc}")
    return result


class Command(BaseCommand):
    help = "Back up the MACS Firebird database, prove a backup restores, and print the cut-over readiness report."
    requires_system_checks = []
    _secret = ""  # the FB_ADMIN_PASSWORD of this run; every printed line and error text is redacted with it

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["backup", "restore-check", "report"])
        parser.add_argument("--database", default="default", help="database alias (default: default)")
        parser.add_argument("--to", default=None, help="backup: the new .fbk file to write (must not exist yet)")
        parser.add_argument("--backup", default=None, help="restore-check: the .fbk file to restore")
        parser.add_argument(
            "--scratch",
            default=None,
            help="restore-check: a new scratch .fdb file; its name must contain clone, scratch or restore-check",
        )
        parser.add_argument("--snapshot", default=None, help="report: the fb_guard snapshot JSON file")

    def handle(self, *args: Any, **options: Any) -> None:
        self._secret = _admin_password()
        action = str(options["action"])
        alias = str(options["database"])
        try:
            if action == "backup":
                self._backup(alias, options.get("to"))
            elif action == "restore-check":
                self._restore_check(alias, options.get("backup"), options.get("scratch"))
            else:
                self._report(options.get("snapshot"))
        except CommandError as exc:
            raise CommandError(redact(str(exc), self._secret)) from None
        except (DatabaseError, OSError, ValueError) as exc:
            raise CommandError(redact(f"{action} failed: {exc}", self._secret)) from None

    def _say(self, text: str) -> None:
        self.stdout.write(redact(text, self._secret))

    def _backup(self, alias: str, to: Any) -> None:
        if not to:
            raise CommandError("backup needs --to FILE.fbk (a new file name)")
        target = os.path.abspath(str(to))
        config = _firebird_config(alias)
        if Path(target).exists():
            raise CommandError(
                f"backup refused: {target} already exists. Choose a new file name; "
                "an existing backup is never overwritten."
            )
        if not Path(target).parent.is_dir():
            raise CommandError(f"backup refused: the folder {Path(target).parent} does not exist.")
        password = _admin_password()
        if not password:
            raise CommandError(
                "backup refused: FB_ADMIN_PASSWORD is not set. Set it for this command only; "
                "it is never written to a file or printed. The database was not touched."
            )
        counts_path = _counts_path(target)
        if Path(counts_path).exists():
            raise CommandError(
                f"backup refused: {counts_path} already exists. Choose a new file name; "
                "an existing counts file is never overwritten."
            )
        # Counted before gbak starts, so the counts describe the file that gbak is about to back up.
        counts = _row_counts(config)
        if not counts:
            raise CommandError(f"backup refused: the database {alias!r} has no user tables to count.")
        source = _gbak_name(config, str(config["NAME"]))
        code, output = _run_gbak(gbak_backup_args(source, target, _admin_user()), password)
        if output:
            self._say(output)
        if code != 0:
            if Path(target).exists():  # written by this run only: the name did not exist before it started
                Path(target).unlink()
            raise CommandError(
                f"backup failed: gbak exited with code {code}. No backup file was kept; "
                "the live database was only read."
            )
        try:
            _write_counts(counts_path, counts)
        except OSError as exc:
            # Both files were created by this run (the names did not exist before it started): remove any partial
            # counts file along with the new backup, so no half-written sidecar is left behind.
            Path(counts_path).unlink(missing_ok=True)
            Path(target).unlink(missing_ok=True)
            raise CommandError(
                f"backup failed: the counts file could not be written ({exc}). No backup was kept."
            ) from None
        self._say(f"backup written: {target} ({Path(target).stat().st_size:,} bytes)")
        self._say(f"counts written: {counts_path} ({len(counts)} tables)")

    def _restore_check(self, alias: str, backup: Any, scratch: Any) -> None:
        if not backup or not scratch:
            raise CommandError("restore-check needs --backup FILE.fbk and --scratch FILE.fdb")
        backup_path = os.path.abspath(str(backup))
        scratch_path = os.path.abspath(str(scratch))
        config = _firebird_config(alias)
        if not Path(backup_path).is_file():
            raise CommandError(f"restore-check refused: backup file {backup_path} does not exist.")
        try:
            refuse_live(scratch_path)
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        if Path(scratch_path).exists():
            raise CommandError(f"restore-check refused: {scratch_path} already exists. Choose a new scratch file name.")
        if not Path(scratch_path).parent.is_dir():
            raise CommandError(f"restore-check refused: the folder {Path(scratch_path).parent} does not exist.")
        password = _admin_password()
        if not password:
            raise CommandError(
                "restore-check refused: FB_ADMIN_PASSWORD is not set. Set it for this command only; "
                "it is never written to a file or printed. No scratch copy was made."
            )
        counts_path = _counts_path(backup_path)
        # Read before the restore, so a bad counts file is refused without leaving a scratch copy behind. A counts
        # file that exists but cannot be used is refused: there is no fallback to counting the live database.
        saved = _read_counts(counts_path) if Path(counts_path).exists() else None
        restore_target = _gbak_name(config, scratch_path)
        code, output = _run_gbak(gbak_restore_args(backup_path, restore_target, _admin_user()), password)
        if output:
            self._say(output)
        if code != 0:
            if Path(scratch_path).exists():  # written by this run only
                Path(scratch_path).unlink()
            raise CommandError(f"restore failed: gbak exited with code {code}. The backup file is untouched.")
        if saved is not None:
            before = saved
            basis = "compared with the counts taken at backup time"
        else:
            before = _row_counts(config)
            basis = "compared with the live database, run with MACS stopped"
            self._say(f"WARNING: no counts file: {basis}")
        if not before:
            raise CommandError(f"restore check refused: the source database {alias!r} has no user tables to compare.")
        # The restored copy is counted through the same server as the restore wrote it (host and port kept).
        after = _row_counts({**config, "NAME": scratch_path})
        differences = compare_counts(before, after)
        self._say(f"tables compared: {len(before)} in the source, {len(after)} in the restored copy ({basis})")
        for line in differences:
            self._say(f"  {line}")
        self._say("RESTORE DIFFERS" if differences else "RESTORE OK")
        self._say(
            f"WARNING: the scratch copy {scratch_path} holds a full copy of customer data. "
            "It is left in place for inspection. Delete it when you have finished."
        )
        if differences:
            raise CommandError("restore check failed: row counts differ. Do not rely on this backup.")

    def _report(self, snapshot: Any) -> None:
        results = [
            self._structure_result(snapshot),
            _guarded("E011 triggers", self._trigger_result),
            _guarded("W011 clock", self._clock_result),
        ]
        for name, passed, detail in results:
            self._say(f"{name}: {'ok' if passed else 'FAIL'} - {detail}")
        if all(passed for _, passed, _ in results):
            self._say("READY")
            return
        self._say("NOT READY")
        raise CommandError("cut-over report: NOT READY (see the lines above)")

    def _structure_result(self, snapshot: Any) -> CheckResult:
        if not snapshot:
            return ("structure verify", False, "not checked: no --snapshot file given (run fb_guard snapshot first)")
        path = str(snapshot)
        if not Path(path).is_file():
            return (
                "structure verify",
                False,
                f"not checked: snapshot file not found: {path} (run fb_guard snapshot first)",
            )
        if not _is_firebird_default():
            return ("structure verify", False, "not checked: the default database is not Firebird")
        return _guarded("structure verify", lambda: self._run_verify(path))

    def _run_verify(self, path: str) -> CheckResult:
        out = StringIO()
        try:
            call_command("fb_guard", "verify", path, database="default", stdout=out, stderr=out)
        except CommandError as exc:
            details = [line.strip() for line in out.getvalue().splitlines() if line.strip()]
            return ("structure verify", False, "; ".join([str(exc), *details]))
        return ("structure verify", True, "existing MACS objects unchanged since the snapshot")

    def _trigger_result(self) -> CheckResult:
        if not _is_firebird_default():
            return ("E011 triggers", False, "not checked: the default database is not Firebird")
        messages = check_macs_triggers(databases=["default"])
        if messages:
            return ("E011 triggers", False, "; ".join(str(message.msg) for message in messages))
        expected = sum(len(names) for names in MACS_TRIGGERS.values())
        return ("E011 triggers", True, f"all {expected} MACS triggers that HR relies on are active")

    def _clock_result(self) -> CheckResult:
        if not _is_firebird_default():
            return ("W011 clock", False, "not checked: the default database is not Firebird")
        messages = check_server_time_zone(databases=["default"])
        if messages:
            return ("W011 clock", False, "; ".join(str(message.msg) for message in messages))
        return ("W011 clock", True, "Firebird server clock matches Asia/Ulaanbaatar time (within 2 minutes)")
