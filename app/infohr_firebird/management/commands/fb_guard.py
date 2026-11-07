"""fb_guard: prove that HR did not change existing objects in the shared Firebird database.

    manage.py fb_guard preflight                 refuse to run if a model table already exists
                                                 (unless it is HR's own, under HR_TABLE_PREFIX)
    manage.py fb_guard snapshot <file.json>      record the fingerprint of the existing objects
    manage.py fb_guard verify <file.json>        compare the database with the snapshot; fail on any change
    manage.py fb_guard grants --user NAME        print the GRANT script for the runtime user (applies nothing)

Use --database to pick the alias (default: "default").
"""

import json
import re
from pathlib import Path
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Model

from infohr_firebird.structure import CATEGORIES, fingerprint, preflight

MACS_APP_LABEL = "macs"
HASH_RE = re.compile(r"[0-9a-f]{12}")  # the fingerprint hash: first 12 lowercase hex characters of sha256
USER_NAME_RE = re.compile(r"[A-Z][A-Z0-9_$]{0,30}")  # the same rule as ^[A-Z][A-Z0-9_$]{0,30}$, matched in full
RESERVED_USER_NAMES = frozenset({"PUBLIC", "SYSDBA", "SYSTEM"})  # built-in roles and accounts: never a runtime user
HR_RIGHTS = "SELECT, INSERT, UPDATE, DELETE"  # every HR table, and only these rights (no ALTER, DROP, REFERENCES)
# Tables that need less than HR_RIGHTS, keyed by Django model label (app_label.modelname in lower case), so the
# Firebird name comes from the backend. A key that matches no model is refused, so an override cannot fail silently.
HR_TABLE_RIGHTS: dict[str, str] = {
    # Append-only logs: the app only inserts. SELECT is kept because the log screens and the admin history read them.
    "accounts.systemlogentry": "SELECT, INSERT",
    "employees.activityentry": "SELECT, INSERT",
    "admin.logentry": "SELECT, INSERT",
    # Permissions and content types are created by migrations (SYSDBA); no runtime code writes them.
    "auth.permission": "SELECT",
    "contenttypes.contenttype": "SELECT",
    # Role-group membership and group permissions: the admin sets them with delete and insert.
    "accounts.user_groups": "SELECT, INSERT, DELETE",
    "auth.group_permissions": "SELECT, INSERT, DELETE",
}
# Audit tables whose reference to the user is SET_NULL: deleting a user makes Django UPDATE that one column to NULL.
# Keyed by model label, value is the field name. The runtime user gets UPDATE on that column only, never the table.
HR_COLUMN_UPDATE: dict[str, str] = {
    "accounts.systemlogentry": "actor",
    "employees.activityentry": "by",
}

# Task 1 (docs/migration/runtime-user-spike.md, "Final minimal GRANT list"): the MACS objects the HR write paths
# and the MACS triggers touch, exactly as tested as the limited user. The IHR_ rows of that list are covered by
# HR_RIGHTS on every HR table, so they are not repeated here.
SPIKE_MACS_TABLES: tuple[tuple[str, str], ...] = (
    ("SELECT, INSERT, UPDATE", "EMPLOYEE"),
    ("SELECT, INSERT, UPDATE", "CUSTOMER"),
    ("SELECT, INSERT, UPDATE", "ADDRESS"),
    ("SELECT", "CITYTOWN"),
    ("SELECT", "DISTRICT"),
    ("SELECT", "BRANCH"),
    ("SELECT", "DEPS"),
    ("SELECT", "OCCUPATION"),
    ("SELECT", "FIRED_REASON"),
    ("SELECT", "JOURNAL"),
    ("SELECT", "ORDERS"),
    ("SELECT, INSERT, DELETE", "MOVEMENT"),
    ("SELECT, INSERT, DELETE", "EMPLOYEE_HISTORY"),
    ("SELECT, INSERT, UPDATE", "CONTACTING"),
    ("SELECT, INSERT", "CONTACT_TYPE"),
)
# MACS columns the HR write paths UPDATE, and no other column of that table (plan 5, task 3): registering an order
# sets the command and the move type of its employee_history row (macs_writes.write_order). One GRANT per column.
SPIKE_MACS_COLUMN_UPDATES: tuple[tuple[str, str], ...] = (
    ("EMPLOYEE_HISTORY", "COMMAND_IDENT"),
    ("EMPLOYEE_HISTORY", "MOVE_TYPE"),
)
SPIKE_MACS_EXCEPTIONS: tuple[str, ...] = ("CANNOT_CHANGE_CUSTID", "IHR_HISTORY_OVERLAP")
SPIKE_MACS_GENERATORS: tuple[str, ...] = (
    "GEN_EMPLOYEEID",
    "GEN_CUSTID",
    "GEN_ADDRESS_ID",
    "GEN_CONTACTING_ID",
    "GEN_CONTACT_TYPE_ID",
    "GEN_EMPLOYEE_HISTORY_ID",
    "GEN_MOVEMENT_ID",
)

