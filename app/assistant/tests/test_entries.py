import re
from collections.abc import Callable
from datetime import date

import pytest
from accounts.models import User

from assistant.entries import ENTRIES, ENTRY_BY_KEY, HelpEntry, allowed_entries

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 4)


def keys(entries: list[HelpEntry]) -> list[str]:
    return [e.key for e in entries]


def test_hr_with_approval(role_user: Callable[[str], User], approval_on: None) -> None:
    assert keys(allowed_entries(role_user("hr"), TODAY)) == [
        "leave.record",
        "leave.decide",
        "leave.balances",
        "leave.calendar",
    ]


def test_hr_without_approval(role_user: Callable[[str], User]) -> None:
    assert keys(allowed_entries(role_user("hr"), TODAY)) == ["leave.record", "leave.balances", "leave.calendar"]


def test_accountant_with_approval(role_user: Callable[[str], User], approval_on: None) -> None:
    assert keys(allowed_entries(role_user("accountant"), TODAY)) == [
        "leave.requests",
        "leave.balances",
        "leave.calendar",
    ]


def test_staff_with_approval(role_user: Callable[[str], User], approval_on: None) -> None:
    assert keys(allowed_entries(role_user("staff"), TODAY)) == ["leave.request"]


def test_staff_without_approval(role_user: Callable[[str], User]) -> None:
    assert keys(allowed_entries(role_user("staff"), TODAY)) == []


def test_approver_with_approval(role_user: Callable[[str], User], approval_on: None) -> None:
    assert keys(allowed_entries(role_user("approver"), TODAY)) == ["leave.request", "leave.decide"]


def test_no_rights(role_user: Callable[[str], User]) -> None:
    assert keys(allowed_entries(role_user("none"), TODAY)) == []


def test_keys_unique_and_urls_reverse() -> None:
    assert len(ENTRY_BY_KEY) == len(ENTRIES) == 6
    for entry in ENTRIES:
        assert entry.url()


def test_every_quoted_label_is_listed() -> None:
    for entry in ENTRIES:
        quoted = re.findall(r"«([^«»]+)»", " ".join(entry.steps) + entry.note)
        missing = [label for label in quoted if label not in entry.labels]
        assert not missing, f"{entry.key} does not list {missing}"
