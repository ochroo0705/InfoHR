"""Add the help assistant's demo people, departments and positions to the demo database. Demo only.

Refuses unless the real settings are PostgreSQL, DEBUG is on and the database name starts with info_hr_demo (see
assistant.demo_data.assistant_data_allowed). Run it through `python scripts/demo.py assistant-data`. There is no
removal: the activity log is append-only. To start over, run `python scripts/demo.py reset`, then this command again.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from assistant import demo_data

REFUSED_MESSAGE = (
    "Туслахын demo өгөгдлийг зөвхөн PostgreSQL дээр, DEBUG горимд, info_hr_demo өгөгдлийн санд нэмнэ. "
    "(Assistant demo data runs only on PostgreSQL with DEBUG on, in a database named info_hr_demo*.)"
)


class Command(BaseCommand):
    help = (
        "Add the help assistant's Mongolian demo staff to the demo database (DEBUG and info_hr_demo only). "
        "To start over: scripts/demo.py reset, then this command."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--large",
            action="store_true",
            help="Also add about 150 more people in uneven departments (charts with a shape).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        db = settings.DATABASES["default"]
        engine = str(db["ENGINE"]).rsplit(".", 1)[-1]  # django.db.backends.postgresql -> postgresql
        if not demo_data.assistant_data_allowed(str(db["NAME"]), bool(settings.DEBUG), engine):
            raise CommandError(REFUSED_MESSAGE)
        today = timezone.localdate()
        counts = demo_data.build(today)
        if options.get("large"):
            more = demo_data.build_large(today)
            counts = {key: counts[key] + more[key] for key in counts}
        self.stdout.write(
            self.style.SUCCESS(
                f"Туслахын demo өгөгдөл: {counts['people']} ажилтан, {counts['departments']} хэлтэс, "
                f"{counts['positions']} албан тушаал нэмэгдлээ."
            )
        )