# Leave and personal-list tables from scripts/grant_macs_pg.sql, with the rights that file gives. NOT yet proven
# on Firebird: none of the tests has run these as the limited user. The three tables the spike already grants
# (ADDRESS, CONTACTING, CONTACT_TYPE) get only the rights the PostgreSQL file adds on top of the spike.
UNPROVEN_TABLES: tuple[tuple[str, str], ...] = (
    ("SELECT, INSERT, UPDATE, DELETE", "LEAVE_TYPE"),
    ("SELECT, INSERT, UPDATE", "LEAVE_ASSIGN"),
    ("SELECT, INSERT, UPDATE", "ENTITLEMENT"),
    ("SELECT, INSERT, UPDATE, DELETE", "HR_LEGALHOLIDAYS"),
    ("SELECT, INSERT, UPDATE", "EMP_VACATION"),
    ("SELECT, INSERT, UPDATE, DELETE", "FAMILY"),
    ("SELECT, INSERT, UPDATE, DELETE", "RELATIVE"),
    ("SELECT, INSERT, UPDATE, DELETE", "BEFORE_WORK"),
    ("SELECT, INSERT, UPDATE, DELETE", "EDUC"),
    ("SELECT, INSERT, UPDATE, DELETE", "GIVEN_PRESENT"),
    ("DELETE", "ADDRESS"),
    ("DELETE", "CONTACTING"),
    ("SELECT, INSERT, UPDATE, DELETE", "EMP_TALENTS"),
    ("SELECT, INSERT, UPDATE, DELETE", "HR_SKILLWORK"),
    ("SELECT, INSERT, UPDATE, DELETE", "MATERIAL_HELP"),
    ("SELECT, INSERT, UPDATE, DELETE", "AWARDS"),
    ("SELECT, INSERT, UPDATE, DELETE", "DISCIPLINE"),
    ("SELECT, INSERT, UPDATE, DELETE", "HR_COMPLAINTS"),
    ("SELECT, INSERT, UPDATE, DELETE", "BODY"),
    ("SELECT, INSERT, UPDATE, DELETE", "DRIVER"),
    ("SELECT, INSERT, UPDATE, DELETE", "MILITARY"),
    ("SELECT, INSERT, UPDATE, DELETE", "ARMY_RANK"),
    ("SELECT, INSERT, UPDATE, DELETE", "FAMILY_MEMBERS"),
    ("SELECT, INSERT, UPDATE, DELETE", "EDU_TYPE"),
    ("SELECT, INSERT, UPDATE, DELETE", "PRESENT_TYPE"),
    ("UPDATE, DELETE", "CONTACT_TYPE"),
    ("SELECT, INSERT, UPDATE, DELETE", "TALENTS"),
    ("SELECT, INSERT, UPDATE, DELETE", "MATERIAL_HELP_TYPE"),
    ("SELECT, INSERT, UPDATE, DELETE", "DISCIPLINE_TYPE"),
    ("SELECT, INSERT, UPDATE, DELETE", "DRIVER_TYPE"),
    ("SELECT, INSERT, UPDATE, DELETE", "QUALIFICATION"),
    ("SELECT, INSERT, UPDATE, DELETE", "SPEC_EDU"),
    ("SELECT, INSERT, UPDATE, DELETE", "HR_TRAINING"),
    ("SELECT, INSERT, UPDATE, DELETE", "FOREIGN_LANG"),
    ("SELECT, INSERT, UPDATE, DELETE", "QUALIFICATION_TYPE"),
    ("SELECT, INSERT, UPDATE, DELETE", "PROFESSION_TYPE"),
    ("SELECT, INSERT, UPDATE, DELETE", "SPEC_EDU_TYPE"),
    ("SELECT, INSERT, UPDATE, DELETE", "FLANGUAGES"),
    ("SELECT, INSERT, UPDATE, DELETE", "LANG_LEVEL"),
    ("SELECT, INSERT, UPDATE", "COMMAND"),  # HR orders: written by macs_writes; cancelled orders keep their row
    ("SELECT, INSERT, UPDATE, DELETE", "NAZG"),  # position slots: the slots screen adds, edits and deletes
)
UNPROVEN_GENERATORS: tuple[str, ...] = (
    "GEN_LEAVE_TYPE_ID",
    "GEN_LEAVE_ASSIGN_ID",
    "GEN_ENTITLEMENT_ID",
    "GEN_HR_LEGALHOLIDAYS_ID",
    "GEN_FAMILY_ID",
    "GEN_RELATIVE_ID",
    "GEN_BEFORE_WORK_ID",
    "GEN_EDUC_ID",
    "GEN_GIVEN_PRESENT_ID",
    "GEN_FAMILY_MEMBERS_ID",
    "GEN_EDU_TYPE_ID",
    "GEN_TALENTS_ID",
    "GEN_PRESENT_TYPE_ID",
    "GEN_HR_SKILLWORK_ID",
    "GEN_MATERIAL_HELP_ID",
    "GEN_MATERIAL_HELP_TYPE_ID",
    "GEN_AWARDS_ID",
    "GEN_DISCIPLINE_ID",
    "GEN_DISCIPLINE_TYPE_ID",
    "GEN_HR_COMPLAINTS_ID",
    "GEN_BODY_ID",
    "GEN_DRIVER_ID",
    "GEN_DRIVER_TYPE_ID",
    "GEN_MILITARY_ID",
    "GEN_ARMY_RANK_ID",
    "GEN_QUALIFICATION_ID",
    "GEN_SPEC_EDU_ID",
    "GEN_HR_TRAINING_ID",
    "GEN_FOREIGN_LANG_ID",
    "GEN_QUALIFICATION_TYPE_ID",
    "GEN_PROFESSION_TYPE_ID",
    "GEN_SPEC_EDU_TYPE_ID",
    "GEN_FLANGUAGES_ID",
    "GEN_LANG_LEVEL_ID",
    "GEN_COMMAND_ID",
    "GEN_NAZG_ID",
)

