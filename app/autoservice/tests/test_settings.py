"""The settings routes and the password that opens the Advanced tab. No database: what reads MACS is replaced."""

import json
import time
from typing import Any

import pytest
from django.test import Client
from pytest import MonkeyPatch

from autoservice import program_settings, tokens, views_settings

UNLOCK = "/api/autoservice/settings/advanced/unlock"
ADVANCED = "/api/autoservice/settings/advanced"
SECRET = {"advanced": ["a"]}


@pytest.fixture
def api(monkeypatch: MonkeyPatch) -> dict[str, Any]:
    logins = {"DASH": ("dash", "123", "r", None, ""), "UUGAN": ("uugan", "777", "r", None, "")}
    monkeypatch.setattr(views_settings, "_find_login", lambda name: logins.get(name.upper()))
    monkeypatch.setattr(program_settings, "advanced", lambda: SECRET)
    monkeypatch.setattr(program_settings, "main", lambda: {"company": {"name": "X"}})
    return {
        "dash": {"Authorization": f"Bearer {tokens.issue('dash', 'r')[0]}"},
        "uugan": {"Authorization": f"Bearer {tokens.issue('uugan', 'r')[0]}"},
    }


def _unlock(headers: dict[str, str], password: str) -> Any:
    return Client().post(
        UNLOCK, data=json.dumps({"password": password}), content_type="application/json", headers=headers
    )


def test_the_advanced_key_belongs_to_one_user_and_expires(monkeypatch: MonkeyPatch) -> None:
    key, _ = tokens.issue_advanced("dash")
    assert tokens.read_advanced(key, "dash")
    assert not tokens.read_advanced(key, "uugan")
    assert not tokens.read_advanced(key[:-2] + "xx", "dash")
    assert not tokens.read_advanced("", "dash")
    assert not tokens.read(key)  # not a bearer token either: the salts differ
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + tokens.advanced_ttl() + 5)
    assert not tokens.read_advanced(key, "dash")


def test_settings_need_a_token(api: dict[str, Any]) -> None:
    assert Client().get("/api/autoservice/settings").status_code == 401
    r = Client().get("/api/autoservice/settings", headers=api["dash"])
    assert r.status_code == 200 and r.json() == {"company": {"name": "X"}}


def test_advanced_is_locked_until_the_password_is_typed(api: dict[str, Any]) -> None:
    c = Client()
    assert c.get(ADVANCED, headers=api["dash"]).status_code == 403
    assert c.get(ADVANCED, headers={**api["dash"], "X-Advanced-Token": "junk"}).status_code == 403
    assert c.get(ADVANCED).status_code == 401  # no bearer token at all
    r = _unlock(api["dash"], "123")
    assert r.status_code == 200
    key = r.json()["advancedToken"]
    opened = c.get(ADVANCED, headers={**api["dash"], "X-Advanced-Token": key})
    assert opened.status_code == 200 and opened.json() == SECRET


def test_a_key_does_not_open_advanced_for_someone_else(api: dict[str, Any]) -> None:
    key = _unlock(api["dash"], "123").json()["advancedToken"]
    assert Client().get(ADVANCED, headers={**api["uugan"], "X-Advanced-Token": key}).status_code == 403


def test_wrong_empty_password(api: dict[str, Any]) -> None:
    # 403 on purpose: a 401 would tell the web app its session ended and sign the user out.
    assert _unlock(api["dash"], "999").status_code == 403
    assert _unlock(api["dash"], "").status_code == 400
    assert _unlock(api["dash"], "777").status_code == 403  # somebody else's password is still wrong for dash


def test_guessing_is_throttled_even_for_the_right_password(api: dict[str, Any]) -> None:
    codes = [_unlock(api["dash"], f"bad{i}").status_code for i in range(7)]
    assert codes == [403] * 5 + [429] * 2
    assert _unlock(api["dash"], "123").status_code == 429


def test_option_values() -> None:
    assert [program_settings._flag(v) for v in ("True", "true", "1", "yes", "False", "", None)] == [
        True,
        True,
        True,
        True,
        False,
        False,
        False,
    ]
