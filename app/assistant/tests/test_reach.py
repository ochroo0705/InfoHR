"""Reach checks: the role lists match the real users, every entry opens, and every label is on a screen."""

from collections.abc import Callable
from datetime import date

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from employees.models import EmployeeExt, JobRecord
from leave.models import LeaveSettings, LeaveTypeExt
from leave.services import requests as request_service
from macs.models import LeaveTypeRow

from assistant.entries import ENTRY_BY_KEY, allowed_entries
from assistant.evalset import ROLE_ENTRIES, ROLES

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 4)
PASSWORD = "x-long-pass-123"  # noqa: S105
# role -> (fixture kind, approval on?)
ROLE_SETUP: dict[str, tuple[str, bool]] = {
    "hr": ("hr", True),
    "hr_off": ("hr", False),
    "accountant": ("accountant", True),
    "staff": ("staff", True),
    "staff_off": ("staff", False),
    "approver": ("approver", True),
    "none": ("none", True),
}
PAIRS = [(key, role) for role in ROLES for key in ROLE_ENTRIES[role]]


def _set_approval(on: bool) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": on})


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _page(client: Client, url: str, modal: bool) -> str:
    headers = {"HX-Request": "true"} if modal else {}
    resp = client.get(url, headers=headers)
    assert resp.status_code == 200, url
    return resp.content.decode()


def _waiting_detail(role_user: Callable[[str], User]) -> tuple[User, str]:
    """A line manager (approver) with one waiting request from a report. Returns the manager and the detail URL."""
    boss = role_user("approver")
    own = EmployeeExt.objects.get(user=boss).employee
    report = JobRecord.objects.filter(manager=own).first().employee  # type: ignore[union-attr]
    creator = User.objects.create_superuser("help_creator", password=PASSWORD)  # a line manager may not be the creator
    leave_type = LeaveTypeRow.objects.create(name="Туршилтын амралт")
    LeaveTypeExt.objects.create(leave_type=leave_type, uses_annual_balance=False, is_paid=True)
    req = request_service.submit(report, leave_type, date(2026, 11, 10), date(2026, 11, 11), "", creator, TODAY)
    return boss, reverse("leave:request_detail", args=[req.pk])


@pytest.mark.parametrize("role", ROLES)
def test_role_entries_match_real_users(role_user: Callable[[str], User], role: str) -> None:
    kind, approval = ROLE_SETUP[role]
    _set_approval(approval)
    user = role_user(kind)
    assert [e.key for e in allowed_entries(user, TODAY)] == list(ROLE_ENTRIES[role])


@pytest.mark.parametrize(("key", "role"), PAIRS)
def test_every_entry_opens_for_its_user(role_user: Callable[[str], User], key: str, role: str) -> None:
    entry = ENTRY_BY_KEY[key]
    kind, approval = ROLE_SETUP[role]
    _set_approval(approval)
    client = _client(role_user(kind))
    _page(client, entry.url(), entry.modal)


@pytest.mark.parametrize(("key", "role"), PAIRS)
def test_every_label_is_on_screen(role_user: Callable[[str], User], key: str, role: str) -> None:
    entry = ENTRY_BY_KEY[key]
    kind, approval = ROLE_SETUP[role]
    _set_approval(approval)
    client = _client(role_user(kind))
    bodies = [_page(client, entry.url(), entry.modal)]
    if key == "leave.request":
        bodies.append(_page(client, reverse("me"), False))
    elif key != "leave.decide":  # the requests page is the entry itself; an approver may not see leave:list
        bodies.append(_page(client, reverse("leave:list"), False))
    if key == "leave.decide":
        # Батлах / Татгалзах are on the request detail page, seen by the line manager of a waiting request.
        boss, detail_url = _waiting_detail(role_user)
        bodies.append(_page(_client(boss), detail_url, False))
    missing = [label for label in entry.labels if not any(label in body for body in bodies)]
    assert not missing, f"{key} as {role}: not on screen: {missing}"
