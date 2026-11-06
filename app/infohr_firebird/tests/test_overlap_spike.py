"""Spike: can a "no overlapping history rows" guard hold on Firebird 3 when two writers run at once?

This is an experiment, not a regression test. Every scenario runs on the cloned database
(fb_clone), never on the template. The test prints one block per scenario; the outcomes and the
decision are written up in docs/migration/overlap-guard-spike.md.

The test asserts only two things: the scenarios all ran, and the trigger rejects an overlap when
the writes are serial (otherwise nothing measured below would mean anything).

Scratch objects use the SPIKE_ prefix so they cannot clash with real tables in the clone.
"""

import contextlib
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import firebird.driver as fbd  # type: ignore[import-untyped]
from django.db import connections

OVERLAP = "IHR_HISTORY_OVERLAP"

# The trigger treats a NULL end_date as open-ended: COALESCE(..., '9999-12-31') is the sentinel.
DDL = [
    "CREATE EXCEPTION IHR_HISTORY_OVERLAP 'Employee history periods overlap'",
    "CREATE TABLE SPIKE_T (ID INTEGER NOT NULL PRIMARY KEY, EMPLOYEE_ID INTEGER NOT NULL, "
    "START_DATE DATE NOT NULL, END_DATE DATE)",
    "CREATE TABLE SPIKE_L (EMPLOYEE_ID INTEGER NOT NULL PRIMARY KEY, N INTEGER NOT NULL)",
    "INSERT INTO SPIKE_L (EMPLOYEE_ID, N) VALUES (1, 0)",
    """CREATE TRIGGER SPIKE_T_OVERLAP FOR SPIKE_T
ACTIVE BEFORE INSERT OR UPDATE POSITION 0 AS
BEGIN
  IF (EXISTS (SELECT 1 FROM SPIKE_T OTHER_ROW
              WHERE OTHER_ROW.EMPLOYEE_ID = NEW.EMPLOYEE_ID
                AND OTHER_ROW.ID <> NEW.ID
                AND OTHER_ROW.START_DATE <= COALESCE(NEW.END_DATE, CAST('9999-12-31' AS DATE))
                AND COALESCE(OTHER_ROW.END_DATE, CAST('9999-12-31' AS DATE)) >= NEW.START_DATE)) THEN
    EXCEPTION IHR_HISTORY_OVERLAP;
END""",
]

INSERT = "INSERT INTO SPIKE_T (ID, EMPLOYEE_ID, START_DATE, END_DATE) VALUES (?, 1, ?, ?)"
UPDATE_LOCK = "UPDATE SPIKE_L SET N = N + 1 WHERE EMPLOYEE_ID = 1"
COUNT = "SELECT COUNT(*) FROM SPIKE_T WHERE EMPLOYEE_ID = 1"
ROWS = "SELECT ID, START_DATE, END_DATE FROM SPIKE_T WHERE EMPLOYEE_ID = 1 ORDER BY ID"
LOCK_VALUE = "SELECT N FROM SPIKE_L WHERE EMPLOYEE_ID = 1"

ROW_FIRST = (1, "2026-01-01", "2026-06-30")
ROW_SECOND = (2, "2026-03-01", None)  # open-ended, overlaps ROW_FIRST

# firebird-driver: lock_timeout=-1 waits forever (the Firebird default), 0 is no-wait.
# Firebird 3.0 has no lock-timeout TPB item (that came in Firebird 4); the probe in the
# spike showed the driver accepts the option, so the wait_lt2 case measures what really happens.
LOCK_MODES: dict[str, tuple[int, float]] = {
    # mode: (lock_timeout for the second writer, seconds the first writer holds its lock)
    "nowait": (0, 0.0),
    "wait": (-1, 1.0),
    "wait_lt2": (2, 5.0),
}


def _open(path: str) -> fbd.Connection:
    kwargs: dict[str, Any] = {"user": "SYSDBA", "charset": "UTF8"}
    password = os.environ.get("FIREBIRD_PASSWORD", "")
    if password:
        kwargs["password"] = password  # secret: from the environment only
    return fbd.connect(path, **kwargs)


def _begin(conn: fbd.Connection, isolation: fbd.Isolation, lock_timeout: int = -1) -> fbd.TransactionManager:
    tm = conn.transaction_manager()
    tm.begin(fbd.tpb(isolation, lock_timeout=lock_timeout))
    return tm


