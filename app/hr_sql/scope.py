"""Fills GOV_SCOPE with the employee ids the asker may see, and whether each one still works here today.

The visible rule is employees/access.py::visible_employees. The working rule is the employee list's own: row_for and
is_working in employees/listing.py; working_flags below is a lean copy of it, pinned by a test.

The fill runs inside the caller's transaction on the governed connection. GOV_SCOPE is a global temporary table
(ON COMMIT DELETE ROWS), so its rows live only until that transaction ends.
"""

from collections.abc import Iterator
from datetime import date

from accounts.models import User
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import QuerySet
from django.utils import timezone
from employees.access import visible_employees
from employees.listing import LEGACY_NOT_WORKING, WORKING_STATES
from employees.models import Employee, JobRecord, JobStatus

_CLEAR = "DELETE FROM GOV_SCOPE"
# Rows go in as EXECUTE BLOCK statements of this many INSERTs: about 8x faster than one INSERT per row (20000 rows:
# 0.3 s against 2.5 s). Firebird refuses a block of 256 or more INSERTs ("Too many Contexts"), so stay well under.
_BLOCK_ROWS = 100


def _insert_blocks(pairs: list[tuple[int, int]]) -> Iterator[str]:
    """EXECUTE BLOCK statements that insert `pairs`. The values are formatted in, not bound: both are int() of ids and
    0/1 flags that came from our own database, so nothing here is text."""
    for start in range(0, len(pairs), _BLOCK_ROWS):
        rows = "".join(
            f"INSERT INTO GOV_SCOPE (EMP_ID, WORKING) VALUES ({int(pk)}, {int(flag)});"  # noqa: S608 (integers only)
            for pk, flag in pairs[start : start + _BLOCK_ROWS]
        )
        yield f"EXECUTE BLOCK AS BEGIN {rows} END"


def working_flags(people: QuerySet[Employee], today: date) -> dict[int, int]:
    """Employee id -> 1 if the employee list counts the person as working on `today`, else 0.

    Two plain column queries (no Employee or JobRecord objects, no position or department): the same answer as
    listing.row_for + listing.is_working, which test_scope pins (test_working_flags_match_the_employee_list). Keep
    the two in step: this copy exists only because building the full rows cost ~0.6 s per 1000 people."""
    ids = people.values("pk")
    jobs: dict[int, list[tuple[int, date, date | None, str]]] = {}
    for emp, start, end, status, pk in JobRecord.objects.filter(employee_id__in=ids).values_list(
        "employee_id", "start_date", "end_date", "status", "pk"
    ):
        jobs.setdefault(emp, []).append((pk, start, end, status))
    flags: dict[int, int] = {}
    for pk, emptype, taken_leave in people.values_list("pk", "emptype", "taken_leave"):
        records = jobs.get(pk, [])
        holding = [r for r in records if r[1] <= today and (r[2] is None or r[2] > today)]
        if holding:
            state = min(holding)[3]  # lowest pk, as row_for picks
        elif not records:
            state = _legacy_state(emptype, taken_leave)
        else:
            first = min(records, key=lambda r: (r[1], r[2] is None, r[2] or date.max))
            state = "upcoming" if first[1] > today else "left"
        flags[pk] = 1 if state in WORKING_STATES else 0
    return flags


def _legacy_state(emptype: int | None, taken_leave: int | None) -> str:
    """No HR job history: the MACS row decides (listing.legacy_job)."""
    if emptype in LEGACY_NOT_WORKING:
        return JobStatus.LEFT
    return JobStatus.LONG_LEAVE if taken_leave else JobStatus.ACTIVE


def fill_scope(connection: BaseDatabaseWrapper, user: User) -> int:
    """Replace the rows of GOV_SCOPE with the ids `user` may see, each with its WORKING flag. Returns how many ids were
    written.

    Call it inside the transaction that will run the governed query. A user with no visible employee gets an empty
    scope, so every governed view then returns zero rows.
    """
    flags = working_flags(visible_employees(user), timezone.localdate())
    ids = sorted(flags)
    with connection.cursor() as cursor:
        cursor.execute(_CLEAR)
        for statement in _insert_blocks([(pk, flags[pk]) for pk in ids]):
            cursor.execute(statement)
    return len(ids)
