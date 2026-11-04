"""Tests for the corrections admin: access, form rules, prefill from the log, name hints, query count."""

import itertools
import json
import re
from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

from assistant.entries import ENTRIES, ENTRY_BY_KEY
from assistant.models import HelpExample, HelpQuestion, Kind, Outcome

PASSWORD = "Test-pass-1"  # noqa: S105
KEY = "leave.record"
QUESTION = "ажилтны мэдээлэл хаана харагдах вэ"
SHIPPED = next(example for entry in ENTRIES for example in entry.examples)
_COUNTER = itertools.count(1)

pytestmark = pytest.mark.django_db

CHANGELIST = reverse("admin:assistant_helpexample_changelist")
ADD = reverse("admin:assistant_helpexample_add")


def _staff(client: Client, group: str | None) -> User:
    """A staff login (may reach the admin site) in the given group; the group decides what it may do."""
    user = User.objects.create_user(f"corr_{next(_COUNTER)}", password=PASSWORD, is_staff=True)
    if group is not None:
        user.groups.add(Group.objects.get(name=group))
    client.force_login(user)
    return user


def _post_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"question": QUESTION, "entry": KEY, "kind": Kind.EXAMPLE, "active": "on", "source": ""}
    data.update(overrides)
    return data


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
        by=User.objects.create_user(f"corr_actor_{next(_COUNTER)}"),
    )


def test_admin_can_add_and_list(client: Client) -> None:
    user = _staff(client, "Admin")
    response = client.post(ADD, _post_data())
    assert response.status_code == 302
    row = HelpExample.objects.get(question=QUESTION)
    assert row.entry == KEY
    assert row.created_by == user
    assert client.get(CHANGELIST).status_code == 200
    assert QUESTION in client.get(CHANGELIST).content.decode()


def test_hr_forbidden(client: Client) -> None:
    _staff(client, "HR")
    assert client.get(CHANGELIST).status_code == 403


def test_no_delete(client: Client) -> None:
    _staff(client, "Admin")
    row = HelpExample.objects.create(question=QUESTION, entry=KEY)
    url = reverse("admin:assistant_helpexample_delete", args=[row.pk])
    assert client.get(url).status_code == 403
    assert client.post(url, {"post": "yes"}).status_code == 403
    assert HelpExample.objects.filter(pk=row.pk).exists()


def test_prefill_from_log(client: Client) -> None:
    user = _staff(client, "Admin")
    log = HelpQuestion.objects.create(
        user=user, question="яаж чөлөө бүртгэх вэ", entry=KEY, outcome=Outcome.ANSWERED, allowed=KEY
    )
    response = client.get(ADD, {"source": log.pk})
    assert response.status_code == 200
    assert "яаж чөлөө бүртгэх вэ" in response.content.decode()
    assert response.context["adminform"].form["entry"].value() == KEY

    response = client.post(ADD, _post_data(question="яаж чөлөө бүртгэх вэ", source=log.pk))
    assert response.status_code == 302
    row = HelpExample.objects.get(question="яаж чөлөө бүртгэх вэ")
    assert row.source == log
    assert row.created_by == user


def test_form_refuses_close_test(client: Client) -> None:
    _staff(client, "Admin")
    response = client.post(ADD, _post_data(question=SHIPPED, kind=Kind.TEST))
    assert response.status_code == 200
    assert "жишээтэй хэт ойролцоо" in response.content.decode()
    assert not HelpExample.objects.filter(question=SHIPPED).exists()


def test_name_warning_shown(client: Client) -> None:
    _staff(client, "Admin")
    _employee("Номин")
    row = HelpExample.objects.create(question="Номин өнөөдөр өвдөөд ирээгүй", entry=KEY)
    response = client.get(reverse("admin:assistant_helpexample_change", args=[row.pk]))
    assert response.status_code == 200
    assert "Нэр байж магадгүй" in response.content.decode()


def test_changelist_queries_flat(client: Client) -> None:
    user = _staff(client, "Admin")
    log = HelpQuestion.objects.create(user=user, question="асуулт", entry=KEY, outcome=Outcome.ANSWERED, allowed=KEY)

    def add_rows(count: int) -> None:
        for _ in range(count):
            HelpExample.objects.create(
                question=f"жишээ асуулт {next(_COUNTER)}", entry=KEY, created_by=user, source=log
            )

    def count_queries() -> int:
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(CHANGELIST).status_code == 200
        return len(ctx.captured_queries)

    add_rows(2)
    count_queries()  # warm-up: content types and permissions are cached after the first request
    few = count_queries()
    add_rows(10)
    many = count_queries()
    assert few == many


def test_hidden_source_is_a_form_field() -> None:
    from assistant.admin import HelpExampleAdmin

    assert HelpExampleAdmin.form.base_fields["source"].widget.input_type == "hidden"


