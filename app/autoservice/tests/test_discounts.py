"""Discount settings: what the screen may send (no database) and that the routes need a token."""

from datetime import date
from typing import Any

import pytest
from django.test import Client

from autoservice import discounts

BASE: dict[str, Any] = {"name": "Оосор", "type": 9, "percent": 5, "start": "2026-04-01", "end": "2027-01-01"}


def test_parse_keeps_the_screen_fields() -> None:
    d = discounts.parse({**BASE, "items": [{"ref": 7, "percent": "12"}, {"ref": 7}, {"ref": 0}, {"ref": 8}]})
    assert d["start"] == date(2026, 4, 1) and d["end"] == date(2027, 1, 1)
    assert d["active"] and not d["all_items"]
    assert d["items"] == [{"ref": 7, "percent": 12.0}, {"ref": 8, "percent": None}]  # no duplicates, no empty ids


def test_all_items_ignores_the_item_list() -> None:
    assert discounts.parse({**BASE, "all_items": True, "items": [{"ref": 7}]})["items"] == []


def test_unknown_type_falls_back_to_percent() -> None:
    assert discounts.parse({**BASE, "type": 42})["type"] == 1


@pytest.mark.parametrize(
    "patch",
    [{"name": " "}, {"percent": 101}, {"percent": -1}, {"percent": "x"}, {"end": "2026-04-01"}, {"start": "bad"}],
)
def test_parse_refuses_bad_input(patch: dict[str, Any]) -> None:
    with pytest.raises(discounts.DiscountError):
        discounts.parse({**BASE, **patch})


@pytest.mark.parametrize("url", ["discounts", "discounts/1", "discounts/lookups", "discounts/items"])
def test_routes_need_a_token(url: str) -> None:
    assert Client().get(f"/api/autoservice/{url}").status_code == 401
