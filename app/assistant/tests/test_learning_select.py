"""Tests for choosing which learned examples the assistant sees, the usage label and the export payload."""

import json
from datetime import datetime, timedelta
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone

from assistant import learning
from assistant.models import HelpExample, Kind

pytestmark = pytest.mark.django_db

KEY = "leave.record"
BASE = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.get_current_timezone())


def _make(question: str, entry: str = KEY, kind: str = Kind.EXAMPLE, active: bool = True, days: int = 0) -> HelpExample:
    """A row whose created_at is `BASE + days`; auto_now_add is overridden with update()."""
    row = HelpExample.objects.create(question=question, entry=entry, kind=kind, active=active)
    HelpExample.objects.filter(pk=row.pk).update(created_at=BASE + timedelta(days=days))
    row.refresh_from_db()
    return row


def test_cap_keeps_newest() -> None:
    for i in range(12):
        _make(f"асуулт {i:02d}", days=i)
    with override_settings(ASSISTANT_EXAMPLES_PER_ENTRY=10):
        chosen = learning.learned_by_entry()[KEY]
    assert chosen == tuple(f"асуулт {i:02d}" for i in range(11, 1, -1))


def test_no_entry_cap() -> None:
    for i in range(12):
        _make(f"байхгүй {i:02d}", entry="", days=i)
    with override_settings(ASSISTANT_NO_ENTRY_EXAMPLES=10):
        chosen = learning.no_entry_questions()
    assert chosen == tuple(f"байхгүй {i:02d}" for i in range(11, 1, -1))


def test_orphans_ignored() -> None:
    _make("хуучин асуулт", entry="leave.gone")
    _make("хуучин тест", entry="leave.gone", kind=Kind.TEST)
    assert "leave.gone" not in learning.learned_by_entry()
    assert "хуучин асуулт" not in learning.no_entry_questions()
    assert [row.question for row in learning.local_tests()] == []


def test_inactive_ignored() -> None:
    _make("идэвхгүй жишээ", active=False)
    _make("идэвхгүй хоосон", entry="", active=False)
    _make("идэвхгүй тест", kind=Kind.TEST, active=False)
    assert learning.learned_by_entry() == {}
    assert learning.no_entry_questions() == ()
    assert learning.local_tests() == []


def test_used_ids_match() -> None:
    kept = _make("зөв жишээ", days=1)
    _make("хоосон жишээ", entry="", days=1)
    with override_settings(ASSISTANT_EXAMPLES_PER_ENTRY=1, ASSISTANT_NO_ENTRY_EXAMPLES=1):
        _make("хамгийн шинэ", days=5)
        used = learning.used_example_ids()
    assert kept.pk not in used
    assert len(used) == 2


def test_used_ids_one_query(django_assert_num_queries: Any) -> None:
    _make("жишээ нэг", days=1)
    _make("хоосон нэг", entry="", days=1)
    with django_assert_num_queries(1):
        learning.used_example_ids()


def test_usage_labels() -> None:
    orphan = HelpExample(pk=1, question="а", entry="leave.gone", kind=Kind.EXAMPLE, active=True)
    inactive = HelpExample(pk=2, question="б", entry=KEY, kind=Kind.EXAMPLE, active=False)
    test_row = HelpExample(pk=3, question="в", entry=KEY, kind=Kind.TEST, active=True)
    used = HelpExample(pk=4, question="г", entry=KEY, kind=Kind.EXAMPLE, active=True)
    spare = HelpExample(pk=5, question="д", entry=KEY, kind=Kind.EXAMPLE, active=True)
    selected = {4}
    assert learning.usage_label(orphan, selected) == "Энэ хариулт байхгүй болсон"
    assert learning.usage_label(inactive, selected) == "Идэвхгүй"
    assert learning.usage_label(test_row, selected) == "Тест"
    assert learning.usage_label(used, selected) == "Ашиглагдаж байна"
    assert learning.usage_label(spare, selected) == "Хязгаараас хэтэрсэн"


def test_local_tests_oldest_first() -> None:
    _make("тест хоёр", kind=Kind.TEST, days=2)
    _make("тест нэг", kind=Kind.TEST, days=1)
    _make("хоосон тест", entry="", kind=Kind.TEST, days=3)
    assert [row.question for row in learning.local_tests()] == ["тест нэг", "тест хоёр", "хоосон тест"]


def test_export_payload_shape() -> None:
    live_example = _make("жишээ асуулт", days=1)
    live_test = _make("тест асуулт", kind=Kind.TEST, days=2)
    rows = [
        live_example,
        live_test,
        _make("идэвхгүй", active=False),
        _make("хуучин", entry="leave.gone"),
    ]
    payload = learning.export_payload(rows)
    assert set(payload) == {"exported_at", "examples", "tests"}
    assert payload["examples"] == [{"question": "жишээ асуулт", "entry": KEY, "expected": ""}]
    assert payload["tests"] == [{"question": "тест асуулт", "entry": KEY, "expected": ""}]
    assert datetime.fromisoformat(payload["exported_at"]).tzinfo is not None
    text = json.dumps(payload, ensure_ascii=False)
    assert "created_by" not in text
    assert "source" not in text
    assert "active" not in text
