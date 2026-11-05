"""Tests for the assistant_export command: the corrections written to a JSON file."""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from assistant.entries import ENTRIES
from assistant.models import HelpExample, Kind


@pytest.fixture
def corrections(db: None) -> None:
    """Two active examples and one active test on a real entry, one inactive example, all in the database."""
    entry = ENTRIES[0].key
    HelpExample.objects.create(question="Жишээ нэг", entry=entry, kind=Kind.EXAMPLE, active=True)
    HelpExample.objects.create(question="Жишээ хоёр", entry="", kind=Kind.EXAMPLE, active=True)
    HelpExample.objects.create(question="Тест нэг", entry=entry, kind=Kind.TEST, active=True)
    HelpExample.objects.create(question="Идэвхгүй", entry=entry, kind=Kind.EXAMPLE, active=False)


def test_export_writes_file(corrections: None, tmp_path: Path) -> None:
    out = tmp_path / "export.json"
    stdout = StringIO()

    call_command("assistant_export", "--out", str(out), stdout=stdout)

    assert stdout.getvalue().strip() == f"Wrote 2 examples and 1 tests to {out}"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"exported_at", "examples", "tests"}
    assert sorted(item["question"] for item in data["examples"]) == ["Жишээ нэг", "Жишээ хоёр"]
    assert [item["question"] for item in data["tests"]] == ["Тест нэг"]
    assert "Идэвхгүй" not in out.read_text(encoding="utf-8")
