"""Tests for the learning-loop model: HelpExample, the allowed-keys field on the log, settings and permissions."""

from collections.abc import Callable
from datetime import date

import pytest
from accounts.models import User
from django.conf import settings
from django.contrib.auth.models import Group, Permission

from assistant.entries import allowed_entries
from assistant.models import HelpExample, HelpQuestion, Kind
from assistant.providers import Choice
from assistant.services import answer
from assistant.tests.test_services import FakeProvider

QUESTION = "яаж чөлөө бүртгэх вэ"

pytestmark = pytest.mark.django_db


def test_example_defaults() -> None:
    example = HelpExample.objects.create(question=QUESTION, entry="leave.record")
    example.refresh_from_db()
    assert example.kind == Kind.EXAMPLE
    assert example.active is True
    assert example.created_at is not None
    assert example.changed_at is not None
    assert example.source is None
    assert example.created_by is None


def test_admin_group_perms() -> None:
    admin = Group.objects.get(name="Admin")
    hr = Group.objects.get(name="HR")
    codenames = {"view_helpexample", "add_helpexample", "change_helpexample"}
    granted = set(
        admin.permissions.filter(content_type__app_label="assistant", codename__endswith="helpexample").values_list(
            "codename", flat=True
        )
    )
    assert granted == codenames
    assert not admin.permissions.filter(codename="delete_helpexample").exists()
    assert not hr.permissions.filter(content_type__app_label="assistant", codename__endswith="helpexample").exists()
    assert Permission.objects.filter(codename="delete_helpexample", content_type__app_label="assistant").exists()


def test_log_stores_allowed_keys(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө бүртгэх хэсэг."))
    answer(user, QUESTION, date(2026, 11, 4), provider)
    row = HelpQuestion.objects.get(user=user)
    hr_keys = (
        "leave.record,leave.balances,leave.calendar,today.home,today.attention,employee.find,employee.hire,"
        "employee.import,employee.work_fields,employee.note,employee.login,employee.setup,"
        "employee.placement,employee.contract,employee.leave_start,employee.leave_return,employee.termination,"
        "employee.rehire,employee.cancel_change,employee.correct_job,employee.personal_sections,"
        "employee.personal_lists,order.register,order.print,order.edit,order.upload,order.cancel,"
        "order.document,recruit.vacancies,recruit.vacancy_add,recruit.vacancy_edit,recruit.vacancy,"
        "recruit.candidate_add,recruit.candidate,recruit.move,recruit.reject,recruit.reopen,recruit.comment,"
        "recruit.file,recruit.convert,recruit.purge,checklist.mine,checklist.undo,checklist.start,"
        "report.catalogue,report.export,report.annual-leave,report.absences,report.away-on-date,report.absence-totals,report.saved_view,report.staff-list,report.children,report.contacts,report.engineers,report.movements,report.history,report.leavers,report.orders,report.discipline,report.awards,report.training,report.health-checks,report.skill-tasks,report.complaints,report.gifts-given,report.gifts-due,report.performance,report.performance-summary,report.accidents,report.poisoning,"
        "log.employee,list.index,list.entry,list.meaning,settings.slots,settings.slot_edit,me.password"
    )
    assert row.allowed == hr_keys


def test_log_stores_long_allowed_list(role_user: Callable[[str], User]) -> None:
    """The Admin list is longer than the old 300-character limit; the whole list is logged."""
    user = role_user("admin")
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө бүртгэх хэсэг."))
    answer(user, QUESTION, date(2026, 11, 4), provider)
    row = HelpQuestion.objects.get(user=user)
    expected = ",".join(e.key for e in allowed_entries(user, date(2026, 11, 4)))
    assert row.allowed == expected
    assert len(expected) > 300


def test_settings_types() -> None:
    assert isinstance(settings.ASSISTANT_EXAMPLES_PER_ENTRY, int)
    assert isinstance(settings.ASSISTANT_NO_ENTRY_EXAMPLES, int)
    assert isinstance(settings.ASSISTANT_SIMILARITY, float)