def test_bulk_activate_skips_conflicts(client: Client) -> None:
    _staff(client, "Admin")
    valid = HelpExample.objects.create(question=QUESTION, entry=KEY, active=False)
    near_copy = HelpExample.objects.create(question=SHIPPED, entry=KEY, kind=Kind.TEST, active=False)
    duplicate = HelpExample.objects.create(question=QUESTION, entry=KEY, active=False)
    response = client.post(
        CHANGELIST,
        {"action": "activate", "_selected_action": [valid.pk, near_copy.pk, duplicate.pk], "index": 0},
        follow=True,
    )
    assert response.status_code == 200
    valid.refresh_from_db()
    near_copy.refresh_from_db()
    duplicate.refresh_from_db()
    assert valid.active is True
    assert near_copy.active is False
    assert duplicate.active is False  # checked after `valid` was switched on, so it is a duplicate now
    message = " ".join(str(m) for m in response.context["messages"])
    assert "1 идэвхжлээ, 2 алгаслаа" in message
    assert SHIPPED in message
    assert "жишээтэй хэт ойролцоо" in message


def test_export_action(client: Client) -> None:
    _staff(client, "Admin")
    active = HelpExample.objects.create(question=QUESTION, entry=KEY, active=True)
    test_row = HelpExample.objects.create(question="тест асуулт нэг", entry=KEY, kind=Kind.TEST, active=True)
    off = HelpExample.objects.create(question="идэвхгүй асуулт", entry=KEY, active=False)
    response = client.post(
        CHANGELIST,
        {"action": "export_json", "_selected_action": [active.pk, test_row.pk, off.pk], "index": 0},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json; charset=utf-8"
    disposition = response["Content-Disposition"]
    assert re.fullmatch(r'attachment; filename="assistant_export_\d{4}-\d{2}-\d{2}\.json"', disposition)
    payload = json.loads(response.content.decode("utf-8"))
    assert set(payload) >= {"exported_at", "examples", "tests"}
    assert payload["examples"] == [{"question": QUESTION, "entry": KEY}]
    assert payload["tests"] == [{"question": "тест асуулт нэг", "entry": KEY}]


def test_orphan_kept_on_save(client: Client) -> None:
    _staff(client, "Admin")
    row = HelpExample.objects.create(question=QUESTION, entry="leave.gone", active=False)
    url = reverse("admin:assistant_helpexample_change", args=[row.pk])
    response = client.get(url)
    assert response.context["adminform"].form["entry"].value() == "leave.gone"
    response = client.post(url, _post_data(entry="leave.gone", active=""))
    assert response.status_code == 302
    row.refresh_from_db()
    assert row.entry == "leave.gone"
    assert row.active is False


def test_orphan_active_refused(client: Client) -> None:
    _staff(client, "Admin")
    row = HelpExample.objects.create(question=QUESTION, entry="leave.gone", active=False)
    url = reverse("admin:assistant_helpexample_change", args=[row.pk])
    response = client.post(url, _post_data(entry="leave.gone", active="on"))
    assert response.status_code == 200
    assert "Энэ хариулт байхгүй болсон байна." in response.content.decode()
    row.refresh_from_db()
    assert row.active is False
    assert row.entry == "leave.gone"


def test_prefill_shows_name_warning_and_asker_entries(client: Client) -> None:
    user = _staff(client, "Admin")
    _employee("Номин")
    log = HelpQuestion.objects.create(
        user=user,
        question="Номин яаж чөлөө бүртгэх вэ",
        entry=KEY,
        outcome=Outcome.ANSWERED,
        allowed="leave.record,leave.balances",
    )
    response = client.get(ADD, {"source": log.pk})
    assert response.status_code == 200
    content = response.content.decode()
    assert "Нэр байж магадгүй" in content
    assert "Асуусан хүнд боломжтой байсан" in content
    assert ENTRY_BY_KEY["leave.record"].title in content
    assert ENTRY_BY_KEY["leave.balances"].title in content


def test_save_warns_about_name(client: Client) -> None:
    _staff(client, "Admin")
    _employee("Номин")
    response = client.post(ADD, _post_data(question="Номин өнөөдөр өвдөөд ирээгүй"), follow=True)
    assert "Нэр байж магадгүй" in response.content.decode()
    assert HelpExample.objects.filter(question="Номин өнөөдөр өвдөөд ирээгүй").exists()


def test_deactivate_counts_switched(client: Client) -> None:
    _staff(client, "Admin")
    on = HelpExample.objects.create(question=QUESTION, entry=KEY, active=True)
    off = HelpExample.objects.create(question="өөр асуулт", entry=KEY, active=False)
    response = client.post(
        CHANGELIST,
        {"action": "deactivate", "_selected_action": [on.pk, off.pk], "index": 0},
        follow=True,
    )
    assert "1 идэвхгүй болголоо" in response.content.decode()
    on.refresh_from_db()
    assert on.active is False
