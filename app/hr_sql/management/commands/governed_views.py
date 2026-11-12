"""manage.py governed_views install: create or update GOV_SCOPE and the GOV_* views on a Firebird database.

Run once after migrate, and again after a change to hr_sql/views.py. Runs as the database owner (the default login),
never as the read-only governed login, which gets only the grants in scripts/grant_governed_fb.sql.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DEFAULT_DB_ALIAS, connections

from hr_sql.views import install


class Command(BaseCommand):
    help = "Create or update the governed objects (GOV_SCOPE and the GOV_* views). Firebird only; safe to repeat."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["install"])
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS, help="the database alias to install into")

    def handle(self, *args: Any, **options: Any) -> None:
        connection = connections[options["database"]]
        if connection.vendor != "firebird":
            raise CommandError("governed_views needs a Firebird database (DB_ENGINE=firebird).")
        install(connection)
        self.stdout.write("governed views installed")
