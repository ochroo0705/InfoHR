"""Firebird side of named_lock.take: two writers on one migrated clone (plan 4, Task 1).

Each test runs its two-writer code in a subprocess in Firebird mode against the module clone (``migrated_clone``).
Inside that process, writer A is the main thread and writer B runs in a thread, so each has its own Django
connection and therefore its own Firebird attachment. Nothing here touches the template.
"""

from typing import Any

from infohr_firebird.tests.test_settings_seam import result_of, run_django

# Shared prelude: a writer's attempt runs in its own thread and reports its outcome in a dict.
PRELUDE = """
import json
import threading
import time
import django
django.setup()
from django.db import connection, transaction
from employees.models import HistoryLock
from employees.named_lock import Lock, LockBusy, take


def attempt(lock, out, key):
    started = time.monotonic()
    try:
        with transaction.atomic():
            take(lock)
        out[key] = "ok"
    except LockBusy:
        out[key] = "busy"
    except Exception as exc:
        out[key] = f"unexpected:{type(exc).__name__}: {exc}"
    finally:
        out[key + "_seconds"] = round(time.monotonic() - started, 2)
        connection.close()
"""

REFUSED_CODE = (
    PRELUDE
    + """
out = {}
# Writer A takes the HIRE lock and keeps its transaction open.
held = transaction.atomic()
held.__enter__()
take(Lock.HIRE)
# Writer B, in another thread, must be refused.
thread = threading.Thread(target=attempt, args=(Lock.HIRE, out, "b_while_held"))
thread.start()
thread.join(8)
out["b_thread_finished"] = not thread.is_alive()
held.__exit__(None, None, None)  # A commits
# Writer B again, now that A has ended its transaction.
attempt(Lock.HIRE, out, "b_after_commit")
# Outside a transaction the lock would be released at once, so take must refuse.
try:
    take(Lock.HIRE)
    out["outside_transaction"] = "no error"
except RuntimeError:
    out["outside_transaction"] = "RuntimeError"
print("RESULT " + json.dumps(out))
"""
)

DIFFERENT_LOCKS_CODE = (
    PRELUDE
    + """
out = {}
held = transaction.atomic()
held.__enter__()
take(Lock.HIRE)
thread = threading.Thread(target=attempt, args=(Lock.ORDER_NUMBER, out, "b_other_lock"))
thread.start()
thread.join(8)
out["b_thread_finished"] = not thread.is_alive()
held.__exit__(None, None, None)
print("RESULT " + json.dumps(out))
"""
)

FIRST_USE_RACE_CODE = (
    PRELUDE
    + """
# No lock row yet: the two writers race to create it.
HistoryLock.objects.filter(employee_id=-1).delete()
out = {}
barrier = threading.Barrier(2)
release = threading.Event()


def race_writer(key):
    started = time.monotonic()
    try:
        with transaction.atomic():
            barrier.wait()
            try:
                take(Lock.HIRE)
                out[key] = "ok"
            except LockBusy:
                out[key] = "busy"
            # The winner keeps its lock until the loser has been answered.
            release.wait(15)
    except Exception as exc:
        out[key] = f"unexpected:{type(exc).__name__}: {exc}"
    finally:
        out[key + "_seconds"] = round(time.monotonic() - started, 2)
        connection.close()


threads = [threading.Thread(target=race_writer, args=(key,)) for key in ("writer_a", "writer_b")]
for thread in threads:
    thread.start()
deadline = time.monotonic() + 20
while time.monotonic() < deadline and not all(k in out for k in ("writer_a", "writer_b")):
    time.sleep(0.05)
release.set()
for thread in threads:
    thread.join(10)
print("RESULT " + json.dumps(out))
"""
)


def _firebird(migrated_clone: str, code: str) -> dict[str, Any]:
    return result_of(run_django(code, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_second_writer_is_refused_while_the_first_holds_the_lock(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, REFUSED_CODE)
    assert data["b_while_held"] == "busy", data
    assert float(data["b_while_held_seconds"]) < 8, data
    assert data["b_thread_finished"] is True, data
    assert data["b_after_commit"] == "ok", data
    assert data["outside_transaction"] == "RuntimeError", data


def test_different_locks_do_not_block_each_other(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, DIFFERENT_LOCKS_CODE)
    assert data["b_other_lock"] == "ok", data
    assert data["b_thread_finished"] is True, data


def test_first_ever_use_race_is_refused_not_blocked(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, FIRST_USE_RACE_CODE)
    outcomes = {key: data[key] for key in ("writer_a", "writer_b")}
    assert sorted(outcomes.values()) == ["busy", "ok"], data
    # The loser must be refused within the 3 s Firebird lock timeout (8 s allows for margin), not wait out the
    # winner's hold (15 s in the script).
    loser = next(key for key, value in outcomes.items() if value == "busy")
    assert float(data[loser + "_seconds"]) < 8, data
