"""Token, password and route tests that need no database: the two functions that read MACS are replaced."""

import json
import time
from typing import Any

import pytest
from django.test import Client
from pytest import MonkeyPatch

from autoservice import passwords, tokens, views
from autoservice.registry import DIRECTORIES

LOGIN = "/api/autoservice/login"


def test_password_matches_trimmed_and_exact() -> None:
    assert passwords.matches("123  ", "123")
    assert not passwords.matches("123", "124")
    assert not passwords.matches("", "")
    assert not passwords.matches(None, "1")
    assert not passwords.matches("123", "")


def test_token_roundtrip_and_tamper() -> None:
    token, expires_at = tokens.issue("dashnyam", "gic")
    user = tokens.read(token)
    assert user is not None
    assert (user.username, user.rights, user.expires_at) == ("dashnyam", "gic", expires_at)
    assert tokens.read(token[:-2] + "xx") is None
    assert tokens.read("") is None


def test_token_expires(monkeypatch: MonkeyPatch) -> None:
    token, _ = tokens.issue("u", "")
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + tokens.ttl() + 5)
    assert tokens.read(token) is None


@pytest.fixture
def fake_login(monkeypatch: MonkeyPatch) -> None:
    rows = {"DASHNYAM": ("dashnyam", "123", "gicrpasall", 7, "")}
    monkeypatch.setattr(views, "_find_login", lambda name: rows.get(name.upper()))


def _post(c: Client, body: dict[str, Any]) -> Any:
    return c.post(LOGIN, data=json.dumps(body), content_type="application/json")


def test_login_ok_returns_token_and_user(fake_login: None) -> None:
    r = _post(Client(), {"username": "DashNyam", "password": "123"})
    assert r.status_code == 200
    data = r.json()
    assert data["tokenType"] == "Bearer" and data["user"] == {
        "username": "dashnyam",
        "rights": "gicrpasall",
        "email": "",
        "branch_id": 7,
    }
    assert tokens.read(data["accessToken"]) is not None


def test_login_wrong_and_unknown_look_the_same(fake_login: None) -> None:
    wrong = _post(Client(), {"username": "dashnyam", "password": "999"})
    unknown = _post(Client(), {"username": "nobody", "password": "123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_needs_both_fields_and_post(fake_login: None) -> None:
    assert _post(Client(), {"username": "dashnyam"}).status_code == 400
    assert Client().get(LOGIN).status_code == 405
    assert Client().post(LOGIN, data="not json", content_type="application/json").status_code == 400


def test_login_locks_after_repeated_failures(fake_login: None) -> None:
    c = Client()
    codes = [_post(c, {"username": "dashnyam", "password": f"bad{i}"}).status_code for i in range(7)]
    assert codes == [401] * 5 + [429] * 2
    assert _post(c, {"username": "dashnyam", "password": "123"}).status_code == 429  # even the right one


def test_directories_need_a_token() -> None:
    r = Client().get("/api/autoservice/dirs/works")
    assert r.status_code == 401 and r["WWW-Authenticate"] == "Bearer"
    assert Client().get("/api/autoservice/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_directory_listing_paging_and_search(monkeypatch: MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_select(d: Any, where: str, params: list[Any], limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        seen.update(table=d.table, where=where, params=params, limit=limit, offset=offset)
        return [{"id": 1, "name": "a"}], 1

    monkeypatch.setattr(views, "_select", fake_select)
    token, _ = tokens.issue("u", "")
    auth = {"Authorization": f"Bearer {token}"}
    r = Client().get("/api/autoservice/dirs/works?q=нас&limit=9999&offset=-4", headers=auth)
    assert r.status_code == 200 and r.json()["results"] == [{"id": 1, "name": "a"}]
    assert (seen["table"], seen["limit"], seen["offset"]) == ("WORKS", 500, 0)  # limit capped, offset floored
    assert seen["where"].count("LIKE") == 3 and seen["params"] == ["%нас%"] * 3
    assert Client().get("/api/autoservice/dirs/nope", headers=auth).status_code == 404
    assert Client().get("/api/autoservice/dirs", headers=auth).json()["directories"] == sorted(DIRECTORIES)


def test_users_directory_never_exposes_passwords() -> None:
    cols = set(DIRECTORIES["users"].columns.values())
    assert cols.isdisjoint({"PASSW", "FPASS"})


def test_clean_values() -> None:
    from datetime import date, datetime
    from decimal import Decimal

    assert views.clean("abc   ") == "abc"
    assert views.clean(Decimal("1.5")) == 1.5
    assert views.clean(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05"
    assert views.clean(date(2026, 1, 2)) == "2026-01-02"
    assert views.clean(b"\x00") is None
    assert views.clean(None) is None
