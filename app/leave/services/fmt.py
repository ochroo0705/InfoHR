"""Shared formatting for user-visible day counts."""

from decimal import Decimal


def fmt_days(days: int | Decimal, *, signed: bool = False) -> str:
    """Render a whole-day count without a trailing ".0" (15 -> "15", -5 -> "-5", Decimal("15.0") -> "15")."""
    text = format(Decimal(days).normalize(), "f")
    return f"+{text}" if signed and days > 0 else text
