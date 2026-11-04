"""The system-log query layer: parsing of the address, each filter in SQL, deleted actors, batches and query count."""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from accounts.audit import Category
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from django.db import connection
from django.http import QueryDict

from logs.system_query import SystemLogFilter, filtered, parse_system_filter, system_page

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
UB = ZoneInfo("Asia/Ulaanbaatar")


def _user(name: str, role: str | None, *, first: str = "", last: str = "") -> User:
    user = User.objects.create_user(name, password=PASSWORD, first_name=first, last_name=last)  # noqa: S106
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _row(message: str, **fields: Any) -> SystemLogEntry:
    """One log row. The actor's username is stored in actor_name, as accounts.audit.record() does."""
    actor = fields.get("actor")
    fields.setdefault("actor_name", actor.username if actor is not None else "")
    fields.setdefault("category", Category.ACCESS)
    fields.setdefault("action", "login")
    fields.setdefault("changes", [])
    return SystemLogEntry.objects.create(message=message, **fields)


def _set_at(entry: SystemLogEntry, when: datetime) -> None:
    # The log is append-only in the ORM (AppendOnlyLogQuerySet.update raises), so the test moves the timestamp in SQL.
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{SystemLogEntry._meta.db_table}" SET "at_time" = %s WHERE id = %s',  # noqa: S608
            [when, entry.pk],
        )


def _messages(f: SystemLogFilter) -> list[str]:
    return [entry.message for entry in filtered(f)]


@pytest.fixture
def actor(db: None) -> User:
    return _user("sys_actor", "HR", first="Сараа", last="Батын")


@pytest.fixture
def admin(db: None) -> User:
    return _user("sys_admin", "Admin", first="Болд", last="Админ")


@pytest.fixture
def world(admin: User, actor: User) -> dict[str, SystemLogEntry]:
    rows = {
        "login": _row("Нэвтэрсэн", actor=actor, ip="10.0.0.5"),
        "setting": _row(
            "Тохиргоо нэмсэн",
            category=Category.SETTINGS,
            action="setting_added",
            actor=admin,
            target_type="Тохиргоо",
            target_label="Ажлын цаг",
            ip="10.0.1.7",
        ),
        "failed": _row(
            "Нэвтрэх оролдлого амжилтгүй",
            action="login_failed",
            actor_name="wrong.user",
            ip="192.168.1.1",
        ),
        "import": _row(
            "Хаяг өөрчлөгдсөн",
            category=Category.IMPORT,
            action="macs_sync",
            target_type="Ажилтан",
            target_label="Батын Сараа",
            changes=[{"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"}],
            ip="2001:db8::1",
        ),
    }
    return rows


def test_parse_drops_bad_values_and_never_raises() -> None:
    params = QueryDict(
        "category=%00&category=access&category=nope&action=drop-table&ip=%00&from=zzz&to=2026-02-30"
        "&by=" + "9" * 300 + "&q=%00%00&oldest=1&offset=abc"
    )
    f = parse_system_filter(params)
    assert f.categories == ["access"]
    assert f.action == ""
    assert f.ip == ""
    assert f.date_from is None and f.date_to is None
    assert len(f.by) == 300
    assert f.q == ""
    assert f.oldest_first is True


def test_parse_keeps_known_action_and_ip_prefix() -> None:
    f = parse_system_filter(QueryDict("action=login_failed&ip=10.0.1&target=%20Ажилтан%20"))
    assert f.action == "login_failed"
    assert f.ip == "10.0.1"
    assert f.target == "Ажилтан"


def test_ip_with_letters_outside_hex_is_dropped() -> None:
    assert parse_system_filter(QueryDict("ip=10.0.0.5%25")).ip == ""  # a percent sign
    assert parse_system_filter(QueryDict("ip=" + "1" * 46)).ip == ""  # too long


def test_category_filter(world: dict[str, SystemLogEntry]) -> None:
    assert _messages(SystemLogFilter(categories=[Category.SETTINGS])) == ["Тохиргоо нэмсэн"]
    # Creating users also writes access rows through the audit signals, so only membership is checked.
    got = set(_messages(SystemLogFilter(categories=[Category.ACCESS, Category.IMPORT])))
    assert {"Нэвтэрсэн", "Нэвтрэх оролдлого амжилтгүй", "Хаяг өөрчлөгдсөн"} <= got
    assert "Тохиргоо нэмсэн" not in got


def test_action_filter(world: dict[str, SystemLogEntry]) -> None:
    assert _messages(SystemLogFilter(action="login_failed")) == ["Нэвтрэх оролдлого амжилтгүй"]


def test_who_matches_actor_name_username_and_person_name(world: dict[str, SystemLogEntry]) -> None:
    assert _messages(SystemLogFilter(by="wrong.user")) == ["Нэвтрэх оролдлого амжилтгүй"]  # stored name only
    assert _messages(SystemLogFilter(by="sys_actor")) == ["Нэвтэрсэн"]  # username
    assert _messages(SystemLogFilter(by="Батын")) == ["Нэвтэрсэн"]  # last name
    assert _messages(SystemLogFilter(by="Болд Админ")) == ["Тохиргоо нэмсэн"]  # every word must match


