"""Structured old and new values in the activity log for the personal list rows (audit-logs task 12)."""

import re
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from macs.models import FamilyRelation, LanguageLevel

from employees.models import ActivityEntry, ActivityKind, Employee
from employees.services import personal_writes as pw
from employees.services import records

from .test_personal_views import add_url, delete_post, delete_url, edit_post, edit_url, lists, only_key, values_for
from .test_views import login_as

__all__ = ["lists"]  # the fixture, imported for these tests
pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 29)


def _latest(employee: Employee) -> ActivityEntry:
    return ActivityEntry.objects.filter(employee=employee).latest("id")


def _list_name(pk: int) -> str:
    """The stored name of a code-list row. MACS's trigger on Firebird writes list names in upper case, so the
    expected text is read back from the row rather than written as typed."""
    return str(FamilyRelation.objects.get(pk=pk).name)


def _mentions(sql: str, table: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(connection.ops.quote_name(table))}(?!\w)", sql) is not None


def _header(entry: ActivityEntry) -> str:
    return render_to_string("employees/_activity_latest.html", {"latest_activity": entry, "today": TODAY})


@pytest.mark.parametrize("kind", ["family", "talent", "material_help", "training"])
def test_unchanged_save_writes_no_entry_for_each_value_type(
    client: Client, hired: Employee, lists: dict[str, Any], kind: str
) -> None:
    """Int, money (Decimal) and date columns must round-trip, or an unchanged save would log a spurious change."""
    login_as(client, "HR")
    client.post(add_url(hired, kind), values_for(kind, lists))
    key = only_key(hired, kind)
    before = ActivityEntry.objects.filter(employee=hired).count()
    assert client.post(edit_url(hired, kind, key), edit_post(client, hired, kind, key)).status_code == 204
    assert ActivityEntry.objects.filter(employee=hired).count() == before


def test_header_shows_the_message_for_personal_list_writes(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "family"), values_for("family", lists))
    added = _latest(hired)
    assert added.header_change is None and "Гэр бүл: нэмсэн — Дорж" in _header(added)
    key = only_key(hired, "family")
    post = edit_post(client, hired, "family", key)
    post["given_name"] = "Болд"
    client.post(edit_url(hired, "family", key), post)
    edited = _latest(hired)
    assert edited.header_change is None and "Гэр бүл: засварласан — Болд" in _header(edited)
    client.post(delete_url(hired, "family", key), delete_post(client, hired, "family", key))
    deleted = _latest(hired)
    assert deleted.header_change is None and "Гэр бүл: устгасан — Болд" in _header(deleted)


def test_header_keeps_the_first_change_for_field_and_salary_edits(hired: Employee, actor: User) -> None:
    records.update_employee(hired, {"clan_name": "Хонгор"}, actor)
    field_entry = _latest(hired)
    assert field_entry.header_change == field_entry.changes[0]
    assert f"{field_entry.changes[0]['field']}: " in _header(field_entry)

    records.update_salary_insurance(hired, {"social_insurance_no": "НД-1234"}, actor)
    salary_entry = _latest(hired)
    assert salary_entry.header_change == salary_entry.changes[0]
    assert f"{salary_entry.changes[0]['field']}: " in _header(salary_entry)


def test_changed_list_name_costs_one_query_per_list(hired: Employee, lists: dict[str, Any], actor: User) -> None:
    """Old and new names of a changed code-list value come from one IN query; an unchanged one costs none."""
    key = pw.add(
        "family",
        hired,
        {"relation_id": lists["relation"].pk, "given_name": "Болд", "surname": None, "birth_date": None},
        {},
        actor,
    )
    other = FamilyRelation.objects.create(name="Ээж", fm_type="mother").pk
    loaded = pw.load("family", hired, key)
    assert loaded is not None
    with CaptureQueriesContext(connection) as changed:
        pw.update("family", hired, key, loaded, {"relation_id": other}, {}, actor)
    assert _latest(hired).changes == [
        {"field": "Хамаарал", "old": _list_name(lists["relation"].pk), "new": _list_name(other)}
    ]
    loaded = pw.load("family", hired, key)
    assert loaded is not None
    with CaptureQueriesContext(connection) as unchanged:
        pw.update("family", hired, key, loaded, {"given_name": "Дорж"}, {}, actor)
    list_queries = [q for q in changed.captured_queries if _mentions(q["sql"], "family_members")]
    assert len(list_queries) == 1
    assert not [q for q in unchanged.captured_queries if _mentions(q["sql"], "family_members")]
    assert len(changed.captured_queries) - len(unchanged.captured_queries) <= 1


def test_family_add_logs_the_entered_name_as_new(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "family"), values_for("family", lists)).status_code == 204
    entry = _latest(hired)
    assert entry.message == "Гэр бүл: нэмсэн — Дорж"
    assert entry.kind == ActivityKind.ADDED and entry.personal is True
    assert {"field": "Нэр", "old": "", "new": "Дорж"} in entry.changes
    assert {"field": "Хамаарал", "old": "", "new": _list_name(lists["relation"].pk)} in entry.changes  # name, not id


def test_talent_add_logs_the_talent_name(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "talent"), values_for("talent", lists)).status_code == 204
    assert {"field": "Авьяас", "old": "", "new": "Хөгжим"} in _latest(hired).changes


def test_language_level_edit_logs_one_change_with_names(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    LanguageLevel.objects.create(name="Сайн")
    client.post(add_url(hired, "language"), values_for("language", lists))
    key = only_key(hired, "language")
    post = edit_post(client, hired, "language", key)
    post["understand_lvl"] = "Сайн"
    assert client.post(edit_url(hired, "language", key), post).status_code == 204
    entry = _latest(hired)
    assert entry.message == "Гадаад хэл: засварласан — Англи"
    assert entry.kind == ActivityKind.CHANGED and entry.personal is True
    assert entry.changes == [{"field": "Ойлгох түвшин", "old": "Дунд", "new": "Сайн"}]


def test_delete_logs_every_change_as_removed(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "family"), values_for("family", lists))
    key = only_key(hired, "family")
    assert client.post(delete_url(hired, "family", key), delete_post(client, hired, "family", key)).status_code == 204
    entry = _latest(hired)
    assert entry.message == "Гэр бүл: устгасан — Дорж"
    assert entry.kind == ActivityKind.DELETED and entry.personal is True
    assert entry.changes and all(change["new"] == "" for change in entry.changes)
    assert {"field": "Нэр", "old": "Дорж", "new": ""} in entry.changes


def test_unchanged_save_adds_no_entry(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "family"), values_for("family", lists))
    key = only_key(hired, "family")
    before = ActivityEntry.objects.filter(employee=hired).count()
    assert client.post(edit_url(hired, "family", key), edit_post(client, hired, "family", key)).status_code == 204
    assert ActivityEntry.objects.filter(employee=hired).count() == before


def test_drawer_renders_old_struck_and_new_for_a_list_edit(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    login_as(client, "HR")
    LanguageLevel.objects.create(name="Сайн")
    client.post(add_url(hired, "language"), values_for("language", lists))
    key = only_key(hired, "language")
    post = edit_post(client, hired, "language", key)
    post["understand_lvl"] = "Сайн"
    client.post(edit_url(hired, "language", key), post)
    body = client.get(reverse("employees:detail", args=[hired.pk])).content.decode()
    assert '<s class="text-slate-400">Дунд</s> → Сайн' in body
    assert "Гадаад хэл: засварласан — Англи" in body
