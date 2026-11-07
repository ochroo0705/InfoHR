"""history.hire() on Firebird: the hire lock comes from employees.named_lock (plan 4, Task 2).

Each scenario runs in a subprocess on the migrated clone (``migrated_clone``) and reports a JSON result. The
two-writer scenario runs writer B in a thread (its own Django connection, so its own Firebird attachment) while
writer A's hire is still uncommitted; A holds the HIRE lock until its transaction ends.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

PRELUDE = """
import json
import threading
import uuid
import datetime as dt
from decimal import Decimal
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from employees import history_range
from employees.models import ContractType, Employee, EmployeeType, JobRecord, JobStatus, SalaryRecord
from employees.services import history, macs_writes
from employees.services.history import HistoryError
from macs.models import Branch, Department, Position

User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"hirelock_{tag}", password="x-long-pass-123")
dep = Department.objects.order_by("pk").values_list("pk", flat=True).first()
pos = Position.objects.order_by("pk").values_list("pk", flat=True).first()
br = Branch.objects.order_by("pk").values_list("pk", flat=True).first()
START = dt.date(2026, 1, 5)
BUSY = history_range.LOCK_BUSY_MESSAGE


def hire_values(label, n):
    return {
        "family_name": "Хайрлах",
        "given_name": f"Л{tag}{label}",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": f"УБ9009{n:04d}",
        "first_hire_date": START,
        "work_conditions": 1,
        "branch_id": br,
    }


def job():
    return {
        "department_id": dep,
        "position_id": pos,
        "employee_type": EmployeeType.FULL_TIME,
        "status": JobStatus.ACTIVE,
        "contract_type": ContractType.OPEN_ENDED,
    }


def hire(label, n):
    return history.hire(
        hire_values(label, n), {}, start=START, job=job(), salary=Decimal("1500000.00"), by=by
    )


def customer_count():
    with connection.cursor() as c:
        c.execute("select count(*) from customer")
        return c.fetchone()[0]


def customers_of(pk):
    with connection.cursor() as c:
        c.execute("select count(*) from customer where employee_ident = %s", [pk])
        return c.fetchone()[0]


def counts():
    return {
        "employees": Employee.objects.count(),
        "jobs": JobRecord.objects.count(),
        "salaries": SalaryRecord.objects.count(),
        "customers": customer_count(),
    }
"""

END_TO_END_CODE = (
    PRELUDE
    + """
expected_code = macs_writes.next_code()
emp = hire("e", 1)
fresh = Employee.objects.get(pk=emp.pk)
jobs = list(JobRecord.objects.filter(employee_id=emp.pk).values_list("change_type", "department_id", "position_id"))
salaries = list(SalaryRecord.objects.filter(employee_id=emp.pk).values_list("base_salary", "change_type"))
customers = customers_of(emp.pk)
print("RESULT " + json.dumps({
    "pk": emp.pk,
    "expected_code": expected_code,
    "code": fresh.code,
    "family_name": fresh.family_name,
    "jobs": [[str(a), b, c_] for a, b, c_ in jobs],
    "dep": dep,
    "pos": pos,
    "salaries": [[str(a), b] for a, b in salaries],
    "customers": customers,
}))
"""
)

TWO_WRITERS_CODE = (
    PRELUDE
    + """
out = {}
with transaction.atomic():
    # Writer A hires and keeps its transaction open, so it still holds the HIRE lock.
    a = hire("a", 2)
    out["a_code"] = a.code
    out["a_pk"] = a.pk
    before = counts()

    def attempt_b():
        try:
            hire("b", 3)
            out["b"] = "ok"
        except HistoryError as exc:
            out["b"] = "busy" if str(exc) == BUSY else f"other:{exc}"
        except Exception as exc:
            out["b"] = f"unexpected:{type(exc).__name__}: {exc}"
        finally:
            connection.close()

    thread = threading.Thread(target=attempt_b)
    thread.start()
    thread.join(30)
    out["b_finished"] = not thread.is_alive()
    out["counts_before_b"] = before
    out["counts_after_b"] = counts()
# Writer A has committed. Writer B retries the same hire in a new transaction: it must now succeed, and take the
# number after A's. That shows B's earlier refusal was a transient lock refusal, not another database error.
retry = hire("b", 3)
out["b_retry_code"] = retry.code
print("RESULT " + json.dumps(out))
"""
)


@pytest.fixture(scope="module")
def end_to_end(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(END_TO_END_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


@pytest.fixture(scope="module")
def two_writers(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(TWO_WRITERS_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_hire_runs_end_to_end_on_firebird(end_to_end: dict[str, Any]) -> None:
    assert end_to_end["code"] == end_to_end["expected_code"]
    assert end_to_end["code"].startswith("E") and end_to_end["code"][1:].isdigit()
    assert end_to_end["family_name"] == "Хайрлах"
    assert end_to_end["jobs"] == [["hire", end_to_end["dep"], end_to_end["pos"]]]
    assert end_to_end["salaries"] == [["1500000.00", "hire"]]
    assert end_to_end["customers"] == 1


def test_two_hires_at_once_do_not_share_a_code(two_writers: dict[str, Any]) -> None:
    # B was refused with the lock-busy message while A held the lock. Its retry after A's commit succeeds and takes
    # the next number, so the refusal was the transient lock and not some other database error.
    assert two_writers["b_finished"] is True, two_writers
    assert two_writers["b"] == "busy", two_writers
    a_number = int(two_writers["a_code"][1:])
    assert two_writers["b_retry_code"] == f"E{a_number + 1:04d}", two_writers


def test_a_refused_hire_writes_nothing(two_writers: dict[str, Any]) -> None:
    assert two_writers["counts_after_b"] == two_writers["counts_before_b"], two_writers
