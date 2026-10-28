import re
from datetime import date

# Query-string values are user input: parse them strictly and treat anything odd as "not given".
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def id_param(value: str | None) -> int | None:
    if not value or len(value) > 12 or not value.isdecimal():
        return None
    number = int(value)
    return number if 0 < number <= 2147483647 else None  # must fit a positive int4


def date_param(value: str | None) -> date | None:
    """ISO YYYY-MM-DD within 1900-2100, otherwise None."""
    if not value or not _ISO_DATE.fullmatch(value):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:  # e.g. 2026-02-30
        return None
    return parsed if 1900 <= parsed.year <= 2100 else None