GRANTS_HEADER = """-- Grants for the limited Firebird runtime user of Info HR (plan 5, task 2).
-- Generated by: manage.py fb_guard grants --user {user}
-- Nothing in this file is a password. The password is set on the server, never here.
--
-- WHO RUNS THIS, AND WHEN
--   The database administrator, once, as SYSDBA, after "manage.py migrate" has created the
--   IHR_ tables and their generators for the installed apps. Run it against the database file
--   (for example with isql, connected as SYSDBA). Run it again only after a new HR table is added,
--   because the HR part of this script is generated from the models.
--
-- HOW TO CREATE THE USER (do this first, on the server, as an administrator)
--   Create a login named {user} with a password chosen for this purpose, using the server's own
--   tools (for example gsec, or isql connected as SYSDBA with CREATE USER). The password is not
--   written in this file, in the repository or in chat. Put the same password in the app's
--   FIREBIRD_PASSWORD setting for the runtime process only, and keep it out of version control.
--   If another name is wanted, change the --user value and regenerate this file.
--
-- WHAT IS GRANTED
--   1. Every IHR_ table of the installed HR apps: SELECT, INSERT, UPDATE, DELETE, and USAGE on
--      each of their generators, except: the append-only logs (system log, activity log, admin
--      log) get SELECT and INSERT only; permissions and content types get SELECT only; the
--      role-group membership and group-permission tables get SELECT, INSERT, DELETE.
--      The system log and the activity log also get UPDATE on one column each (see below).
--   1c. Read only (SELECT): the unmanaged MACS lookup and history tables the screens read (those
--      not named in items 2 and 4), and the migration history IHR_DJANGO_MIGRATIONS. Migrations run
--      as SYSDBA, so the runtime user never writes the history.
--   2. The MACS tables that the MACS triggers and the HR write paths touch, exactly as tested as
--      the limited user (docs/migration/runtime-user-spike.md). Triggers run with the caller's
--      rights, so these are needed even though the app does not name them.
--   3. The exceptions the MACS triggers raise: USAGE on EXCEPTION.
--   4. A block marked NOT YET PROVEN ON FIREBIRD: the leave, personal-list, HR order (COMMAND)
--      and position slot (NAZG) tables from scripts/grant_macs_pg.sql, with the rights that file
--      gives. Their write paths have not been run as this user yet. Review that block before
--      relying on it.
--
-- USER DELETION
--   An administrator can delete a user. Django then sets the user reference to NULL in the
--   audit rows that point at that user: the actor of a system-log row (ACTOR_ID) and the "by"
--   of an activity-log row (BY_ID). The runtime user therefore gets UPDATE on those two columns
--   only. It cannot change any other column of those logs, and it cannot delete any log row.
--   The admin's own log (IHR_DJANGO_ADMIN_LOG) is different: Django deletes a user's rows in it
--   with the user (CASCADE). The runtime user has NO delete right on that log, on purpose: it
--   would let the app wipe the admin history. So a user who has admin-log entries is deleted only
--   by an administrator as SYSDBA. The app's normal route is to deactivate the user instead.
--   A user with no admin-log rows can be deleted by the runtime user (its system-log and
--   activity-log references are set to NULL under the column grants above).
--
-- WHAT IS NEVER GRANTED
--   ALL, ALTER, DROP, CREATE, REFERENCES, and any right to create or change users or the
--   security database. The runtime user needs no DDL (spike answer (e)).
--
-- After the script, COMMIT is issued. Check with a test login that the app's write paths pass
-- before the MACS database is used in production.
"""


