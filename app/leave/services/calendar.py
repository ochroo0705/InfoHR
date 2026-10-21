"""Company calendar: Sat/Sun off plus public holidays from hr_legalholidays (spec §4)."""

from datetime import date, timedelta

from django.db.models import QuerySet
from macs.models import LegalHoliday

from leave.services import writes

# Fixed-date public holidays (Law on public holidays). Moving ones (Tsagaan Sar) are entered by hand.
FIXED_HOLIDAYS: list[tuple[int, int, str]] = [
    (1, 1, "Шинэ жил"),
    (3, 8, "Эмэгтэйчүүдийн баяр"),
    (6, 1, "Хүүхдийн баяр"),
    (7, 11, "Үндэсний их баяр наадам"),
    (7, 12, "Үндэсний их баяр наадам"),
    (7, 13, "Үндэсний их баяр наадам"),
    (7, 14, "Үндэсний их баяр наадам"),
    (7, 15, "Үндэсний их баяр наадам"),
    (11, 26, "Тусгаар тогтнолын өдөр"),
    (12, 29, "Үндэсний эрх чөлөө, тусгаар тогтнолоо сэргээсний баяр"),
]


def _overlapping(start: date, end: date) -> QuerySet[LegalHoliday]:
    return LegalHoliday.objects.filter(start_date__lte=end, end_date__gte=start)


def holiday_names(year: int) -> dict[date, str]:
    """Every day of `year` covered by a LegalHoliday row, mapped to that row's name."""
    return _expand(date(year, 1, 1), date(year, 12, 31))


def _expand(start: date, end: date) -> dict[date, str]:
    names: dict[date, str] = {}
    for row in _overlapping(start, end):
        first = max(row.start_date, start)
        last = min(row.end_date, end)
        for n in range((last - first).days + 1):
            names[first + timedelta(n)] = row.name
    return names


def holidays_between(start: date, end: date) -> set[date]:
    return set(_expand(start, end))


def is_working_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def working_days(start: date, end: date) -> int:
    holidays = holidays_between(start, end)
    return sum(1 for n in range((end - start).days + 1) if is_working_day(start + timedelta(n), holidays))


def prefill_year(year: int) -> int:
    """Add the fixed-date holidays missing from `year`. Returns how many dates were added."""
    mapping = holiday_names(year)
    added = 0
    for month, day, name in FIXED_HOLIDAYS:
        fixed = date(year, month, day)
        if fixed not in mapping:
            mapping[fixed] = name
            added += 1
    if added:
        writes.set_holiday_dates(year, mapping)
    return added


def has_holidays(year: int) -> bool:
    return _overlapping(date(year, 1, 1), date(year, 12, 31)).exists()
