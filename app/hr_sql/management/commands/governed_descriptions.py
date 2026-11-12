"""manage.py governed_descriptions status | sign <VIEW> --by "<name>": the reviewed descriptions of the GOV_* views.

`status` lists each view as signed or draft. `sign` writes the signer's name and today's date into that view's file;
it is the only way a file becomes signed, and it is for the domain owner to run. Files: hr_sql/descriptions/.
"""

from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from hr_sql.descriptions import draft_views, load_all, sign


class Command(BaseCommand):
    help = "Show or sign the reviewed descriptions of the governed views (hr_sql/descriptions/)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["status", "sign"])
        parser.add_argument("view", nargs="?", help="the view to sign, for example GOV_LEAVE")
        parser.add_argument("--by", default="", help="the name of the domain owner who reviewed the file")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["action"] == "status":
            self._status()
            return
        if not options["view"]:
            raise CommandError("sign needs the view name, for example: sign GOV_LEAVE --by \"<name>\"")
        try:
            sign(options["view"], options["by"], date.today())
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"{options['view'].upper()} signed")

    def _status(self) -> None:
        drafts = set(draft_views())
        for name, view in load_all().items():
            if name in drafts:
                self.stdout.write(f"{name}: draft (not signed)")
            else:
                self.stdout.write(f"{name}: signed by {view.reviewed_by} on {view.reviewed_on}")
