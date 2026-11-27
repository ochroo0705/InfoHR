"""Repair sheet request checks and the mapping of database refusals. No database: the vehicle lookup is replaced."""

from typing import Any

import pytest
from django.db import DatabaseError
from pytest import MonkeyPatch

from autoservice import repairs
from autoservice.quotes import QuoteError
from autoservice.registry import DIRECTORIES


@pytest.fixture
def car(monkeypatch: MonkeyPatch) -> dict[str, Any]:
    row = {
        "id": 4045,
        "car_id": 50,
        "plate": "5240УАЕ",
        "body_no": "",
        "engine_type": "2ZRFXE",
        "vin": "V",
        "color": "",
        "engine_no": "",
        "certificate": "",
        "driver_no": "",
        "maked": None,
        "spec": "",
        "year": 2012,
        "owner": "Бат",
        "phone": "99226269",
    }
    monkeypatch.setattr(repairs, "vehicle", lambda vehicle_id: row if vehicle_id == 4045 else None)
    return row


def _body(**kw: Any) -> dict[str, Any]:
    return {"vehicle_id": 4045, "works": [{"ref": 432, "mech_id": 4905, "qty": 1, "price": 85000}]} | kw


def test_parse_defaults_and_mechanic(car: dict[str, Any]) -> None:
    data = repairs.parse(_body())
    assert (data["customer"], data["phone"], data["vat_on"], data["internal"]) == ("Бат", "99226269", True, False)
    assert data["works"][0]["mech_id"] == 4905 and data["works"][0]["disc"] == 0
    assert data["garage"] == 0 and data["expense_acct"] == "" and data["card_no"] == ""


def test_parse_a_work_without_a_mechanic_is_allowed_until_it_is_finished(car: dict[str, Any]) -> None:
    data = repairs.parse(_body(works=[{"ref": 432, "qty": 1, "price": 1}]))
    assert data["works"][0]["mech_id"] is None


def test_parse_internal_expense_keeps_the_account_only_when_internal(car: dict[str, Any]) -> None:
    assert repairs.parse(_body(internal=True, expense_acct="7003-003"))["expense_acct"] == "7003-003"
    assert repairs.parse(_body(internal=False, expense_acct="7003-003"))["expense_acct"] == ""


def test_parse_garage_only_when_switched_on(car: dict[str, Any]) -> None:
    assert repairs.parse(_body(garage_on=True, garage=15000))["garage"] == 15000
    assert repairs.parse(_body(garage_on=False, garage=15000))["garage"] == 0


@pytest.mark.parametrize(
    "change, text",
    [
        ({"vehicle_id": 0}, "Автомашин сонгоно уу"),
        ({"vehicle_id": 7}, "Автомашин олдсонгүй"),
        ({"works": [], "parts": []}, "Ажил эсвэл сэлбэгийн мөр"),
        ({"works": [{"ref": 1, "qty": 1, "price": 1, "mech_id": "abc"}]}, "Засварчин"),
        ({"parts": [{"qty": 1, "price": 1}]}, "бүртгэлтэй бараа"),
        ({"garage_on": True, "garage": -5}, "Гарааж"),
        ({"date_in": "yesterday"}, "Огноо"),
        ({"customer_id": "x"}, "Харилцагч"),
    ],
)
def test_parse_refuses_bad_requests(car: dict[str, Any], change: dict[str, Any], text: str) -> None:
    with pytest.raises(QuoteError) as e:
        repairs.parse(_body(**change))
    assert text in str(e.value)


def test_database_exceptions_become_messages_and_locked_ones_are_conflicts() -> None:
    finish = repairs.db_error(DatabaseError("exception 12 EMPJOB_NOT_EQUAL at procedure FINISH_SERVCARDS"))
    assert isinstance(finish, repairs.RepairLocked) and "засварчин" in str(finish)
    assert "Төлбөр" in str(repairs.db_error(DatabaseError("exception PAYMENT_NOT_EQUAL")))
    unknown = repairs.db_error(DatabaseError("something else broke"))
    assert not isinstance(unknown, repairs.RepairLocked)


def test_header_row_becomes_the_screens_fields() -> None:
    known = {
        "status": 2,
        "vat_percent": 10.0,
        "warranty": "yes",
        "settle_later": "no",
        "internal": "yes",
        "garage_day": 1,
        "garage_price": 5000.0,
        "doc_no": "225217  ",
        "id": 19315,
    }
    h = repairs._header(tuple(known.get(key) for key, _ in repairs.HEADER_COLUMNS))
    assert (h["finished"], h["started"], h["vat_on"], h["warranty"]) == (True, True, True, True)
    assert (h["settle_later"], h["internal"]) == (False, True)
    assert (h["garage_on"], h["garage"], h["no"], h["doc_no"]) == (True, 5000.0, 225217, "225217")


def test_the_mechanic_directory_is_limited_to_customers_flagged_as_employees() -> None:
    d = DIRECTORIES["mechanics"]
    assert d.table == "CUSTOMER" and d.where == "EMPLOYEE = 'yes'"
