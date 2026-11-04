import importlib
from pathlib import Path

import infohr_firebird


def test_backend_module_is_a_django_backend() -> None:
    base = importlib.import_module("infohr_firebird.base")
    assert base.DatabaseWrapper.vendor == "firebird"


def test_license_kept() -> None:
    licence = Path(infohr_firebird.__file__).parent / "LICENSE"
    assert licence.exists()
    assert "BSD" in licence.read_text(encoding="utf-8")


def test_fb_alias_resolves_to_the_clone(fb_alias: str, fb_clone: str) -> None:
    from django.db import connections

    assert connections[fb_alias].settings_dict["NAME"] == fb_clone
