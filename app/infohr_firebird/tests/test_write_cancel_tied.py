"""Cancelling one of two changes that share a date, on Firebird against EMPLOYEE_HISTORY_BD0 (2026-11-11).

The stale-history finding from the first run is fixed by `macs_writes.refresh_history_rows`.

`test_write_cancel.py` case C cancels the LATER-created of two tied changes and compares with today's state, which a
future-dated change does not touch. These cases look closer: cancel either of the two, then check the history rows
that stay behind and the employee row on the day the surviving change takes effect.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django
from infohr_firebird.tests.test_write_cancel import CANCEL_CODE

PREAMBLE = CANCEL_CODE.split("out = {}\n", 1)[0]

TIED_CODE = (
    PREAMBLE
    + """
out = {}

def on_day(pk, day):
    # What the daily sync would write on `day`: sync_current takes the job and salary valid that day.
    e = Employee.objects.get(pk=pk)
    macs_writes.sync_current(e, day)
    after = snap(pk)
    job = history.job_on(Employee.objects.get(pk=pk), day)
    sal = history.salary_on(Employee.objects.get(pk=pk), day)
    return {"employee": after, "wanted": {"department": job.department_id, "salary": str(sal.base_salary)}}

# T1: transfer and salary change both on FUT1. Cancel the salary change (created second); the transfer stays.
e1 = start(1)
ev_t1 = transfer(e1, FUT1, {"department": Department.objects.get(pk=dep2)})
ev_s1 = raise_salary(e1, FUT1, "1700000.00")
rows_before = rows(e1.pk)
events.cancel(ev_s1, reason="tied t1", by=by)
out["t1"] = {
    "rows_before": rows_before,
    "rows_after": rows(e1.pk),
    "employee_after_cancel": snap(e1.pk),
    "on_fut1": on_day(e1.pk, FUT1),
    "dep2": dep2,
    "dep1": dep1,
}

# T2: the same pair, but cancel the transfer (created first); the salary change stays.
e2 = start(2)
ev_t2 = transfer(e2, FUT1, {"department": Department.objects.get(pk=dep2)})
ev_s2 = raise_salary(e2, FUT1, "1700000.00")
rows_before2 = rows(e2.pk)
events.cancel(ev_t2, reason="tied t2", by=by)
out["t2"] = {
    "rows_before": rows_before2,
    "rows_after": rows(e2.pk),
    "employee_after_cancel": snap(e2.pk),
    "on_fut1": on_day(e2.pk, FUT1),
    "dep2": dep2,
    "dep1": dep1,
}

print("RESULT " + json.dumps(out, default=str))
"""
)


@pytest.fixture(scope="module")
def tied(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(TIED_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


@pytest.mark.parametrize("case", ["t1", "t2"])
def test_tied_cancel_removes_exactly_one_history_row(tied: dict[str, Any], case: str) -> None:
    data = tied[case]
    assert len(data["rows_after"]) == len(data["rows_before"]) - 1


@pytest.mark.parametrize("case", ["t1", "t2"])
def test_tied_cancel_employee_is_right_on_the_surviving_date(tied: dict[str, Any], case: str) -> None:
    on = tied[case]["on_fut1"]
    assert on["employee"]["department"] == on["wanted"]["department"]
    assert on["employee"]["salary"] == on["wanted"]["salary"]


def test_surviving_history_row_does_not_carry_the_cancelled_change(tied: dict[str, Any]) -> None:
    """After cancelling the transfer (T2) the remaining salary history row must not show the cancelled department."""
    data = tied["t2"]
    survivors = [r for r in data["rows_after"] if r["changed_date"].startswith("2035-03-01")]
    assert survivors, data["rows_after"]
    assert all(r["department"] != data["dep2"] for r in survivors), (data["rows_before"], data["rows_after"])
