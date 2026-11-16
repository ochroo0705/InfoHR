"""Corrections from a report cell (D-080, phase 4): the department, position and manager of the job row shown, and the
base salary of today.

The record-level work (which record, its text, its form, the save through the history service) is in
employees.services.report_corrections: this module names no job, salary or history model (test T-028). The switch is
CompanySettings.report_corrections. The rights are the employee page's: manage employees for job fields, manage salary
for salary.
"""

import logging
from typing import Any

from accounts.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, DataError, IntegrityError
from django.http import QueryDict
from employees.services import report_corrections as service

from reports.cell_edit import CLASH, CellResult

logger = logging.getLogger(__name__)

# the cell key -> what it corrects: the job record the row shows, or today's salary record
KEYS = {"department": "job", "position": "job", "manager": "job", "salary": "salary"}
NEEDS_REASON = "Засварын шалтгааныг заавал бичнэ үү."
TOO_LONG_REASON = "Засварын шалтгаан 200 тэмдэгтээс хэтрэхгүй байна."
REASON_MAX = 200  # the reason's length in the activity log's line (the editor box has the same limit)


def enabled() -> bool:
    """The company setting «Тайлангаас засвар хийх»."""
    return service.setting_on()


def can_correct(user: User, employee: Any, key: str) -> bool:
    """May this user correct this cell of this employee: the setting is on and the right of the field."""
    if key not in KEYS or not enabled():
        return False
    return service.may_correct(user, employee, key)


def lookup(employee: Any, key: str, record_id: int | None) -> tuple[Any, str]:
    """The record a cell corrects and the message that blocks it now ("" when it can be corrected)."""
    return service.lookup(employee, key, record_id)


def record_for(employee: Any, key: str, record_id: int | None) -> Any:
    """The record a cell may correct now, or None (see service.record_for)."""
    return service.record_for(employee, key, record_id)


def shown_text(record: Any, key: str) -> str:
    """The text the cell shows for this record."""
    return service.shown_text(record, key)


def field_of(key: str) -> str:
    """The form field a cell key edits."""
    return service.field_of(key)


def form_for(user: User, record: Any, key: str, data: QueryDict | None = None) -> Any:
    """The employee page's form for this cell, bound to `data` when given."""
    return service.form_for(user, record, key, data)


def _spaced(text: str) -> str:
    return " ".join(text.split())


def save(user: User, employee: Any, key: str, record: Any, post: QueryDict) -> CellResult:
    """Validate and save one correction. `post` holds `old` (the text the editor loaded), the field's value and
    `reason`. CLASH when the cell shows other text now; NEEDS_REASON for a blank reason (nothing is saved). Refuses
    with PermissionDenied when `can_correct` is False. The field is checked on its own, as its form field."""
    if not can_correct(user, employee, key):
        raise PermissionDenied
    if _spaced(post.get("old", "")) != _spaced(service.shown_text(record, key)):
        return CellResult(ok=False, error=CLASH)
    reason = post.get("reason", "").strip()
    if not reason:
        return CellResult(ok=False, error=NEEDS_REASON)
    if len(reason) > REASON_MAX:
        return CellResult(ok=False, error=TOO_LONG_REASON)
    name = service.field_of(key)
    try:
        value: Any = service.form_for(user, record, key).fields[name].clean(post.get(name))
    except ValidationError as exc:
        return CellResult(ok=False, error=str(exc.messages[0]))
    try:
        updated = service.apply(user, record, key, value, reason)
    except service.HistoryError as exc:
        return CellResult(ok=False, error=str(exc))
    except (IntegrityError, DataError) as exc:
        logger.warning("report correction refused: %s", exc)
        return CellResult(ok=False, error=service.DB_REFUSED)
    except DatabaseError as exc:  # the database is down or busy: the cell says so instead of the page failing
        logger.warning("report correction failed: %s", exc)
        return CellResult(ok=False, error=service.DB_REFUSED)
    return CellResult(ok=True, text=service.shown_text(updated, key))
