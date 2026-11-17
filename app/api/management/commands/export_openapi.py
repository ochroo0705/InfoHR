import json
from pathlib import Path

from django.core.management.base import BaseCommand

from api.main import api


class Command(BaseCommand):
    help = "Write the MACS Human Capital API OpenAPI schema to a JSON file."

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument("out_path", help="Where to write the schema, for example web/openapi.json.")

    def handle(self, *args, **options) -> None:  # type: ignore[no-untyped-def]
        out = Path(options["out_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(api.get_openapi_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        out.write_text(text, encoding="utf-8")
        self.stdout.write(f"Wrote {out}")
