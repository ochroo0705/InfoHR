from datetime import date, datetime
from typing import Any

from django.conf import settings
from django.db import models


class ServerComputedCharField(models.CharField[Any, Any]):
    """A text column that the database computes (a Firebird COMPUTED BY column, e.g. MACS EMPLOYEE.FULLNAME).
    Firebird refuses any write to it, so on Firebird ``generated`` is True: Django then neither inserts nor updates
    it and reads it back. On PostgreSQL the column is an ordinary text column and ``generated`` stays False."""

    generated = settings.DB_ENGINE == "firebird"


class TimestampDateField(models.DateField[Any, Any]):
    """A date kept in a production `timestamp` column (Firebird dialect-1 DATE)."""

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> date | None:
        return value.date() if isinstance(value, datetime) else value


class SmallintFlagField(models.BooleanField[Any, Any]):
    """A production smallint flag (1 = yes, 0 or null = no) that Python sees as a bool.
    Null reads as False; a bool is stored as 1 or 0."""

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> bool:
        return bool(value)

    def get_prep_value(self, value: Any) -> int | None:
        return None if value is None else int(bool(value))
