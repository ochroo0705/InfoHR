import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
VENDOR = APP / "static" / "vendor" / "plotly"


def test_plotly_file_exists_with_banner():
    text = (VENDOR / "plotly-basic.min.js").read_text(encoding="utf-8")
    assert "plotly.js (basic - minified) v2.35.2" in text[:200]


def test_readme_names_version_and_hash():
    readme = (VENDOR / "README.txt").read_text(encoding="utf-8")
    assert "2.35.2" in readme and "sha256:" in readme
    assert (VENDOR / "LICENSE").read_text(encoding="utf-8").strip()


def test_no_cdn_script_in_templates():
    external = re.compile(r"""<script[^>]*\ssrc\s*=\s*["']?\s*(https?:)?//""", re.IGNORECASE)
    for path in APP.glob("**/templates/**/*.html"):
        assert not external.search(path.read_text(encoding="utf-8")), path


def test_the_cdn_scan_catches_the_usual_forms():
    external = re.compile(r"""<script[^>]*\ssrc\s*=\s*["']?\s*(https?:)?//""", re.IGNORECASE)
    for bad in ('<script src="https://x/a.js">', "<script src='http://x/a.js'>", '<script defer src="//x/a.js">'):
        assert external.search(bad), bad
    assert not external.search('<script src="{% static "a.js" %}">')
