"""The Today page rules as services: the away shade table and the attention box (tone and tiers)."""

import pytest
from accounts.models import User

from employees import attention
from employees.services import today_page


@pytest.mark.parametrize(
    ("count", "off", "headcount", "expected"),
    [
        (None, False, 50, "off"),
        (3, True, 50, "off"),
        (0, False, 50, "zero"),
        (1, False, 50, "low"),
        (3, False, 50, "mid"),
        (5, False, 50, "high"),
        (1, False, 0, "low"),
    ],
)
def test_away_shade_table(count: int | None, off: bool, headcount: int, expected: str) -> None:
    assert today_page.away_shade(count, off, headcount) == expected


def test_shade_classes_cover_every_key() -> None:
    assert set(today_page.SHADE_CLASSES) == {"off", "zero", "low", "mid", "high"}
    assert today_page.SHADE_CLASSES["off"] == "bg-slate-100 text-slate-400"
    assert today_page.SHADE_CLASSES["zero"] == "bg-sky-50 text-slate-500"
    assert today_page.SHADE_CLASSES["low"] == "bg-sky-200"


@pytest.mark.django_db
def test_box_with_nothing_is_calm() -> None:
    user = User.objects.create_user("svc_calm", password="x-long-pass-123")  # noqa: S106
    box = attention.box(user, [])
    assert box.tone == "calm"
    assert box.shown == []
    assert box.hidden == []


@pytest.mark.django_db
def test_box_with_an_overdue_item_is_urgent() -> None:
    user = User.objects.create_user("svc_urgent", password="x-long-pass-123")  # noqa: S106
    found = [attention.Attention(None, "Test overdue", "lists_death", attention.OVERDUE)]
    box = attention.box(user, found)
    assert box.tone == "urgent"
    assert box.tiers.urgent_count == 1
