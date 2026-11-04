"""fb_guard: prove that HR did not change existing objects in the shared Firebird database.

    manage.py fb_guard preflight                 refuse to run if a model table already exists
                                                 (unless it is HR's own, under HR_TABLE_PREFIX)
    manage.py fb_guard snapshot <file.json>      record the fingerprint of the existing objects
    manage.py fb_guard verify <file.json>        compare the database with the snapshot; fail on any change

Use --database to pick the alias (default: "default").
"""

import json
import re
from pathlib import Path
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connections
from django.db.models import Model

from infohr_firebird.structure import CATEGORIES, fingerprint, preflight

MACS_APP_LABEL = "macs"
HASH_RE = re.compile(r"[0-9a-f]{12}")  # the fingerprint hash: first 12 lowercase hex characters of sha256


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


class Command(BaseCommand):
    help = "Pre-flight, snapshot and verify HR's additions to a Firebird database that MACS also uses."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["preflight", "snapshot", "verify"])
        parser.add_argument("path", nargs="?", default=None, help="snapshot and verify: the JSON file")
        parser.add_argument("--database", default="default", help="database alias to check (default: default)")

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