def _snapshot_problem(data: Any) -> str:
    """Why data is not a usable snapshot, or "" when it is. An empty prefix would match every object."""
    if not isinstance(data, dict):
        return "not a JSON object"
    prefixes = data.get("ignore_prefixes")
    if not isinstance(prefixes, list) or not prefixes:
        return "ignore_prefixes must be a non-empty list"
    if not all(isinstance(prefix, str) and prefix for prefix in prefixes):
        return "every ignore_prefixes entry must be a non-empty string"
    stored = data.get("fingerprint")
    if not isinstance(stored, dict) or set(stored) != set(CATEGORIES):
        return "fingerprint must have exactly the known categories"
    for name, value in stored.items():
        valid = (
            isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], int)
            and not isinstance(value[0], bool)
            and isinstance(value[1], str)
            and HASH_RE.fullmatch(value[1]) is not None
        )
        if not valid:
            return f"fingerprint entry {name} must be [row count, hash]"
    return ""


def _checked_user(user: Any) -> str:
    """The --user name, or a CommandError. The name is written into SQL text, so only the validated form passes."""
    if not isinstance(user, str) or USER_NAME_RE.fullmatch(user) is None:
        raise CommandError(
            "grants --user must be a Firebird user name: upper case letters, digits, _ or $, "
            "starting with a letter, at most 31 characters"
        )
    # PUBLIC is the role every login has: a grant to it gives every user the rights. SYSDBA and SYSTEM are the
    # built-in administrator and system accounts, and RDB$ names are Firebird's own objects (RDB$ADMIN is a role).
    # The regex above accepts all of them, so they are refused here.
    if user in RESERVED_USER_NAMES or user.startswith("RDB$"):
        raise CommandError(f"grants --user must be a Firebird user name, not the built-in name {user}")
    return user


