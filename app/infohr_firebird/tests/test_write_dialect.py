"""SQL that differs by database, run on Firebird (plan 3, Task 9).

Covers the generator (snapshot_history), the E-number (next_code), the talent list (personal_writes, WITH LOCK),
the annual leave total (leave.services.writes.sync_vacation, ORDER BY + WITH LOCK) and the ERP customer row
(create_customer_row, INSERT ... RETURNING). Each scenario runs the real function in a subprocess on the migrated
clone and reports JSON; the tests assert on it.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

DIALECT_CODE = """
import json
import uuid
import datetime as dt
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone
from employees.models import Employee
from employees.services import macs_writes, personal_writes
from leave.models import LeaveTypeExt
from leave.services import writes as leave_writes
from macs.dialect import next_value
from macs.models import EmployeeHistory, LeaveAssign, LeaveTypeRow, TalentKind

User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"dialect_{tag}", password="x-long-pass-123")
TODAY = timezone.localdate()

def register(n):
    return "УБ" + f"{abs(hash((tag, n))) % 10**8:08d}"

def values(n, given="Бат", family="Пробный"):
    return {
        "family_name": family,
        "given_name": given,
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": register(n),
        "first_hire_date": TODAY,
        "work_conditions": 1,
    }

def gen_now():
    with connection.cursor() as c:
        c.execute("SELECT GEN_ID(GEN_EMPLOYEE_HISTORY_ID, 0) FROM rdb$database")
        return int(c.fetchone()[0])

def vacation_rows(pk):
    with connection.cursor() as c:
        c.execute(
            "SELECT myear, mmonth, v_day, is_vacation, start_date, end_date FROM emp_vacation WHERE emp_ident = %s",
            [pk],
        )
        return [[str(v) for v in r] for r in c.fetchall()]

out = {}

# A. snapshot_history: id from the generator, row written with that id, generator advanced by exactly 1.
e_hist = macs_writes.create_employee(values(1), {}, code=f"T9H{tag}", by=by)
before = gen_now()
hid = macs_writes.snapshot_history(e_hist, TODAY)
after = gen_now()
row = EmployeeHistory.objects.filter(pk=hid).values("id", "employee_id_value").first()
out["history"] = {
    "returned": hid,
    "row_id": row["id"] if row else None,
    "row_employee": row["employee_id_value"] if row else None,
    "employee_pk": e_hist.pk,
    "gen_before": before,
    "gen_after": after,
    "next_value_is_int": isinstance(next_value("gen_employee_history_id"), int),
}

# B. next_code: E0099, E9999, E10000 and junk codes present; the next code is E10001.
for n, code in enumerate(("E0099", "E9999", "E10000", "E12A", "EX", "E123"), start=10):
    macs_writes.create_employee(values(n, given="Код", family=code), {}, code=code, by=by)
out["next_code"] = macs_writes.next_code()

# C. talent list: insert, select for update, update, delete through personal_writes.
e_tal = macs_writes.create_employee(values(2, given="Тал", family="Нэр"), {}, code=f"T9T{tag}", by=by)
talent = TalentKind.objects.order_by("pk").first() or TalentKind.objects.create(name="T9 talent")
tid = personal_writes.add(
    "talent", e_tal, {"talent_ident": talent.pk, "trained_year": 2020, "description": "first"}, {}, by
)
loaded = personal_writes.load("talent", e_tal, tid)
with transaction.atomic():
    locked = personal_writes._talent_row(e_tal, tid, lock=True)
personal_writes.update("talent", e_tal, tid, loaded, {"description": "second"}, {}, by)
updated = personal_writes.load("talent", e_tal, tid)
personal_writes.delete("talent", e_tal, tid, updated, by)
out["talent"] = {
    "returned": tid,
    "talent_pk": talent.pk,
    "loaded": loaded,
    "locked": list(locked) if locked else None,
    "updated": updated,
    "after_delete": personal_writes.load("talent", e_tal, tid),
    "rows_after_delete": personal_writes._talent_row(e_tal, tid, lock=False),
}

