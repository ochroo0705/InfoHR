import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
VENDOR = APP / "static" / "vendor" / "echarts"


def test_echarts_file_exists_with_version():
    text = (VENDOR / "echarts.min.js").read_text(encoding="utf-8")
    assert 'version="5.5.1"' in text
    assert "Apache Software Foundation" in text[:400]


def test_license_is_apache():
    assert "Apache License" in (VENDOR / "LICENSE").read_text(encoding="utf-8")


def test_no_cdn_script_in_templates():
    external = re.compile(r"""<script[^>]*\ssrc\s*=\s*["']?\s*(https?:)?//""", re.IGNORECASE)
    for path in APP.glob("**/templates/**/*.html"):
        assert not external.search(path.read_text(encoding="utf-8")), path


def test_the_cdn_scan_catches_the_usual_forms():
    external = re.compile(r"""<script[^>]*\ssrc\s*=\s*["']?\s*(https?:)?//""", re.IGNORECASE)
    for bad in ('<script src="https://x/a.js">', "<script src='http://x/a.js'>", '<script defer src="//x/a.js">'):
        assert external.search(bad), bad
    assert not external.search('<script src="{% static "a.js" %}">')
