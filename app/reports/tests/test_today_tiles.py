"""The Today page's «Удахгүй болох» lines: the report setups that match now, one count each."""

import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from reports import today_tiles
from reports.models import SavedView
from reports.rules import Group, Rule, dump_rules
from reports.staff_list import REPORT as STAFF_REPORT
from reports.starter import rule_template
from reports.today_tiles import MAX_TILES, tiles, uses_next_days

from .conftest import legacy

pytestmark = pytest.mark.django_db

CONTRACT = "Гэрээ дуусах дөхсөн"
PROBATION = "Туршилтын хугацаа дуусах дөхсөн"
HEADING = "Удахгүй болох"


def _today_url() -> str:
    return reverse("employees:today")


def _views_url() -> str:
    return reverse("employees:today_views")


def _viewer_without_reports() -> User:
    """Sees the employees but may not open any report (no reports.view_reports)."""
    user = User.objects.create_user("no_reports_today", password="x-long-pass-123")  # noqa: S106
    user.user_permissions.add(Permission.objects.get(codename="view_employees"))
    return User.objects.get(pk=user.pk)


def _shared_view(name: str, query: str, author: User, visibility: str = "shared") -> SavedView:
    return SavedView.objects.create(
        report=STAFF_REPORT.key, name=name, query=query, author=author, visibility=visibility
    )


def _next_days(column: str = "contract_end", days: str = "30") -> str:
    return rule_template("tmp", Rule(column, "next_days", days)).query


def test_flat_next_days_rule_is_found() -> None:
    assert uses_next_days(dump_rules(Group("and", (Rule("contract_end", "next_days", "30"),))))


def test_next_days_two_levels_deep_is_found() -> None:
    inner = Group("and", (Rule("contract_end", "next_days", "30"),))
    assert uses_next_days(dump_rules(Group("and", (Rule("age", "gte", "55"), Group("or", (inner,))))))


def test_only_last_days_is_not_next_days() -> None:
    assert not uses_next_days(dump_rules(Group("and", (Rule("contract_end", "last_days", "30"),))))


@pytest.mark.parametrize("text", ["", "not json", "{}", '{"op": "and", "items": 5}'])
def test_empty_or_broken_text_is_not_next_days(text: str) -> None:
    assert not uses_next_days(text)