def _classify(message: str) -> str:
    text = " ".join(message.split())
    lowered = text.lower()
    if OVERLAP in text:
        return f"ERROR {OVERLAP}"
    if "lock conflict" in lowered:
        return "ERROR lock conflict (no-wait refused at once)"
    if "update conflicts" in lowered:
        return "ERROR update conflict (row changed by a transaction committed after this one started)"
    if "lock timeout" in lowered or "timeout" in lowered:
        return "ERROR lock timeout"
    return "ERROR other: " + text[:200]


def _attempt(action: Callable[[], Any]) -> str:
    try:
        action()
        return "ok"
    except Exception as exc:  # the spike records every database error as an outcome
        return f"{_classify(str(exc))} | raw: {' '.join(str(exc).split())[:400]}"


def _run(tm: fbd.TransactionManager, sql: str, params: tuple[Any, ...] = ()) -> None:
    tm.cursor().execute(sql, params)


def _scalar(tm: fbd.TransactionManager, sql: str) -> Any:
    cur = tm.cursor()
    cur.execute(sql)
    return cur.fetchone()[0]


def _rows(tm: fbd.TransactionManager) -> list[str]:
    cur = tm.cursor()
    cur.execute(ROWS)
    return [f"id {r[0]}: {r[1]} .. {r[2]}" for r in cur.fetchall()]


def _setup(base: fbd.Connection) -> None:
    for sql in DDL:
        tm = _begin(base, fbd.Isolation.SNAPSHOT)
        _run(tm, sql)
        tm.commit()


def _reset(base: fbd.Connection) -> None:
    tm = _begin(base, fbd.Isolation.SNAPSHOT)
    _run(tm, "DELETE FROM SPIKE_T")
    _run(tm, "UPDATE SPIKE_L SET N = 0 WHERE EMPLOYEE_ID = 1")
    tm.commit()


def _final(base: fbd.Connection) -> tuple[list[str], Any]:
    tm = _begin(base, fbd.Isolation.SNAPSHOT)
    rows, lock_value = _rows(tm), _scalar(tm, LOCK_VALUE)
    tm.commit()
    return rows, lock_value


def _close_all(*items: Any) -> None:
    """Roll back any still-open transaction, then close the attachment. Used in finally blocks."""
    for item in items:
        if isinstance(item, fbd.TransactionManager):
            with contextlib.suppress(Exception):
                if item.is_active():
                    item.rollback()
        elif isinstance(item, fbd.Connection):
            with contextlib.suppress(Exception):
                item.close()


def _control(base: fbd.Connection, path: str) -> dict[str, str]:
    """Serial writes, no concurrency: the trigger must reject an overlap, including an open end date."""
    _reset(base)
    out: dict[str, str] = {"case": "control: serial writes"}
    conn = _open(path)
    try:
        tm = _begin(conn, fbd.Isolation.SNAPSHOT)
        out["open-ended row A"] = _attempt(lambda: _run(tm, INSERT, ROW_SECOND))
        out["commit A"] = _attempt(tm.commit)

        tm = _begin(conn, fbd.Isolation.SNAPSHOT)
        out["overlapping row B"] = _attempt(lambda: _run(tm, INSERT, (3, "2027-01-01", "2027-02-01")))
        tm.rollback()

        tm = _begin(conn, fbd.Isolation.SNAPSHOT)
        out["row C before A"] = _attempt(lambda: _run(tm, INSERT, (4, "2025-01-01", "2025-12-31")))
        out["commit C"] = _attempt(tm.commit)
    finally:
        _close_all(conn)
    rows, lock_value = _final(base)
    out["rows"] = " | ".join(rows)
    out["lock N"] = str(lock_value)
    return out


def _case_insert_only(base: fbd.Connection, path: str, isolation: fbd.Isolation, commit_first: bool) -> dict[str, str]:
    """Case (a): trigger only, no lock row.

    commit_first=False: both transactions insert before either commits.
    commit_first=True: the second transaction starts before the first commits, and inserts after it.
    """
    _reset(base)
    name = (
        "a2: 2nd starts before 1st commits, inserts after" if commit_first else "a1: both insert before either commits"
    )
    out: dict[str, str] = {"case": f"(a) trigger only | {isolation.name} | {name}"}
    first, second = _open(path), _open(path)
    t1 = t2 = None
    try:
        t1 = _begin(first, isolation)
        t2 = _begin(second, isolation)
        out["1st insert"] = _attempt(lambda: _run(t1, INSERT, ROW_FIRST))
        if commit_first:
            out["1st commit"] = _attempt(t1.commit)
        out["2nd sees before insert (rows)"] = str(_scalar(t2, COUNT))
        out["2nd insert"] = _attempt(lambda: _run(t2, INSERT, ROW_SECOND))
        if not commit_first:
            out["1st commit"] = _attempt(t1.commit)
        out["2nd commit"] = _attempt(t2.commit)
    finally:
        _close_all(t1, t2, first, second)
    rows, lock_value = _final(base)
    out["rows"] = " | ".join(rows)
    out["lock N"] = str(lock_value)
    return out