class Command(BaseCommand):
    help = "Pre-flight, snapshot and verify HR's additions to a Firebird database that MACS also uses."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["preflight", "snapshot", "verify", "grants"])
        parser.add_argument("path", nargs="?", default=None, help="snapshot and verify: the JSON file")
        parser.add_argument("--database", default="default", help="database alias to check (default: default)")
        parser.add_argument("--user", default=None, help="grants: the Firebird user name the script grants to")

    def models_to_check(self) -> list[type[Model]]:
        """Managed HR models that will get a table. Proxies share their concrete model's table and are skipped."""
        return [
            model
            for model in apps.get_models(include_auto_created=True)
            if model._meta.managed and not model._meta.proxy and model._meta.app_label != MACS_APP_LABEL
        ]

    def handle(self, *args: Any, **options: Any) -> None:
        alias = str(options["database"])
        action = str(options["action"])
        if action == "preflight":
            self._preflight(alias)
        elif action == "snapshot":
            self._snapshot(alias, self._require_path(options.get("path"), action))
        elif action == "grants":
            self._grants(alias, options.get("user"))
        else:
            self._verify(alias, self._require_path(options.get("path"), action))

    def _require_path(self, path: Any, action: str) -> str:
        if not path:
            raise CommandError(f"{action} needs a file path")
        return str(path)

    def _preflight(self, alias: str) -> None:
        models = self.models_to_check()
        problems = preflight(connections[alias], models, getattr(settings, "HR_TABLE_PREFIX", ""))
        if problems:
            for problem in problems:
                self.stdout.write(f"collision: {problem}")
            raise CommandError("pre-flight failed: " + "; ".join(problems))
        self.stdout.write(f"pre-flight ok: {len(models)} model tables, none exist yet or only HR-owned")

    def _snapshot(self, alias: str, path: str) -> None:
        prefix = str(getattr(settings, "HR_TABLE_PREFIX", "")).upper()
        if not prefix:
            raise CommandError(
                "snapshot needs HR_TABLE_PREFIX: without a prefix HR objects cannot be separated from MACS objects"
            )
        with connections[alias].cursor() as cursor:
            current = fingerprint(cursor, (prefix,))
        data = {"ignore_prefixes": [prefix], "fingerprint": {name: list(value) for name, value in current.items()}}
        try:
            Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            raise CommandError(f"cannot write snapshot {path}: {exc}") from exc
        self.stdout.write(f"snapshot written: {path} ({len(current)} categories)")

    def _verify(self, alias: str, path: str) -> None:
        stored = self._read_snapshot(path)
        with connections[alias].cursor() as cursor:
            current = fingerprint(cursor, tuple(stored["ignore_prefixes"]))
        changed = False
        for name in CATEGORIES:
            now = list(current[name])
            before = stored["fingerprint"].get(name)
            if before != now:
                changed = True
                self.stdout.write(f"changed: {name} stored {before} now {now}")
        if changed:
            raise CommandError("existing MACS objects changed")
        self.stdout.write("verify ok: existing objects unchanged")

    def _grants(self, alias: str, user: Any) -> None:
        """Print the GRANT script. Names come from the models (Firebird naming) and the constants, never from input."""
        name = _checked_user(user)
        connection = connections[alias]
        if connection.vendor != "firebird":
            raise CommandError("grants writes Firebird names: run it with the Firebird settings (DB_ENGINE=firebird)")
        ops: Any = connection.ops  # the backend's own naming: quote_name and get_sequence_name (generator <TABLE>_SQ)
        models = self.models_to_check()
        models_by_label = {model._meta.label_lower: model for model in models}
        unknown = sorted((set(HR_TABLE_RIGHTS) | set(HR_COLUMN_UPDATE)) - set(models_by_label))
        if unknown:
            raise CommandError("HR_TABLE_RIGHTS or HR_COLUMN_UPDATE names no HR model: " + ", ".join(unknown))
        column_lines: list[str] = []
        for label, field_name in sorted(HR_COLUMN_UPDATE.items()):
            model = models_by_label[label]
            try:
                field: Any = model._meta.get_field(field_name)  # a forward FK here; typed Any for its .column
            except FieldDoesNotExist as exc:
                raise CommandError(f"HR_COLUMN_UPDATE: {label} has no field {field_name}") from exc
            table = str(ops.quote_name(model._meta.db_table))
            column_lines.append(f"GRANT UPDATE ({ops.quote_name(field.column)}) ON {table} TO {name};")
        rights_by_table = {
            str(ops.quote_name(model._meta.db_table)): HR_TABLE_RIGHTS.get(model._meta.label_lower, HR_RIGHTS)
            for model in models
        }
        sequences = sorted(
            {str(ops.get_sequence_name(model._meta.db_table)) for model in models if model._meta.auto_field is not None}
        )
        lines = [GRANTS_HEADER.format(user=name)]
        lines.append("-- 1. HR tables (IHR_) and their generators")
        lines += [f"GRANT {rights_by_table[table]} ON {table} TO {name};" for table in sorted(rights_by_table)]
        lines.append("-- 1b. Audit references to the user (set to NULL when a user is deleted): one column each")
        lines += column_lines
        lines += [f"GRANT USAGE ON SEQUENCE {sequence} TO {name};" for sequence in sequences]
        # Read-only: unmanaged MACS tables the screens read that no list above already names, and the migration history.
        unmanaged = [
            model
            for model in apps.get_models(include_auto_created=True)
            if not model._meta.managed and not model._meta.proxy
        ]
        listed = {str(ops.quote_name(table)) for _rights, table in (*SPIKE_MACS_TABLES, *UNPROVEN_TABLES)}
        read_only = sorted({str(ops.quote_name(model._meta.db_table)) for model in unmanaged} - listed)
        history = str(ops.quote_name(MigrationRecorder.Migration._meta.db_table))
        lines.append("-- 1c. Read only: unmanaged MACS tables the app reads, and the migration history")
        lines += [f"GRANT SELECT ON {table} TO {name};" for table in [*read_only, history]]
        lines.append("-- 2. MACS tables and generators, as tested in the spike (runtime-user-spike.md)")
        lines += [f"GRANT {rights} ON {table} TO {name};" for rights, table in SPIKE_MACS_TABLES]
        lines += [f"GRANT UPDATE ({column}) ON {table} TO {name};" for table, column in SPIKE_MACS_COLUMN_UPDATES]
        lines += [f"GRANT USAGE ON SEQUENCE {generator} TO {name};" for generator in SPIKE_MACS_GENERATORS]
        lines.append("-- 3. Exceptions raised by triggers")
        lines += [f"GRANT USAGE ON EXCEPTION {exception} TO {name};" for exception in SPIKE_MACS_EXCEPTIONS]
        lines.append("-- 4. NOT YET PROVEN ON FIREBIRD: leave, personal lists, COMMAND, NAZG (as in grant_macs_pg.sql)")
        lines += [f"GRANT {rights} ON {table} TO {name};" for rights, table in UNPROVEN_TABLES]
        lines += [f"GRANT USAGE ON SEQUENCE {generator} TO {name};" for generator in UNPROVEN_GENERATORS]
        lines.append("COMMIT;")
        self.stdout.write("\n".join(lines) + "\n")

    def _read_snapshot(self, path: str) -> dict[str, Any]:
        """Load and validate a snapshot. Anything malformed is a CommandError, never a crash or a silent pass."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"cannot read snapshot {path}: {exc}") from exc
        problem = _snapshot_problem(data)
        if problem:
            raise CommandError(f"invalid fb_guard snapshot {path}: {problem}")
        loaded: dict[str, Any] = data
        return loaded
