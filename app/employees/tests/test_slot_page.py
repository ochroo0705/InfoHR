"""The request-free slot screen service (employees.services.slot_page), position-slots plan step 3e Task 1."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from macs.models import Branch, NazgRow, Position

from employees.services import history, slot_page
from employees.services.slot_page import SlotLine
from employees.slot_kind import MAIN, TEMPORARY
from employees.tests.helpers import next_order_number

from .conftest import hire_values

pytestmark = pytest.mark.django_db

TODAY = date(2026, 6, 15)


@pytest.fixture
def branch() -> Branch:
    return Branch.objects.create(name="Төв салбар")


def _hire(actor: User, job_values: dict[str, Any], branch: Branch, n: int) -> None:
    values = {**hire_values(f"УБ9933{n:04d}"), "branch": branch}
    history.hire(
        values,
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("1"),
        by=actor,
        order_number=next_order_number(),
    )


def test_year_param_accepts_four_digits_in_range() -> None:
    assert slot_page.year_param("2026", 1999) == 2026
    assert slot_page.year_param("2000", 1999) == 2000
    assert slot_page.year_param("2100", 1999) == 2100


def test_year_param_falls_back_for_bad_values() -> None:
    fallback = 1234  # never a valid parse of any bad value below, so a wrong parse shows up
    for raw in ("abc", "99", "1999", "2101", "２０２６", None, ""):
        assert slot_page.year_param(raw, fallback) == fallback, raw


def test_year_param_refuses_full_width_digits() -> None:
    assert slot_page.year_param("２０２６", 1234) == 1234  # int("２０２６") == 2026, so this must not parse


def test_used_on_is_today_for_this_year_and_jan_first_otherwise() -> None:
    assert slot_page.used_on(2026, TODAY) == TODAY
    assert slot_page.used_on(2025, TODAY) == date(2025, 1, 1)
    assert slot_page.used_on(2027, TODAY) == date(2027, 1, 1)


def test_slot_lines_order_and_free_count(actor: User, job_values: dict[str, Any], branch: Branch) -> None:
    position = job_values["position"]
    other = Position.objects.create(name="Ахлах нягтлан")
    NazgRow.objects.create(kind="Main", qty=3, year=2026, position=position, branch=branch)
    NazgRow.objects.create(kind="Main", qty=1, year=2026, position=other, branch=branch)
    _hire(actor, job_values, branch, 1)  # one person in the 3-post row
    lines = slot_page.slot_lines(2026, TODAY)
    assert [line.row.position.name for line in lines] == ["Ахлах нягтлан", "Нягтлан"]  # by position name
    by_name = {line.row.position.name: line for line in lines}
    assert (by_name[position.name].posts, by_name[position.name].used, by_name[position.name].free) == (3, 1, 2)
    assert (by_name[other.name].posts, by_name[other.name].used, by_name[other.name].free) == (1, 0, 1)


def test_slot_lines_overfilled_row_has_negative_free(actor: User, job_values: dict[str, Any], branch: Branch) -> None:
    position = job_values["position"]
    NazgRow.objects.create(kind="Main", qty=1, year=2026, position=position, branch=branch)
    _hire(actor, job_values, branch, 1)
    _hire(actor, job_values, branch, 2)
    (line,) = slot_page.slot_lines(2026, TODAY)
    assert (line.posts, line.used, line.free) == (1, 2, -1)


def test_totals_sum_all_lines() -> None:
    lines = [
        SlotLine(row=NazgRow(kind=MAIN, qty=3, year=2026), posts=3, used=1, free=2),
        SlotLine(row=NazgRow(kind=TEMPORARY, qty=2, year=2026), posts=2, used=3, free=-1),
    ]
    assert slot_page.totals(lines) == slot_page.SlotTotals(posts=5, used=4, free=1)
    assert slot_page.totals([]) == slot_page.SlotTotals(posts=0, used=0, free=0)


def test_kind_label() -> None:
    assert slot_page.kind_label(TEMPORARY) == "Түр"
    assert slot_page.kind_label(MAIN) == "Үндсэн"
