"""Order registration on Firebird: the order-number lock comes from employees.named_lock (plan 4, Task 3).

Each scenario runs in a subprocess on the migrated clone (``migrated_clone``) and reports a JSON result. The
two-writer scenario runs writer B in a thread (its own Django connection, so its own Firebird attachment) while
writer A's number check is still uncommitted; A holds the ORDER_NUMBER lock until its transaction ends. Writer B
registers through the public path (orders.create_for_change), which reaches orders._validate.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

PRELUDE = """
import json
import threading
import uuid
import datetime as dt
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from employees import history_range
from employees.models import Employee, OrderType
from employees.services import orders
from employees.services.orders import OrderError

BUSY = history_range.LOCK_BUSY_MESSAGE
DATE = dt.date(2026, 3, 1)
by = get_user_model().objects.create_user(f"orderlock_{uuid.uuid4().hex[:6]}", password="x-long-pass-123")
emp = Employee.objects.order_by("pk").first()


def register_b(number):
    return orders.create_for_change(
        employee=emp, event=None, is_hire=True, order_type=OrderType.HIRED,
        number=number, date=DATE, summary="Т10", issued_by="Т10", by=by,
    )
"""

TWO_WRITERS_CODE = (
    PRELUDE
    + """
out = {}
assert emp is not None, "the migrated clone has no employee to register an order for"
with transaction.atomic():
    # Writer A checks its number and keeps its transaction open, so it still holds the ORDER_NUMBER lock.
    orders._validate("A-1", DATE, "", "", None)

    def attempt_b():
        try:
            register_b("B-1")
            out["b"] = "ok"
        except OrderError as exc:
            out["b"] = "busy" if exc.errors == {"number": BUSY} else f"other:{exc.errors}"
        except Exception as exc:
            out["b"] = f"unexpected:{type(exc).__name__}: {exc}"
        finally:
            connection.close()

    thread = threading.Thread(target=attempt_b)
    thread.start()
    thread.join(30)
    out["b_finished"] = not thread.is_alive()
# Writer A has committed. Writer B retries the same public registration: it must now pass, which shows its earlier
# refusal was the transient lock refusal and not some other database error.
register_b("B-1")
out["b_retry"] = "ok"
print("RESULT " + json.dumps(out))
"""
)


@pytest.fixture(scope="module")
def two_writers(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(TWO_WRITERS_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_second_registration_is_refused_while_the_first_is_open(two_writers: dict[str, Any]) -> None:
    assert two_writers["b_finished"] is True, two_writers
    assert two_writers["b"] == "busy", two_writers
    assert two_writers["b_retry"] == "ok", two_writers
