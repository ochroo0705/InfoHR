"""Discount cards: routes need a token, and the statement refuses a bad date before touching the database."""

import pytest
from django.test import Client

from autoservice import cards, tokens


@pytest.mark.parametrize(
    "url", ["discount-cards", "discount-cards/1", "discount-cards/1/statement", "discount-cards/intervals"]
)
def test_routes_need_a_token(url: str) -> None:
    assert Client().get(f"/api/autoservice/{url}").status_code == 401


def test_statement_refuses_a_bad_date() -> None:
    headers = {"Authorization": f"Bearer {tokens.issue('dash', 'r')[0]}"}
    r = Client().get("/api/autoservice/discount-cards/1/statement?from=yesterday", headers=headers)
    assert r.status_code == 400


def test_card_types_follow_the_dcode() -> None:
    # GET_BONUSINFO: -1 bonus collecting, -2 stepped; -3/-4 keep a bonus balance too.
    assert cards.TYPES[-1] == "Бонус цуглуулах карт"
    assert set(cards.TYPES) == {-1, -2, -3, -4}
