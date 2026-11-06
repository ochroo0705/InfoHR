"""Exact money amounts that also work on a Firebird DOUBLE PRECISION column.

On Firebird SQL dialect 1, a DECIMAL/NUMERIC with more than 9 digits is stored as a double and read
back as a float, so plain Decimal storage can drift. ExactMoneyField keeps the normal numeric(14,2)
column on PostgreSQL. On Firebird it stores a DOUBLE PRECISION column, rounds every value to 2
places (ROUND_HALF_UP) before it is sent and after it is read, and converts to float only at the
database boundary. Everywhere else the values stay Decimal.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db import models

CENT = Decimal("0.01")
FIREBIRD_VENDOR = "firebird"


class ExactMoneyField(models.DecimalField):
    """DecimalField for money with exactly 2 decimal places (defaults: 14 digits, 2 places)."""

    exact_money = True  # read by infohr_firebird.checks: this field is safe on Firebird, no W001

    def __init__(self, verbose_name: Any = None, name: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(verbose_name, name, **kwargs)

    def db_type(self, connection: Any) -> str:
        if connection.vendor == FIREBIRD_VENDOR:
            return "DOUBLE PRECISION"
        return super().db_type(connection)

    def _quantized(self, value: Any) -> Decimal | None:
        if value is None:
            return None
        return self.to_python(value).quantize(CENT, rounding=ROUND_HALF_UP)

    def get_db_prep_value(self, value: Any, connection: Any, prepared: bool = False) -> Any:
        quantized = self._quantized(value)
        if quantized is None:
            return None
        if connection.vendor == FIREBIRD_VENDOR:
            return float(quantized)
        return quantized

    def get_db_prep_save(self, value: Any, connection: Any) -> Any:
        return self.get_db_prep_value(value, connection)

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, float):
            value = Decimal(repr(value))
        return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
