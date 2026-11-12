import os
import subprocess
import sys
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


def test_debug_is_off_by_default() -> None:
    """Production safety: with no DJANGO_DEBUG the code default is DEBUG off. A child process imports config.settings
    with the .env reader turned off (the developer's .env sets DJANGO_DEBUG=true), so this process is not touched."""
    code = (
        "import environ; environ.Env.read_env = lambda *a, **k: None\n"
        "import config.settings as s\n"
        "print(s.DEBUG)"
    )
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_DEBUG"}
    env["PYTHONPATH"] = str(settings.BASE_DIR)
    # Fixed argv (this interpreter, a literal snippet): no untrusted input reaches the command.
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)  # noqa: S603
    assert result.stdout.strip() == "False"


def test_datepicker_placeholder_and_title_say_year_month_day() -> None:
    """The date box shows ЖЖЖЖ-СС-ӨӨ and a tooltip with the order (audit task 8, step 2)."""
    text = (Path(settings.BASE_DIR) / "static" / "js" / "datepicker.js").read_text(encoding="utf-8")
    assert '"ЖЖЖЖ-СС-ӨӨ"' in text
    assert '"Жил-сар-өдөр"' in text
    assert "ОООО" not in text


def test_datepicker_upgrades_month_inputs() -> None:
    """A native <input type="month"> would show the browser's own English popup; the picker takes it over."""
    text = (Path(settings.BASE_DIR) / "static" / "js" / "datepicker.js").read_text(encoding="utf-8")
    assert 'input[type="month"]' in text
    assert '"ЖЖЖЖ-СС"' in text
    assert "Энэ сар" in text
