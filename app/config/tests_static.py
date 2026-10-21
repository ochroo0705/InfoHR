import os
from pathlib import Path

from django.conf import settings
from django.templatetags.static import static
from pytest_django.fixtures import SettingsWrapper

SELECT_JS = Path(settings.BASE_DIR) / "static" / "js" / "select.js"


def _touch(seconds: int) -> None:
    os.utime(SELECT_JS, (seconds, seconds))


def test_changed_static_file_gets_new_url(settings: SettingsWrapper) -> None:
    """Without collectstatic (runserver, tests) the URL carries the file's mtime."""
    original = SELECT_JS.stat().st_mtime
    try:
        for debug in (True, False):
            settings.DEBUG = debug
            _touch(1_700_000_000)
            first = static("js/select.js")
            _touch(1_700_000_100)
            assert first == "/static/js/select.js?v=1700000000"
            assert static("js/select.js") == "/static/js/select.js?v=1700000100"
    finally:
        os.utime(SELECT_JS, (original, original))


def test_unknown_file_keeps_plain_url() -> None:
    assert static("js/does-not-exist.js") == "/static/js/does-not-exist.js"
