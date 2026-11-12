import re
from collections.abc import Callable
from datetime import date

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from employees.models import CompanySettings, EmployeeExt

from assistant.entries import ENTRIES, ENTRY_BY_KEY, allowed_entries
from assistant.entry import HelpEntry
from assistant.evalset import ROLE_ENTRIES
from assistant.tests.helpers import new_candidate, on_screen, open_vacancy

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 4)
# What a role must be offered and must never be offered: a few facts about the rights. The full lists are not kept
# here: evalset.ROLE_ENTRIES is built from `allowed_entries` for a real user of each role (conftest.py).
ROLE_RULES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "hr": (
        frozenset(
            {
                "leave.record",
                "leave.decide",
                "leave.balances",
                "leave.calendar",
                "employee.hire",
                "employee.import",
                "employee.placement",
                "order.edit",
                "recruit.vacancy_add",
                "checklist.start",
                "report.staff-list",
                "report.saved_view",
                "settings.slots",
            }
        ),
        frozenset(
            {"leave.requests", "employee.salary_change", "employee.first_salary", "settings.users", "settings.roles"}
        ),
    ),
    "hr_off": (
        frozenset({"leave.record", "leave.balances", "leave.calendar", "employee.hire", "order.edit"}),
        frozenset({"leave.decide", "leave.requests", "employee.salary_change", "settings.users"}),
    ),
    "accountant": (
        frozenset(
            {
                "leave.requests",
                "employee.salary_change",
                "employee.correct_salary",
                "employee.first_salary",
                "employee.bank_insurance",
                "order.register",
                "report.household-income",
                "report.loans",
                "log.employee",
            }
        ),
        frozenset({"employee.hire", "order.edit", "leave.record", "recruit.vacancies", "settings.slots"}),
    ),
    "admin": (
        frozenset({"leave.record", "employee.salary_change", "checklist.templates", "settings.assistant"}),
        frozenset({"leave.request", "settings.users"}),
    ),
}

MANAGING_RECRUIT_KEYS = [
    "recruit.vacancy_add",
    "recruit.vacancy_edit",
    "recruit.candidate_add",
    "recruit.move",
    "recruit.reject",
    "recruit.reopen",
    "recruit.file",
    "recruit.convert",
    "recruit.purge",
]


def keys(entries: list[HelpEntry]) -> list[str]:
    return [e.key for e in entries]


@pytest.mark.parametrize("role", list(ROLE_RULES))
def test_role_rules(role: str) -> None:
    must, never = ROLE_RULES[role]
    offered = set(ROLE_ENTRIES[role])
    assert not must - offered, f"{role} is missing {sorted(must - offered)}"
    assert not never & offered, f"{role} is offered {sorted(never & offered)}"


@pytest.mark.parametrize("role", ["hr", "hr_off", "accountant", "staff", "staff_off", "approver", "admin", "auditor"])
def test_role_lists_follow_the_entries_order(role: str) -> None:
    """The role lists come from `allowed_entries`: no key twice, the fixed entries in ENTRIES order. Entries built from
    the database (saved views, templates) follow them and are not in ENTRIES."""
    listed = list(ROLE_ENTRIES[role])
    assert len(set(listed)) == len(listed)
    fixed = [key for key in listed if key in ENTRY_BY_KEY]
    assert fixed == [e.key for e in ENTRIES if e.key in set(fixed)]
    assert listed[: len(fixed)] == fixed  # the built ones come after the fixed ones


def test_auditor_sees_only_the_log(role_user: Callable[[str], User]) -> None:
    assert keys(allowed_entries(role_user("auditor"), TODAY)) == ["checklist.mine", "log.system", "me.password"]


def test_staff_with_approval(role_user: Callable[[str], User], approval_on: None) -> None:
    assert keys(allowed_entries(role_user("staff"), TODAY)) == [
        "leave.request",
        "checklist.mine",
        "me.page",
        "me.password",
    ]


def test_staff_without_approval(role_user: Callable[[str], User]) -> None:
    assert keys(allowed_entries(role_user("staff"), TODAY)) == ["checklist.mine", "me.page", "me.password"]


def test_approver_with_approval(role_user: Callable[[str], User], approval_on: None) -> None:
    assert keys(allowed_entries(role_user("approver"), TODAY)) == [
        "leave.request",
        "leave.decide",
        "checklist.mine",
        "me.page",
        "me.password",
    ]


def test_no_rights(role_user: Callable[[str], User]) -> None:
    assert keys(allowed_entries(role_user("none"), TODAY)) == ["checklist.mine", "me.password"]


def test_keys_unique_and_urls_reverse() -> None:
    assert len(ENTRY_BY_KEY) == len(ENTRIES)
    for entry in ENTRIES:
        assert entry.url()


def test_every_quoted_label_is_listed() -> None:
    for entry in ENTRIES:
        quoted = re.findall(r"«([^«»]+)»", " ".join(entry.steps) + entry.note)
        missing = [label for label in quoted if label not in entry.labels]
        assert not missing, f"{entry.key} does not list {missing}"


def test_hiring_manager_gets_lookup_recruit_entries_only(role_user: Callable[[str], User]) -> None:
    """A staff login named as a vacancy's hiring manager (no recruitment right) gets the look-up entries, their labels
    are on the screens it may open, and none of the managing entries."""
    actor = role_user("hr")
    user = role_user("staff")
    own = EmployeeExt.objects.get(user=user).employee
    vacancy = open_vacancy(actor, manager=own)
    candidate = new_candidate(actor, vacancy)
    recruit_keys = [k for k in keys(allowed_entries(user, TODAY)) if k.startswith("recruit.")]
    assert recruit_keys == ["recruit.vacancies", "recruit.vacancy", "recruit.candidate", "recruit.comment"]
    assert not set(MANAGING_RECRUIT_KEYS) & set(recruit_keys)
    client = Client()
    client.force_login(user)
    bodies = [
        client.get(reverse("recruitment:vacancies")).content.decode(),
        client.get(reverse("recruitment:vacancy_detail", args=[vacancy.pk])).content.decode(),
        client.get(reverse("recruitment:candidate_detail", args=[candidate.pk])).content.decode(),
    ]
    for key in recruit_keys:
        missing = [x for x in ENTRY_BY_KEY[key].labels if not any(on_screen(x, b) for b in bodies)]
        assert not missing, f"{key} as a hiring manager: not on screen: {missing}"


def test_order_cancel_hidden_when_hire_order_off(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    CompanySettings.objects.update_or_create(pk=1, defaults={"order_hired": False})
    assert "order.cancel" not in keys(allowed_entries(user, TODAY))
    CompanySettings.objects.update_or_create(pk=1, defaults={"order_hired": True})
    assert "order.cancel" in keys(allowed_entries(user, TODAY))
