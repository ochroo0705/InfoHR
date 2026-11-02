"""Cleaning of values typed into the log's filter fields and read from the URL.

Every helper drops a bad value instead of raising: a NUL byte, an overlong text or a malformed number becomes
"nothing typed", so a pasted link can never make the log page fail.
"""

import re
from datetime import date

MAX_WORDS = 8  # search words per field
MAX_WORD = 100  # characters per search word
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ID = re.compile(r"[0-9]{1,9}")  # ASCII digits only; longer numbers would overflow an integer column


def clean_text(value: object, limit: int) -> str:
    """The value as text: NUL bytes removed (Postgres refuses them), outer spaces stripped, cut to `limit`."""
    if not isinstance(value, str):
        return ""
    return value.replace("\x00", "")[:limit].strip()


def words(text: str) -> list[str]:
    """Search words: split on whitespace, at most MAX_WORDS, each cut to MAX_WORD characters."""
    parts = clean_text(text, 2000).split()
    return [part[:MAX_WORD] for part in parts[:MAX_WORDS]]


def parse_date(text: str) -> date | None:
    """A calendar day written YYYY-MM-DD, or None."""
    value = clean_text(text, 10)
    if not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:  # 2026-02-30, year 0000
        return None


def parse_id(text: str) -> int | None:
    """A record number: decimal digits only, at most nine of them."""
    value = clean_text(text, 20)
    if not _ID.fullmatch(value):
        return None
    return int(value)
