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
from assistant.tests.helpers import new_candidate, on_screen, open_vacancy

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 4)
# The HR role's entries of the areas (today, employee, order, recruit, checklist, report, log, list, settings, me),
# in ENTRIES order.
HR_AREA_KEYS = [
    "today.home",
    "today.attention",
    "employee.find",
    "employee.hire",
    "employee.import",
    "employee.work_fields",
    "employee.note",
    "employee.login",
    "employee.setup",
    "employee.placement",
    "employee.contract",
    "employee.leave_start",
    "employee.leave_return",
    "employee.termination",
    "employee.rehire",
    "employee.cancel_change",
    "employee.correct_job",
    "employee.personal_sections",
    "employee.personal_lists",
    "order.register",
    "order.print",
    "order.edit",
    "order.upload",
    "order.cancel",
    "order.document",
    "recruit.vacancies",
    "recruit.vacancy_add",
    "recruit.vacancy_edit",
    "recruit.vacancy",
    "recruit.candidate_add",
    "recruit.candidate",
    "recruit.move",
    "recruit.reject",
    "recruit.reopen",
    "recruit.comment",
    "recruit.file",
    "recruit.convert",
    "recruit.purge",
    "checklist.mine",
    "checklist.undo",
    "checklist.start",
    "report.catalogue",
    "report.export",
    "report.annual-leave",
    "report.absences",
    "report.away-on-date",
    "report.absence-totals",
    "report.saved_view",
    "report.staff-list",
    "report.children",
    "report.contacts",
    "report.engineers",
    "report.movements",
    "report.history",
    "report.leavers",
    "report.orders",
    "report.discipline",
    "report.awards",
    "report.training",
    "report.health-checks",
    "report.skill-tasks",
    "report.complaints",
    "report.gifts-given",
    "report.gifts-due",
    "report.performance",
    "report.performance-summary",
    "report.accidents",
    "report.poisoning",
    "log.employee",
    "list.index",
    "list.entry",
    "list.meaning",
    "settings.slots",
    "settings.slot_edit",
    "me.password",
]

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


def test_hr_with_approval(role_user: Callable[[str], User], approval_on: None) -> None:
    assert keys(allowed_entries(role_user("hr"), TODAY)) == [
        "leave.record",
        "leave.decide",
        "leave.balances",
        "leave.calendar",
        *HR_AREA_KEYS,
    ]


def test_hr_without_approval(role_user: Callable[[str], User]) -> None:
    assert keys(allowed_entries(role_user("hr"), TODAY)) == [
        "leave.record",
        "leave.balances",
        "leave.calendar",
        *HR_AREA_KEYS,
    ]


def test_accountant_with_approval(role_user: Callable[[str], User], approval_on: None) -> None:
    assert keys(allowed_entries(role_user("accountant"), TODAY)) == [
        "leave.requests",
        "leave.balances",
        "leave.calendar",
        "today.home",
        "today.attention",
        "employee.find",
        "employee.salary_change",
        "employee.correct_salary",
        "employee.first_salary",
        "employee.bank_insurance",
        "order.register",
        "order.print",
        "checklist.mine",
        "report.catalogue",
        "report.export",
        "report.annual-leave",
        "report.absences",
        "report.away-on-date",
        "report.absence-totals",
        "report.saved_view",
        "report.staff-list",
        "report.engineers",
        "report.household-income",
        "report.movements",
        "report.history",
        "report.leavers",
        "report.orders",
        "report.loans",
        "log.employee",
        "me.password",
    ]


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
    assert len(ENTRY_BY_KEY) == len(ENTRIES) == 98
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
