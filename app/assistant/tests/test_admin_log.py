"""Tests for the question log admin: correction columns, name flag, query count, sidebar group and audit."""

import itertools
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import SystemLogEntry, User
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

from assistant.models import HelpExample, HelpQuestion, Kind, Outcome

PASSWORD = "Test-pass-1"  # noqa: S105
KEY = "leave.record"
QUESTION = "ажилтны мэдээлэл хаана харагдах вэ"
_COUNTER = itertools.count(1)

pytestmark = pytest.mark.django_db

LOG = reverse("admin:assistant_helpquestion_changelist")
ADD = reverse("admin:assistant_helpexample_add")


def _staff(client: Client, group: str) -> User:
    """A staff login in the given group; the group decides what it may do."""
    user = User.objects.create_user(f"log_{next(_COUNTER)}", password=PASSWORD, is_staff=True)
    user.groups.add(Group.objects.get(name=group))
    client.force_login(user)
    return user


def _employee(given: str) -> None:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = hire_values(f"УБ{next(_COUNTER):08d}") | {"given_name": given}
    history.hire(
        values,
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=User.objects.create_user(f"log_actor_{next(_COUNTER)}"),
    )


def _question(user: User, text: str) -> HelpQuestion:
    return HelpQuestion.objects.create(user=user, question=text, entry=KEY, outcome=Outcome.ANSWERED, allowed=KEY)


def test_log_shows_fix_link_and_corrected(client: Client) -> None:
    user = _staff(client, "Admin")
    corrected = _question(user, "асуулт нэг")
    plain = _question(user, "асуулт хоёр")
    HelpExample.objects.create(question="засвар нэг", entry=KEY, source=corrected, active=True)
    HelpExample.objects.create(question="засвар хоёр", entry=KEY, source=plain, active=False)

    response = client.get(LOG)

    assert response.status_code == 200
    html = response.content.decode()
    assert "Засах" in html
    assert f"{ADD}?source={corrected.pk}" in html
    flags = {row.pk: row.corrected for row in response.context["cl"].result_list}
    assert flags == {corrected.pk: True, plain.pk: False}


def test_fix_link_hidden_without_add_permission(client: Client) -> None:
    user = User.objects.create_user(f"log_viewer_{next(_COUNTER)}", password=PASSWORD, is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_helpquestion"))
    client.force_login(user)
    log = _question(user, "асуулт нэг")

    response = client.get(LOG)

    assert response.status_code == 200
    html = response.content.decode()
    assert "асуулт нэг" in html  # positive control: the row is rendered
    assert f"{ADD}?source={log.pk}" not in html


def test_name_flag(client: Client) -> None:
    user = _staff(client, "Admin")
    _employee("Номин")
    _question(user, "Номин өнөөдөр ирээгүй")
    _question(user, "чөлөө бүртгэх")

    html = client.get(LOG).content.decode()

    assert html.count("⚠ Нэр") == 1


def test_log_changelist_queries_flat(client: Client) -> None:
    user = _staff(client, "Admin")

    def add_rows(count: int) -> None:
        for _ in range(count):
            _question(user, f"асуулт {next(_COUNTER)}")

    def count_queries() -> int:
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(LOG).status_code == 200
        return len(ctx.captured_queries)

    add_rows(2)
    count_queries()  # warm-up: content types and permissions are cached after the first request
    few = count_queries()
    add_rows(10)
    many = count_queries()
    assert few == many


def test_sidebar_has_assistant_group(client: Client) -> None:
    unfold: dict[str, Any] = settings.UNFOLD
    titles = [group["title"] for group in unfold["SIDEBAR"]["navigation"]]
    assert titles[titles.index("Тохиргоо") + 1] == "Туслах"

    _staff(client, "Admin")
    html = client.get(reverse("admin:index")).content.decode()
    assert "Туслахын асуултууд" in html
    assert "Сурсан жишээ, тест" in html


def test_correction_is_audited(client: Client) -> None:
    _staff(client, "Admin")

    response = client.post(
        ADD, {"question": QUESTION, "entry": KEY, "kind": Kind.EXAMPLE, "active": "on", "source": ""}
    )

    assert response.status_code == 302
    [entry] = SystemLogEntry.objects.filter(action="setting_added", target_label=QUESTION)
    assert entry.category == "settings"
    assert entry.actor_name.startswith("log_")


def test_bulk_deactivate_is_audited(client: Client) -> None:
    _staff(client, "Admin")
    first = HelpExample.objects.create(question="идэвхтэй нэг", entry=KEY, active=True)
    second = HelpExample.objects.create(question="идэвхтэй хоёр", entry=KEY, active=True)

    response = client.post(
        reverse("admin:assistant_helpexample_changelist"),
        {"action": "deactivate", "_selected_action": [first.pk, second.pk], "index": 0},
        follow=True,
    )

    assert response.status_code == 200
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.active is False
    assert second.active is False
    entries = SystemLogEntry.objects.filter(
        action="setting_changed", target_label__in=[first.question, second.question]
    )
    assert sorted(entry.target_label for entry in entries) == sorted([first.question, second.question])
    assert all(entry.actor_name.startswith("log_") for entry in entries)
