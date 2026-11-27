"""Vehicle owners and the HUR plate lookup. No database, no network: HUR's answers are replaced."""

import json
from typing import Any

import pytest
from django.test import Client
from django.test.utils import override_settings
from pytest import MonkeyPatch

from autoservice import hur, tokens, vehicles, views_vehicles

BASE: dict[str, Any] = {"plate": " 8366убг ", "mark_id": 49, "phone": "99101298"}

HUR_ANSWER = {
    "return": {
        "resultCode": 0,
        "response": {
            "plateNumber": "8366УБГ",
            "markName": "TOYOTA",
            "modelName": "Prius 30",
            "buildYear": "2012",
            "cabinNumber": "ZVW305452132",
            "colorName": "Мөнгөлөг",
            "purpose": "Суудал",
            "ownerFirstname": "Бат",
            "ownerLastname": "Дорж",
            "ownerHandphone": "99101298",
            "ownerRegnum": "УБ77010101",
            "ownerAddress": {"state": "Улаанбаатар", "soum": "Баянзүрх"},
            "fueltype": "NO ACCESS",
        },
    }
}


def test_parse_normalises_the_plate_and_checks_required_fields() -> None:
    d = vehicles.parse({**BASE, "year": "2012", "org_id": ""})
    assert d["plate"] == "8366УБГ" and d["year"] == 2012 and d["org_id"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"plate": " "},
        {"mark_id": 0},
        {"mark_id": "x"},
        {"year": 1800},
        {"plate": "x" * 33},
        {"owner": "x" * 321},
    ],
)
def test_parse_refuses_bad_input(patch: dict[str, Any]) -> None:
    with pytest.raises(vehicles.VehicleError):
        vehicles.parse({**BASE, **patch})


def test_hur_answer_is_parsed_and_hidden_fields_are_dropped() -> None:
    v = hur.parse(HUR_ANSWER, "8366УБГ")
    assert (v["make"], v["model"], v["year"], v["vin"]) == ("TOYOTA", "Prius 30", 2012, "ZVW305452132")
    assert v["fuel_type"] is None  # "NO ACCESS" is not data
    assert v["owner"] == {
        "first_name": "Бат",
        "last_name": "Дорж",
        "phone": "99101298",
        "register": "УБ77010101",
        "type": None,
        "address": "Улаанбаатар, Баянзүрх",
    }


def test_hur_error_code_is_a_404_with_the_fixed_text() -> None:
    raw = {"return": {"resultCode": 5, "resultMessage": "Бүртгэл төв -с олдсонгүй"}}
    with pytest.raises(hur.HurError) as e:
        hur.parse(raw, "1")
    assert e.value.status == 404 and "төвөөс" in str(e.value)


def test_hur_without_settings_is_off() -> None:
    with override_settings(HUR_USERNAME="", HUR_PASSWORD="", HUR_CODE=""), pytest.raises(hur.HurError) as e:
        hur.vehicle("1234УБА")
    assert e.value.status == 503


@override_settings(HUR_USERNAME="u", HUR_PASSWORD="p", HUR_CODE="c")  # noqa: S106 - a test value, not a secret
def test_hur_renews_the_token_once_on_401(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    logins = iter(["old", "new"])

    def fake_post(path: str, payload: dict[str, Any], token: str = "") -> Any:  # noqa: S107 - no secret here
        calls.append((path, token))
        if path == "login":
            return {"token": next(logins), "expiresIn": 3600}
        if token == "old":  # noqa: S105 - a test value, not a secret
            raise hur.HurError("ХУР getVehicleInfo алдаа: 401")
        assert payload == {"code": "c", "number": "8366УБГ"}
        return HUR_ANSWER

    monkeypatch.setattr(hur, "_post", fake_post)
    monkeypatch.setattr(hur, "_token", None)
    assert hur.vehicle(" 8366убг ")["model"] == "Prius 30"
    assert calls == [("login", ""), ("getVehicleInfo", "old"), ("login", ""), ("getVehicleInfo", "new")]


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens.issue('dash', 'r')[0]}"}


def test_routes_need_a_token() -> None:
    for url in ("vehicles", "vehicles/1", "vehicles/hur?plate=1"):
        assert Client().get(f"/api/autoservice/{url}").status_code == 401


def test_hur_route_matches_our_lists_and_limits_calls(monkeypatch: MonkeyPatch, headers: dict[str, str]) -> None:
    monkeypatch.setattr(hur, "vehicle", lambda plate: hur.parse(HUR_ANSWER, plate))
    monkeypatch.setattr(vehicles, "match_hur", lambda info: {"mark": {"id": 49, "name": "Prius 30"}, "org": None})
    monkeypatch.setattr(vehicles, "find_by_plate", lambda plate: 4112)
    monkeypatch.setattr(views_vehicles, "_hur_calls", {"dash": []})
    r = Client().get("/api/autoservice/vehicles/hur?plate=8366УБГ", headers=headers)
    body = json.loads(r.content)
    assert r.status_code == 200 and body["mark"]["id"] == 49 and body["registered_id"] == 4112
    assert body["owner"]["phone"] == "99101298"
    assert Client().get("/api/autoservice/vehicles/hur", headers=headers).status_code == 400
    for _ in range(views_vehicles.HUR_PER_MINUTE):
        Client().get("/api/autoservice/vehicles/hur?plate=8366УБГ", headers=headers)
    assert Client().get("/api/autoservice/vehicles/hur?plate=8366УБГ", headers=headers).status_code == 429


def test_hur_route_passes_the_registry_error(monkeypatch: MonkeyPatch, headers: dict[str, str]) -> None:
    def fail(plate: str) -> Any:
        raise hur.HurError("ХУР-тай холбогдож чадсангүй.", status=502)

    monkeypatch.setattr(hur, "vehicle", fail)
    monkeypatch.setattr(views_vehicles, "_hur_calls", {"dash": []})
    assert Client().get("/api/autoservice/vehicles/hur?plate=1", headers=headers).status_code == 502