# D. annual leave: two assigns in one year give one emp_vacation total row (ORDER BY ... WITH LOCK).
annual = LeaveTypeRow.objects.create(name=f"T9 annual {tag}")
LeaveTypeExt.objects.create(leave_type=annual, uses_annual_balance=True, is_paid=True)
e_leave = macs_writes.create_employee(values(3, given="Чөлөө", family="Авлага"), {}, code=f"T9L{tag}", by=by)
leave_writes.record_assign(e_leave, annual, dt.date(2031, 2, 17), dt.date(2031, 2, 19), 3, "t9", by)
after_first = vacation_rows(e_leave.pk)
leave_writes.record_assign(e_leave, annual, dt.date(2031, 7, 13), dt.date(2031, 7, 17), 5, "t9", by)
out["leave"] = {
    "assigns": LeaveAssign.objects.filter(employee_id=e_leave.pk).count(),
    "after_first": after_first,
    "after_second": vacation_rows(e_leave.pk),
}

# E. ERP customer row: create_customer_row returns the new cust_id; a second call returns None.
e_cust = macs_writes.create_employee(values(4, given=f"Харилцагч{tag[:3]}", family="Тест"), {}, code=f"T9C{tag}", by=by)
with connection.cursor() as c:
    c.execute("DELETE FROM customer WHERE employee_ident = %s AND employee = 'yes'", [e_cust.pk])
cust_id = macs_writes.create_customer_row(e_cust)
with connection.cursor() as c:
    c.execute("SELECT cust_id, TRIM(description), employee_ident FROM customer WHERE cust_id = %s", [cust_id])
    stored = c.fetchone()
out["customer"] = {
    "returned": cust_id,
    "stored": list(stored) if stored else None,
    "employee_pk": e_cust.pk,
    "second_call": macs_writes.create_customer_row(e_cust),
}

print("RESULT " + json.dumps(out, default=str))
"""


@pytest.fixture(scope="module")
def dialect(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(DIALECT_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_snapshot_history_returns_id_of_the_row_and_advances_generator_once(dialect: dict[str, Any]) -> None:
    h = dialect["history"]
    assert isinstance(h["returned"], int) and h["returned"] > 0
    assert h["row_id"] == h["returned"]
    assert h["row_employee"] == h["employee_pk"]
    assert h["gen_after"] - h["gen_before"] == 1
    assert h["next_value_is_int"] is True


def test_next_code_follows_9999_and_ignores_junk_codes(dialect: dict[str, Any]) -> None:
    assert dialect["next_code"] == "E10001"


def test_talent_insert_lock_update_delete(dialect: dict[str, Any]) -> None:
    t = dialect["talent"]
    assert t["returned"] == t["talent_pk"]
    assert t["loaded"] == {"talent_ident": t["talent_pk"], "trained_year": 2020, "description": "first"}
    assert t["locked"] is not None and t["locked"][0] == t["talent_pk"]
    assert t["updated"]["description"] == "second"
    assert t["after_delete"] is None
    assert t["rows_after_delete"] is None


def test_leave_writes_recompute_one_vacation_total_row(dialect: dict[str, Any]) -> None:
    leave = dialect["leave"]
    assert leave["assigns"] == 2
    assert len(leave["after_first"]) == 1
    year, month, days, is_vacation, start, end = leave["after_first"][0]
    assert (year, month, days, is_vacation) == ("2031", "2", "3", "yes")
    assert (start[:10], end[:10]) == ("2031-02-17", "2031-02-19")  # Firebird TIMESTAMP: date and 00:00:00
    # The second leave adds to the same row: one row, total 8 days, earliest start, latest end.
    assert len(leave["after_second"]) == 1
    year, month, days, is_vacation, start, end = leave["after_second"][0]
    assert (year, month, days, is_vacation) == ("2031", "2", "8", "yes")
    assert (start[:10], end[:10]) == ("2031-02-17", "2031-07-17")


def test_create_customer_row_returns_new_cust_id(dialect: dict[str, Any]) -> None:
    c = dialect["customer"]
    assert isinstance(c["returned"], int) and c["returned"] > 0
    assert c["stored"][0] == c["returned"]
    assert c["stored"][2] == c["employee_pk"]
    assert c["second_call"] is None
