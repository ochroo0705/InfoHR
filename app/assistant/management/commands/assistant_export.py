"""Write the active corrections to a JSON file for review. Writes nothing to the database."""

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from assistant import learning
from assistant.models import HelpExample


class Command(BaseCommand):
    help = "Write the active corrections to a JSON file for review. Writes nothing to the database."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--out",
            default=None,
            help="File to write (UTF-8). Default: assistant_export_<YYYY-MM-DD>.json in the current directory.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        out = Path(options["out"] or f"assistant_export_{timezone.localdate():%Y-%m-%d}.json")
        payload = learning.export_payload(HelpExample.objects.all())
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"Wrote {len(payload['examples'])} examples and {len(payload['tests'])} tests to {out}")
