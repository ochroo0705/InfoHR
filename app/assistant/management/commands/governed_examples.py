"""manage.py governed_examples check: list the approved verified queries that no longer pass the SQL checker.

The reference is the full catalogue of the governed views (hr_sql.descriptions.load_all), so a view or column change
shows up here. Exits with a command error (non-zero) when any approved example is stale. Writes nothing to the database.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from assistant.verified import stale_examples


class Command(BaseCommand):
    help = "Check the approved verified queries against the current governed views. Exits non-zero when one is stale."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["check"])

    def handle(self, *args: Any, **options: Any) -> None:
        stale = stale_examples()
        if not stale:
            self.stdout.write("All approved examples pass the checker.")
            return
        for item in stale:
            self.stderr.write(f"#{item.pk} {item.question}: {item.problem}")
        raise CommandError(f"{len(stale)} approved example(s) no longer pass the checker.")
