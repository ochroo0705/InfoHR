"""Run a workspace tool's SQL through the governed path: the saved query plus a Spec, checked and run as the viewer.

Every function here builds one SQL text with ws_sql and runs it with ``run_question`` exactly once. There is no other
way to run SQL here. The gate (switch, database, non-empty catalogue) is the same as sqlanswer's, and the reasons
are sqlanswer's own constants.

No new migration. This module may import hr_sql and sqlcore; sqlcore imports nothing from HR.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from hr_sql.host import HrHost
from sqlcore.explain import tidy_result
from sqlcore.limits import Limits
from sqlcore.runner import Host, Refused, run_question

from assistant import sqlanswer
from assistant.sqlanswer import NO_VIEWS_REASON, OFF_REASON, UNAVAILABLE_REASON
from assistant.ws_limits import EXPORT_MAX_ROWS, EXPORT_TIMEOUT_S, MAX_PAGE, PAGE_SIZE
from assistant.ws_sql import Spec, SpecError, count_sql, group_sql, wrap_sql

# Above MAX_PAGE the page is refused, so a typed number cannot ask for a huge window.
PAGE_TOO_FAR_REASON = f"A page above {MAX_PAGE} cannot be shown."


@dataclass(frozen=True)
class RunResult:
    status: str  # "ok", "refused", "off" or "unavailable"
    reason: str = ""  # "" when ok
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[object, ...], ...] = ()  # tidied: money rounded to 2 places, as on the card
    cut: bool = False  # True when more rows exist than the rows above (set by run_base only)


def _host(host: Host | None) -> Host:
    return host if host is not None else HrHost()


def _blocked(user: object, governed: Host) -> RunResult | None:
    """The same gate as sqlanswer.sql_answer. None when the run may go ahead."""
    if not sqlanswer._setting_enabled():
        return RunResult(status="off", reason=OFF_REASON)
    if not sqlanswer._database_ready():
        return RunResult(status="unavailable", reason=UNAVAILABLE_REASON)
    if not governed.catalogue_for(user).views:
        return RunResult(status="unavailable", reason=NO_VIEWS_REASON)
    return None


def _run(user: object, sql: str, limits: Limits, governed: Host) -> tuple[RunResult, bool]:
    """Run the checked SQL once. Returns the result and whether the rows were cut at limits.max_rows."""
    outcome = run_question(governed, user, sql, limits)
    if isinstance(outcome, Refused):
        return RunResult(status="refused", reason=outcome.reason), False
    tidied, _changed = tidy_result(outcome.result)
    result = RunResult(status="ok", columns=tuple(tidied.columns), rows=tuple(tidied.rows))
    return result, outcome.result.truncated


def _too_far(page: object) -> bool:
    return isinstance(page, int) and not isinstance(page, bool) and page > MAX_PAGE


def _rows_sql(base_sql: str, columns: tuple[str, ...], spec: Spec, page: int | None) -> str:
    """Grouped rows when the spec groups, otherwise the filtered and sorted rows. Shared by the page and the export."""
    if spec.group_by:
        return group_sql(base_sql, columns, spec, page=page)
    return wrap_sql(base_sql, columns, spec, page=page)


def base_columns(user: object, base_sql: str, host: Host | None = None) -> RunResult:
    """The saved query run with one row allowed. Returns its column names, and that one tidied row if there is one."""
    governed = _host(host)
    blocked = _blocked(user, governed)
    if blocked is not None:
        return blocked
    result, _cut = _run(user, base_sql, Limits(max_rows=1), governed)
    return result


_DEFAULT_TIMEOUT_S = Limits().timeout_s


def run_base(
    user: object,
    base_sql: str,
    host: Host | None = None,
    limit: int = PAGE_SIZE,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> RunResult:
    """The saved query itself, up to ``limit`` rows (PAGE_SIZE for the table, EXPORT_MAX_ROWS for an export), with no
    tool applied. Used when the result has no column a tool can use. ``cut`` says whether more rows exist."""
    governed = _host(host)
    blocked = _blocked(user, governed)
    if blocked is not None:
        return blocked
    result, cut = _run(user, base_sql, Limits(max_rows=limit, timeout_s=timeout_s), governed)
    return replace(result, cut=cut) if result.status == "ok" else result


def run_page(
    user: object, base_sql: str, columns: tuple[str, ...], spec: Spec, page: int, host: Host | None = None
) -> RunResult:
    """One page of PAGE_SIZE rows (0-based page), with the spec's filters, sort or grouping applied."""
    governed = _host(host)
    blocked = _blocked(user, governed)
    if blocked is not None:
        return blocked
    if _too_far(page):
        return RunResult(status="refused", reason=PAGE_TOO_FAR_REASON)
    try:
        sql = _rows_sql(base_sql, columns, spec, page)
    except SpecError as error:
        return RunResult(status="refused", reason=str(error))
    result, _cut = _run(user, sql, Limits(max_rows=PAGE_SIZE), governed)
    return result


def run_count(
    user: object, base_sql: str, columns: tuple[str, ...], spec: Spec, host: Host | None = None
) -> int | None:
    """How many rows of the saved query pass the spec's filters, or with a group_by how many groups they fall into.
    None when the run is not ok."""
    governed = _host(host)
    if _blocked(user, governed) is not None:
        return None
    try:
        sql = count_sql(base_sql, columns, spec)
    except SpecError:
        return None
    result, _cut = _run(user, sql, Limits(max_rows=1), governed)
    if result.status != "ok" or not result.rows or not result.rows[0]:
        return None
    value = result.rows[0][0]
    if isinstance(value, bool) or not isinstance(value, (int, Decimal, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def run_export(
    user: object, base_sql: str, columns: tuple[str, ...], spec: Spec, host: Host | None = None
) -> tuple[RunResult, bool]:
    """Every row the spec selects, up to EXPORT_MAX_ROWS. The second value is True when the rows were cut there."""
    governed = _host(host)
    blocked = _blocked(user, governed)
    if blocked is not None:
        return blocked, False
    try:
        sql = _rows_sql(base_sql, columns, spec, None)
    except SpecError as error:
        return RunResult(status="refused", reason=str(error)), False
    return _run(user, sql, Limits(max_rows=EXPORT_MAX_ROWS, timeout_s=EXPORT_TIMEOUT_S), governed)
