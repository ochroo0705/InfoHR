"""Shared helpers for the governed view tests: run a question as a user, read a view's columns, build an id list.

Firebird only. The callers install the governed objects through a fixture (conftest.py::governed_objects).
"""

from typing import Any

import pytest
from accounts.models import User
from django.db import transaction
from sqlcore.limits import Limits
from sqlcore.runner import DEFAULT_LIMITS, Answered, Refused, run_question

from hr_sql.connection import GOVERNED_ALIAS, governed_connection
from hr_sql.host import HrHost


def rows(user: User, sql: str) -> list[tuple[Any, ...]]:
    outcome = run_question(HrHost(), user, sql, DEFAULT_LIMITS)
    if isinstance(outcome, Refused):
        pytest.fail(f"Refused: {outcome.reason}")
    assert isinstance(outcome, Answered)
    return list(outcome.result.rows)


def refusal(user: User, sql: str, limits: Limits = DEFAULT_LIMITS) -> str:
    outcome = run_question(HrHost(), user, sql, limits)
    assert isinstance(outcome, Refused), "the question should have been refused"
    reason: str = outcome.reason
    return reason


def columns(view: str) -> list[str]:
    with transaction.atomic(using=GOVERNED_ALIAS), governed_connection().cursor() as cursor:
        cursor.execute(f"SELECT * FROM {view} WHERE 1 = 0")  # noqa: S608 (fixed view names)
        return [str(column[0]).strip() for column in cursor.description or ()]


def id_list(ids: list[int]) -> str:
    return ", ".join(str(pk) for pk in ids)
