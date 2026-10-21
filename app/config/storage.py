"""Static files get a new URL whenever their content changes, so browsers never keep an old copy.

After `collectstatic` the URL carries the content hash from Django's manifest
(e.g. js/select.3f2a9c.js). Under runserver, or for a file not collected yet, the
URL gets `?v=<file mtime>` instead, which also changes on every edit.
"""

import os

from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage, StaticFilesStorage


class VersionedStaticFilesStorage(ManifestStaticFilesStorage):
    def url(self, name: str | None, force: bool = False) -> str:
        if name and not settings.DEBUG:
            try:
                return super().url(name, force)
            except ValueError:  # no manifest entry: collectstatic not run (tests, fresh checkout)
                pass
        plain = StaticFilesStorage.url(self, name)
        path = finders.find(name) if name else None
        if isinstance(path, str):
            return f"{plain}?v={int(os.path.getmtime(path))}"
        return plain