def _case_lock_row(base: fbd.Connection, path: str, isolation: fbd.Isolation, mode: str) -> dict[str, str]:
    """Case (b): the same trigger, plus UPDATE of the employee's lock row as the first statement.

    The first writer holds the lock row, then inserts. The second writer runs in a thread so it
    can block; the first writer commits after the mode's hold time.
    """
    _reset(base)
    lock_timeout, hold = LOCK_MODES[mode]
    out: dict[str, str] = {"case": f"(b) trigger + lock row | {isolation.name} | {mode}"}
    first, second = _open(path), _open(path)
    t1 = t2 = None
    try:
        t1 = _begin(first, isolation)
        out["1st lock UPDATE"] = _attempt(lambda: _run(t1, UPDATE_LOCK))
        out["1st insert"] = _attempt(lambda: _run(t1, INSERT, ROW_FIRST))
        t2 = _begin(second, isolation, lock_timeout)
        result: dict[str, Any] = {}

        def second_writer() -> None:
            started = time.monotonic()
            result["2nd lock UPDATE"] = _attempt(lambda: _run(t2, UPDATE_LOCK))
            result["2nd lock UPDATE returned at"] = f"{time.monotonic() - t0:.2f} s after 2nd start"
            if result["2nd lock UPDATE"] == "ok":
                result["2nd sees before insert (rows)"] = str(_scalar(t2, COUNT))
                result["2nd insert"] = _attempt(lambda: _run(t2, INSERT, ROW_SECOND))
            if result["2nd lock UPDATE"] == "ok" and result.get("2nd insert") == "ok":
                result["2nd commit"] = _attempt(t2.commit)
            else:
                _close_all(t2)
                result["2nd commit"] = "rolled back"
            result["2nd seconds"] = f"{time.monotonic() - started:.2f}"

        t0 = time.monotonic()
        thread = threading.Thread(target=second_writer, daemon=True)
        thread.start()
        if mode == "nowait":
            thread.join(15)
        else:
            time.sleep(hold)
        out["1st commit"] = _attempt(t1.commit)
        out["1st commit at"] = f"{time.monotonic() - t0:.2f} s after 2nd start"
        thread.join(15)
        if thread.is_alive():
            out["2nd writer"] = "STILL BLOCKED after 15 s"
        out.update(result)
    finally:
        _close_all(t1, t2, first, second)
    rows, lock_value = _final(base)
    out["rows"] = " | ".join(rows)
    out["lock N"] = str(lock_value)
    return out


def _print_block(result: dict[str, str]) -> None:
    print()
    print(f"=== {result['case']}")
    for key, value in result.items():
        if key != "case":
            print(f"    {key}: {value}")


def test_two_writers_overlap_outcomes(fb_clone: str, fb_alias: str) -> None:
    # The wrapper sets the Firebird client library and dialect process-wide; the raw driver
    # connections below need those settings, so connect the wrapper once first.
    connections[fb_alias].ensure_connection()
    base = _open(fb_clone)
    results: list[dict[str, str]] = []
    try:
        _setup(base)
        control = _control(base, fb_clone)
        results.append(control)
        for isolation in (
            fbd.Isolation.SNAPSHOT,
            fbd.Isolation.READ_COMMITTED,
            fbd.Isolation.READ_COMMITTED_RECORD_VERSION,
        ):
            for commit_first in (False, True):
                results.append(_case_insert_only(base, fb_clone, isolation, commit_first))
            for mode in LOCK_MODES:
                results.append(_case_lock_row(base, fb_clone, isolation, mode))
    finally:
        _close_all(base)

    for result in results:
        _print_block(result)

    assert control["overlapping row B"].startswith(f"ERROR {OVERLAP}")
    assert control["row C before A"] == "ok"
    assert len(results) == 1 + 3 * (2 + len(LOCK_MODES))
