"""Quote pricing and request checks. No database: the one lookup that reads MACS is replaced."""

from typing import Any

import pytest
from pytest import MonkeyPatch

from autoservice import pricing, quotes


def _line(**kw: Any) -> dict[str, Any]:
    return {"qty": 1, "price": 85000, "disc": 5, "card": 0, "vat": True} | kw


def test_line_matches_an_existing_macs_row() -> None:
    """Row 150 of the Carservice database: 85 000 with 5 % discount and VAT 10 %."""
    db = pricing.line_to_db(_line(), vat_on=True)
    assert db["PRICE_NT"] == db["TOTAL_NT"] == db["BASEPRICE"] == 85000
    assert db["PRICE"] == pytest.approx(73409.09, abs=0.01)
    assert db["TOTAL"] == pytest.approx(73409.09, abs=0.01)
    assert db["VAT_AMOUNT"] == pytest.approx(7340.91, abs=0.01)
    assert db["PROC_N"] == 10 and db["DISCOUNT"] == 5
    assert db["TOTAL"] + db["VAT_AMOUNT"] == pytest.approx(85000 * 0.95)  # what the customer pays


def test_card_percent_adds_to_discount_and_quantity_multiplies() -> None:
    db = pricing.line_to_db(_line(qty=3, disc=5, card=5), vat_on=True)
    assert db["TOTAL"] + db["VAT_AMOUNT"] == pytest.approx(3 * 85000 * 0.90)
    assert db["TOTAL_NT"] == 3 * 85000


def test_no_vat_when_the_quote_or_the_line_has_none() -> None:
    for db in (pricing.line_to_db(_line(), vat_on=False), pricing.line_to_db(_line(vat=False), vat_on=True)):
        assert db["VAT_AMOUNT"] == 0 and db["PROC_N"] == 0
        assert db["TOTAL"] == pytest.approx(85000 * 0.95)


def test_round_trip_through_the_stored_columns() -> None:
    src = _line(qty=2, price=100000, disc=10, card=2.5)
    db = pricing.line_to_db(src, vat_on=True)
    back = pricing.line_from_db(
        db["QUANTITY"],
        db["PRICE"],
        db["DISCOUNT"],
        db["CARD_PERCENT"],
        db["VAT_AMOUNT"],
        db["PRICE_NT"],
        db["BASEPRICE"],
        db["PROC_N"],
    )
    assert back == {"qty": 2, "price": 100000, "disc": 10, "card": 2.5, "vat": True}


def test_old_rows_without_price_nt_fall_back_to_base_price_then_price() -> None:
    assert pricing.line_from_db(1, 100, 0, 0, 0, None, 120, 0)["price"] == 120
    assert pricing.line_from_db(1, 110, 0, 0, 10, None, None, 10)["price"] == pytest.approx(121)


@pytest.fixture
def car(monkeypatch: MonkeyPatch) -> dict[str, Any]:
    row = {
        "id": 4085,
        "car_id": 73,
        "plate": "7035УББ",
        "body_no": "",
        "engine_type": "",
        "vin": "",
        "color": "",
        "engine_no": "",
        "certificate": "",
        "driver_no": "",
        "maked": None,
        "spec": "",
        "year": 2016,
        "owner": "Бат",
        "phone": "99112233",
    }
    monkeypatch.setattr(quotes, "vehicle", lambda vehicle_id: row if vehicle_id == 4085 else None)
    return row


def _body(**kw: Any) -> dict[str, Any]:
    return {"vehicle_id": 4085, "works": [{"ref": 408, "qty": 1, "price": 1000}]} | kw


def test_parse_takes_customer_and_phone_from_the_vehicle(car: dict[str, Any]) -> None:
    data = quotes.parse(_body())
    assert (data["customer"], data["phone"], data["vat_on"], data["customer_id"]) == ("Бат", "99112233", True, None)
    assert data["works"][0]["disc"] == 0 and data["works"][0]["vat"] is True


def test_parse_cuts_long_text_to_the_column_length(car: dict[str, Any]) -> None:
    data = quotes.parse(_body(customer="Я" * 200, notes="н" * 500, phone="9" * 100))
    assert (len(data["customer"]), len(data["notes"]), len(data["phone"])) == (80, 100, 30)


@pytest.mark.parametrize(
    "change, text",
    [
        ({"vehicle_id": 0}, "Автомашин сонгоно уу"),
        ({"vehicle_id": 5}, "Автомашин олдсонгүй"),
        ({"works": [], "parts": []}, "Ажил эсвэл сэлбэгийн мөр"),
        ({"works": [{"qty": 1, "price": 1}]}, "бүртгэлтэй ажил"),
        ({"parts": [{"ref": 1, "qty": 1, "price": 1}, {"qty": 1, "price": 1}]}, "Сэлбэг №2"),
        ({"works": [{"ref": 1, "qty": 0, "price": 1}]}, "тоо"),
        ({"works": [{"ref": 1, "qty": 1, "price": -1}]}, "үнэ"),
        ({"works": [{"ref": 1, "qty": 1, "price": 1, "disc": 101}]}, "хөнгөлөлт"),
        ({"works": [{"ref": 1, "qty": 1, "price": 1, "disc": 60, "card": 50}]}, "нийлбэр"),
        ({"works": "x"}, "жагсаалт"),
        ({"date": "yesterday"}, "Огноо"),
        ({"customer_id": "abc"}, "Харилцагч"),
        ({"branch_id": "x"}, "Салбар"),
    ],
)
def test_parse_refuses_bad_requests(car: dict[str, Any], change: dict[str, Any], text: str) -> None:
    with pytest.raises(quotes.QuoteError) as e:
        quotes.parse(_body(**change))
    assert text in str(e.value)


def test_a_vehicle_without_a_make_cannot_be_quoted(car: dict[str, Any]) -> None:
    car["car_id"] = None
    with pytest.raises(quotes.QuoteError, match="марк"):
        quotes.parse(_body())


def test_customer_is_required_when_the_vehicle_has_no_owner_name(car: dict[str, Any]) -> None:
    car["owner"] = ""
    with pytest.raises(quotes.QuoteError, match="Үйлчлүүлэгчийн нэр"):
        quotes.parse(_body())
    assert quotes.parse(_body(customer="Дорж"))["customer"] == "Дорж"
