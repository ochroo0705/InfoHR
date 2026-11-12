"""Limits on a question, the result it returns, and the timeout signal.

Plain Python only. No Django, no HR imports, no database connection.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_rows: int = 1000
    timeout_s: float = 15.0


@dataclass(frozen=True)
class Result:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool


class QueryTimeout(Exception):
    """Raised by a host's execute when the query was stopped because of the time limit."""