def test_target_matches_label_and_type(world: dict[str, SystemLogEntry]) -> None:
    assert _messages(SystemLogFilter(target="Ажлын цаг")) == ["Тохиргоо нэмсэн"]
    assert set(_messages(SystemLogFilter(target="Ажилтан"))) == {"Хаяг өөрчлөгдсөн"}
    assert _messages(SystemLogFilter(target="Тохиргоо")) == ["Тохиргоо нэмсэн"]  # the type word


def test_ip_prefix_and_exact(world: dict[str, SystemLogEntry]) -> None:
    assert set(_messages(SystemLogFilter(ip="10.0"))) == {"Нэвтэрсэн", "Тохиргоо нэмсэн"}
    assert _messages(SystemLogFilter(ip="10.0.1.7")) == ["Тохиргоо нэмсэн"]
    assert _messages(SystemLogFilter(ip="2001:db8")) == ["Хаяг өөрчлөгдсөн"]
    assert _messages(SystemLogFilter(ip="172.16")) == []


def test_full_ip_is_exact_not_a_prefix(world: dict[str, SystemLogEntry]) -> None:
    _row("Гарал A", ip="10.0.0.5")
    _row("Гарал B", ip="10.0.0.50")
    got = set(_messages(SystemLogFilter(ip="10.0.0.5")))
    assert "Гарал A" in got and "Гарал B" not in got


def test_date_range_is_whole_local_days(world: dict[str, SystemLogEntry]) -> None:
    before = _row("өмнөх өдөр")
    first = _row("эхний өдөр")
    last = _row("сүүлийн өдөр")
    after = _row("маргаашийн өдөр")
    _set_at(before, datetime(2026, 3, 9, 23, 59, tzinfo=UB))
    _set_at(first, datetime(2026, 3, 10, 0, 0, tzinfo=UB))
    _set_at(last, datetime(2026, 3, 10, 23, 59, tzinfo=UB))
    _set_at(after, datetime(2026, 3, 11, 0, 0, tzinfo=UB))
    day = date(2026, 3, 10)
    got = set(filtered(SystemLogFilter(date_from=day, date_to=day)).values_list("message", flat=True))
    assert got == {"эхний өдөр", "сүүлийн өдөр"}


def test_search_matches_message_and_change_values(world: dict[str, SystemLogEntry]) -> None:
    assert _messages(SystemLogFilter(q="Хаяг өөрчлөгдсөн")) == ["Хаяг өөрчлөгдсөн"]
    assert _messages(SystemLogFilter(q="Баянзүрх")) == ["Хаяг өөрчлөгдсөн"]  # a new value in changes
    assert _messages(SystemLogFilter(q="Сүхбаатар")) == ["Хаяг өөрчлөгдсөн"]  # an old value in changes


@pytest.mark.parametrize("word", ["old", "new", "field", '"'])
def test_search_never_matches_json_key_names(world: dict[str, SystemLogEntry], word: str) -> None:
    assert _messages(SystemLogFilter(q=word)) == []


def test_oldest_first_reverses_the_order(world: dict[str, SystemLogEntry]) -> None:
    newest = _messages(SystemLogFilter())
    assert _messages(SystemLogFilter(oldest_first=True)) == list(reversed(newest))
    assert newest[0] == "Хаяг өөрчлөгдсөн"  # the last row written is first by default


def test_deleted_actor_keeps_the_name(world: dict[str, SystemLogEntry]) -> None:
    gone = _user("gone_actor", "HR", first="Өнөр", last="Одоо")
    row = _row("Устсан хэрэглэгчийн бичлэг", actor=gone)
    gone.delete()
    row.refresh_from_db()
    assert row.actor is None
    assert row.actor_name == "gone_actor"
    rows, _more = system_page(SystemLogFilter(q="Устсан"), 0, 60)
    assert [r.actor_name for r in rows] == ["gone_actor"]


def test_empty_actor_name_is_kept_empty(world: dict[str, SystemLogEntry]) -> None:
    rows, _more = system_page(SystemLogFilter(by="Систем"), 0, 60)  # no such name typed in any row
    assert rows == []
    system_row = _row("Системийн үйлдэл")
    rows, _more = system_page(SystemLogFilter(q="Системийн үйлдэл"), 0, 60)
    assert [r.actor_name for r in rows] == [""] and rows[0].pk == system_row.pk


def test_page_has_more_flag(world: dict[str, SystemLogEntry]) -> None:
    rows, more = system_page(SystemLogFilter(), 0, 2)
    assert len(rows) == 2 and more is True
    total = filtered(SystemLogFilter()).count()
    rows, more = system_page(SystemLogFilter(), total - 1, 2)
    assert len(rows) == 1 and more is False


def test_page_clamps_huge_offset_and_size(world: dict[str, SystemLogEntry]) -> None:
    assert system_page(SystemLogFilter(), 10**30, 60) == ([], False)
    rows, more = system_page(SystemLogFilter(), 0, 10**30)
    assert len(rows) <= 500 and more is False


def test_query_count_flat_at_20000_rows(world: dict[str, SystemLogEntry], django_assert_max_num_queries: Any) -> None:
    SystemLogEntry.objects.bulk_create(
        [SystemLogEntry(category=Category.EXPORT, action="export_list", message=f"жишээ {i}") for i in range(20000)],
        batch_size=5000,
    )
    with django_assert_max_num_queries(6):
        rows, more = system_page(SystemLogFilter(q="жишээ"), 0, 60)
    assert len(rows) == 60 and more is True
