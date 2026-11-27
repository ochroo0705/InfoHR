"""Promotions: what the screen may send (no database) and that the routes need a token."""

from typing import Any

import pytest
from django.test import Client

from autoservice import promotions

BASE: dict[str, Any] = {"name": "Тос", "start": "2026-04-01", "end": "2026-06-01"}
LINE = {"class_id": 181, "work_id": 4011, "percent": 50}


def test_parse_drops_duplicate_lines() -> None:
    d = promotions.parse({**BASE, "lines": [LINE, {**LINE, "percent": 10}, {"class_id": 180, "work_id": 4307}]})
    assert d["active"]
    assert d["lines"] == [
        {"class_id": 181, "work_id": 4011, "percent": 50.0},
        {"class_id": 180, "work_id": 4307, "percent": 0.0},
    ]


@pytest.mark.parametrize(
    "patch",
    [
        {"name": " "},
        {"end": "2026-03-01"},
        {"start": "bad"},
        {"lines": [{"class_id": 0, "work_id": 5}]},
        {"lines": [{**LINE, "percent": 101}]},
        {"lines": [{**LINE, "percent": "x"}]},
    ],
)
def test_parse_refuses_bad_input(patch: dict[str, Any]) -> None:
    with pytest.raises(promotions.PromotionError):
        promotions.parse({**BASE, **patch})


@pytest.mark.parametrize("url", ["promotions", "promotions/1"])
def test_routes_need_a_token(url: str) -> None:
    assert Client().get(f"/api/autoservice/{url}").status_code == 401
