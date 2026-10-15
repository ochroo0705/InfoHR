"""Shared formatting for user-visible day counts."""

from decimal import Decimal


def fmt_days(days: Decimal, *, signed: bool = False) -> str:
    """Render a day count without a trailing ".0" (15.0 -> "15", 4.5 -> "4.5")."""
    text = format(days.normalize(), "f")
    return f"+{text}" if signed and days > 0 else text