def test_hr_sees_the_contract_template_with_its_count(
    client: Client, login_hr: User, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    legacy(actor, job_values, contract_end=today + timedelta(days=10))
    legacy(actor, job_values, contract_end=today + timedelta(days=200))
    tile = next(t for t in tiles(login_hr) if t.name == CONTRACT)
    assert tile.count == 1
    assert tile.report == STAFF_REPORT.title
    response = client.get(tile.url)
    assert response.status_code == 200
    assert "Нийт: 1" in response.content.decode()


def test_shared_view_with_next_days_comes_after_the_templates(login_hr: User, actor: User) -> None:
    _shared_view("Дуусах гэрээ", _next_days(), author=actor)
    found = tiles(login_hr)
    assert [t.name for t in found] == [CONTRACT, PROBATION, "Дуусах гэрээ"]


def test_private_view_of_another_user_is_not_shown(login_hr: User) -> None:
    other = User.objects.create_user("other_author", password="x-long-pass-123")  # noqa: S106
    _shared_view("Хувийн", _next_days(), author=other, visibility="private")
    assert "Хувийн" not in [t.name for t in tiles(login_hr)]


def test_saved_view_without_next_days_is_not_shown(login_hr: User, actor: User) -> None:
    _shared_view("Нас", rule_template("tmp", Rule("age", "gte", "55")).query, author=actor)
    assert "Нас" not in [t.name for t in tiles(login_hr)]


def test_user_without_view_reports_gets_no_tiles() -> None:
    assert tiles(_viewer_without_reports()) == []


def test_fragment_is_empty_without_view_reports(client: Client) -> None:
    client.force_login(_viewer_without_reports())
    response = client.get(_views_url())
    assert response.status_code == 200
    assert response.content.decode().strip() == ""


def test_never_more_than_max_tiles(login_hr: User, actor: User) -> None:
    for i in range(MAX_TILES + 4):
        _shared_view(f"Харагдац {i:02d}", _next_days(days=str(30 + i)), author=actor)
    assert MAX_TILES == 8
    assert len(tiles(login_hr)) == MAX_TILES


def test_fragment_lists_the_tile_for_hr(
    client: Client, login_hr: User, actor: User, job_values: dict[str, Any]
) -> None:
    legacy(actor, job_values, contract_end=timezone.localdate() + timedelta(days=10))
    body = client.get(_views_url()).content.decode()
    assert HEADING in body
    assert CONTRACT in body


def test_fragment_is_empty_when_nothing_matches(
    client: Client, login_hr: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(today_tiles, "tiles", lambda user: [])
    response = client.get(_views_url())
    assert response.status_code == 200
    assert response.content.decode().strip() == ""


HIDDEN_RULE_VIEW = "Туслах хугацаа"  # next_days on birth_date, which the accountant may not see
VISIBLE_RULE_VIEW = "Гэрээний хугацаа"


def test_next_days_on_a_hidden_column_does_not_make_a_tile(login_hr: User, actor: User, accountant_user: User) -> None:
    hidden = dump_rules(Group("and", (Rule("birth_date", "next_days", "30"), Rule("contract_end", "filled", ""))))
    visible = dump_rules(Group("and", (Rule("contract_end", "next_days", "30"),)))
    _shared_view(HIDDEN_RULE_VIEW, urlencode({"rules": hidden}), actor)
    _shared_view(VISIBLE_RULE_VIEW, urlencode({"rules": visible}), actor)
    assert HIDDEN_RULE_VIEW in [t.name for t in tiles(login_hr)]  # the HR may see birth_date
    names = [t.name for t in tiles(accountant_user)]
    assert HIDDEN_RULE_VIEW not in names
    assert VISIBLE_RULE_VIEW in names


def test_tile_count_matches_the_page_for_every_tile(
    client: Client, login_hr: User, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    legacy(actor, job_values, contract_end=today + timedelta(days=10))
    legacy(actor, job_values, contract_end=today + timedelta(days=200))
    _shared_view(VISIBLE_RULE_VIEW, _next_days(), author=actor)
    found = {t.name: t for t in tiles(login_hr)}
    assert CONTRACT in found and VISIBLE_RULE_VIEW in found
    for tile in found.values():
        response = client.get(tile.url)
        assert response.status_code == 200
        match = re.search(r"Нийт: (\d+)", response.content.decode())
        assert match is not None, tile.name
        assert int(match.group(1)) == tile.count, tile.name


def test_tile_count_matches_the_page_when_a_hidden_rule_is_dropped(
    client: Client, actor: User, job_values: dict[str, Any], accountant_user: User
) -> None:
    today = timezone.localdate()
    legacy(actor, job_values, contract_end=today + timedelta(days=10))
    legacy(actor, job_values, contract_end=today + timedelta(days=200))
    both = dump_rules(Group("and", (Rule("contract_end", "next_days", "30"), Rule("birth_date", "filled", ""))))
    _shared_view(VISIBLE_RULE_VIEW, urlencode({"rules": both}), actor)
    tile = next(t for t in tiles(accountant_user) if t.name == VISIBLE_RULE_VIEW)
    client.force_login(accountant_user)
    response = client.get(tile.url)
    assert response.status_code == 200
    match = re.search(r"Нийт: (\d+)", response.content.decode())
    assert match is not None
    assert int(match.group(1)) == tile.count == 1


def test_hostile_saved_views_do_not_break_the_fragment(client: Client, login_hr: User, actor: User) -> None:
    contract_rule = dump_rules(Group("and", (Rule("contract_end", "next_days", "30"),)))
    queries = {
        "Бүтэцгүй 1": "rules=%%%",
        "Бүтэцгүй 2": "rules=[[[",
        "Урт": "rules=" + "x" * 3990,  # the longest a saved view can store (the column is 4000 characters)
        "Буруу огноо": "as_of=notadate&layout=zzz",
        "Буруу бүгд": urlencode(
            {"rules": contract_rule, "layout": "zzz", "as_of": "notadate", "sort": "--x", "lval": "zzz:??"}
        ),
        "Үл мэдэгдэх багана": urlencode({"rules": dump_rules(Group("and", (Rule("nope", "next_days", "30"),)))}),
    }
    for name, query in queries.items():
        _shared_view(name, query, author=actor)
    found = tiles(login_hr)
    assert isinstance(found, list)
    assert "Буруу бүгд" in [t.name for t in found]  # its valid rule survives, the bad parts are ignored
    response = client.get(_views_url())
    assert response.status_code == 200


def test_today_page_loads_the_fragment_for_hr(client: Client, login_hr: User) -> None:
    body = client.get(_today_url()).content.decode()
    assert f'hx-get="{_views_url()}"' in body


def test_today_page_has_no_fragment_load_without_view_reports(client: Client) -> None:
    client.force_login(_viewer_without_reports())
    body = client.get(_today_url()).content.decode()
    assert _views_url() not in body
