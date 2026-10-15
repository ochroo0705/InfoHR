from datetime import date
from decimal import Decimal

import pytest

from leave.models import Holiday
from leave.services import calendar

pytestmark = pytest.mark.django_db


def test_weekdays_only() -> None:
    # Mon 2027-03-01 .. Sun 2027-03-14 = 10 working days
    assert calendar.working_days(date(2027, 3, 1), date(2027, 3, 14)) == Decimal(10)


def test_holiday_inside_leave_is_not_counted() -> None:
    Holiday.objects.create(date=date(2027, 3, 8), name="Эмэгтэйчүүдийн баяр")
    assert calendar.working_days(date(2027, 3, 1), date(2027, 3, 12)) == Decimal(9)


def test_half_days() -> None:
    assert calendar.working_days(date(2027, 3, 1), date(2027, 3, 5), start_half=True, end_half=True) == Decimal(4)
    assert calendar.working_days(date(2027, 3, 1), date(2027, 3, 1), start_half=True) == Decimal("0.5")
    assert calendar.working_days(date(2027, 3, 1), date(2027, 3, 1), start_half=True, end_half=True) == Decimal("0.5")


def test_half_flag_on_non_working_day_is_ignored() -> None:
    # Sat 2027-03-06 .. Wed 2027-03-10: 3 working days; start_half falls on Saturday
    assert calendar.working_days(date(2027, 3, 6), date(2027, 3, 10), start_half=True) == Decimal(3)


def test_weekend_only_is_zero() -> None:
    assert calendar.working_days(date(2027, 3, 6), date(2027, 3, 7)) == Decimal(0)


def test_prefill_year_is_idempotent() -> None:
    created = calendar.prefill_year(2027)
    assert created == len(calendar.FIXED_HOLIDAYS)
    assert Holiday.objects.filter(date=date(2027, 7, 11)).exists()
    assert calendar.prefill_year(2027) == 0
    assert calendar.has_holidays(2027) and not calendar.has_holidays(2028)
