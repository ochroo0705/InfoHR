"""Company calendar: Sat/Sun off plus the Holiday table (spec §4)."""

from datetime import date, timedelta
from decimal import Decimal

from leave.models import Holiday

HALF = Decimal("0.5")

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


def holidays_between(start: date, end: date) -> set[date]:
    return set(Holiday.objects.filter(date__range=(start, end)).values_list("date", flat=True))


def is_working_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def working_days(start: date, end: date, *, start_half: bool = False, end_half: bool = False) -> Decimal:
    holidays = holidays_between(start, end)
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    total = Decimal(sum(1 for d in days if is_working_day(d, holidays)))
    if start == end:
        return HALF if (start_half or end_half) and total else total
    if start_half and is_working_day(start, holidays):
        total -= HALF
    if end_half and is_working_day(end, holidays):
        total -= HALF
    return total


def prefill_year(year: int) -> int:
    created = 0
    for month, day, name in FIXED_HOLIDAYS:
        _, was_created = Holiday.objects.get_or_create(date=date(year, month, day), defaults={"name": name})
        created += was_created
    return created


def has_holidays(year: int) -> bool:
    return Holiday.objects.filter(date__year=year).exists()
