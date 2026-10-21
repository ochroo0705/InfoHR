from datetime import date

import pytest
from macs.models import LegalHoliday

from leave.services import calendar

pytestmark = pytest.mark.django_db


def _holiday(start: date, end: date, name: str) -> LegalHoliday:
    return LegalHoliday.objects.create(
        name=name,
        start_date=start,
        end_date=end,
        hdays=(end - start).days + 1,
    )


def test_weekdays_only() -> None:
    # Mon 2027-03-01 .. Sun 2027-03-14 = 10 working days
    assert calendar.working_days(date(2027, 3, 1), date(2027, 3, 14)) == 10


def test_holiday_inside_leave_is_not_counted() -> None:
    _holiday(date(2027, 3, 8), date(2027, 3, 8), "Эмэгтэйчүүдийн баяр")
    assert calendar.working_days(date(2027, 3, 1), date(2027, 3, 12)) == 9


def test_multi_day_holiday_row_expanded() -> None:
    _holiday(date(2026, 2, 17), date(2026, 2, 19), "Цагаан сар")
    assert calendar.holidays_between(date(2026, 2, 1), date(2026, 2, 28)) == {
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 2, 19),
    }


def test_holiday_row_clipped_to_range() -> None:
    _holiday(date(2026, 2, 17), date(2026, 2, 19), "Цагаан сар")
    assert calendar.holidays_between(date(2026, 2, 18), date(2026, 2, 18)) == {date(2026, 2, 18)}


def test_working_days_whole() -> None:
    # Mon 2027-03-01 .. Fri 2027-03-05 with Wed 2027-03-03 as a holiday = 4 whole days
    _holiday(date(2027, 3, 3), date(2027, 3, 3), "Амралтын өдөр")
    result = calendar.working_days(date(2027, 3, 1), date(2027, 3, 5))
    assert result == 4
    assert type(result) is int


def test_weekend_only_is_zero() -> None:
    assert calendar.working_days(date(2027, 3, 6), date(2027, 3, 7)) == 0


def test_holiday_names_maps_each_day() -> None:
    _holiday(date(2027, 2, 1), date(2027, 2, 2), "Шинэ жил")
    assert calendar.holiday_names(2027) == {
        date(2027, 2, 1): "Шинэ жил",
        date(2027, 2, 2): "Шинэ жил",
    }


def test_prefill_year_is_idempotent() -> None:
    assert not calendar.has_holidays(2027)
    added = calendar.prefill_year(2027)
    assert added == len(calendar.FIXED_HOLIDAYS)
    assert calendar.holiday_names(2027)[date(2027, 7, 11)] == "Үндэсний их баяр наадам"
    assert calendar.prefill_year(2027) == 0
    assert calendar.has_holidays(2027) and not calendar.has_holidays(2028)


def test_prefill_keeps_existing_holiday_names() -> None:
    _holiday(date(2027, 1, 1), date(2027, 1, 1), "Өөр нэр")
    added = calendar.prefill_year(2027)
    assert added == len(calendar.FIXED_HOLIDAYS) - 1
    assert calendar.holiday_names(2027)[date(2027, 1, 1)] == "Өөр нэр"
