"""MACS triggers that HR relies on must be present and active (plan 3, Task 4).

The triggers are read from RDB$TRIGGERS. The first test uses the module clone of the template, which has
every trigger. The deactivation test works on its own copy (fb_clone), so the shared clone stays intact.
Each check runs in a subprocess, the same way the settings seam tests do.
"""

from typing import Any

from infohr_firebird.tests.test_settings_seam import result_of, run_django

PRESENT_CODE = """
import json
import django
django.setup()
from macs.triggers import EXPECTED, missing, require
tables = sorted(EXPECTED)
require(*tables)
print("RESULT " + json.dumps({"missing": missing(*tables)}))
"""

# Requires MOVEMENT (cached for this process), deactivates MOVEMENT_AI0 on this process's own copy, then checks:
# - missing() reports it;
# - a require() of the same table set is still silent (the positive result is cached for the process);
# - a require() of a different table set is not cached and raises, naming the trigger.
DEACTIVATE_CODE = """
import json
import django
django.setup()
from django.db import connection
from macs.triggers import MacsTriggerMissing, missing, require
require("MOVEMENT")
with connection.cursor() as cursor:
    cursor.execute("ALTER TRIGGER MOVEMENT_AI0 INACTIVE")
cached_silent = True
try:
    require("MOVEMENT")
except MacsTriggerMissing:
    cached_silent = False
raised = False
message = ""
try:
    require("MOVEMENT", "EMPLOYEE")
except MacsTriggerMissing as error:
    raised = True
    message = str(error)
print("RESULT " + json.dumps({
    "missing": missing("MOVEMENT"),
    "cached_silent": cached_silent,
    "raised": raised,
    "message": message,
}))
"""

# Run after DEACTIVATE_CODE on the same copy: the inactive trigger is still inactive in a new process.
AFTER_RESTART_CODE = """
import json
import django
django.setup()
from macs.triggers import MacsTriggerMissing, missing, require
raised = False
try:
    require("MOVEMENT")
except MacsTriggerMissing:
    raised = True
print("RESULT " + json.dumps({"missing": missing("MOVEMENT"), "raised": raised}))
"""

# Requires EMPLOYEE_HISTORY on a copy whose EMPLOYEE_HISTORY_BD0 is inactive from the start (R9d: no test covered it).
HISTORY_CODE = """
import json
import django
django.setup()
from django.db import connection
from macs.triggers import MacsTriggerMissing, require
with connection.cursor() as cursor:
    cursor.execute("ALTER TRIGGER EMPLOYEE_HISTORY_BD0 INACTIVE")
raised = False
message = ""
try:
    require("EMPLOYEE_HISTORY")
except MacsTriggerMissing as error:
    raised = True
    message = str(error)
print("RESULT " + json.dumps({"raised": raised, "message": message}))
"""

# Requires MOVEMENT at clock 1000, deactivates MOVEMENT_AI0, then steps a fake time.monotonic clock:
# - still inside RECHECK_SECONDS the cached positive result applies, so require() stays silent;
# - after RECHECK_SECONDS the triggers are checked again and require() raises, naming the trigger.
RECHECK_CODE = """
import json
import time
import django
django.setup()
from django.db import connection
from macs.triggers import MacsTriggerMissing, RECHECK_SECONDS, require
clock = [1000.0]
time.monotonic = lambda: clock[0]
require("MOVEMENT")
with connection.cursor() as cursor:
    cursor.execute("ALTER TRIGGER MOVEMENT_AI0 INACTIVE")
within_window_raised = False
try:
    require("MOVEMENT")
except MacsTriggerMissing:
    within_window_raised = True
clock[0] += RECHECK_SECONDS + 1
raised = False
message = ""
try:
    require("MOVEMENT")
except MacsTriggerMissing as error:
    raised = True
    message = str(error)
print("RESULT " + json.dumps({"within_window_raised": within_window_raised, "raised": raised, "message": message}))
"""

E011_CODE = """
import json
import django
django.setup()
from django.core.checks import run_checks
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from io import StringIO
issues = run_checks(databases=["default"])
found = [i for i in issues if i.id == "infohr_firebird.E011"]
raised = False
try:
    call_command("check", databases=["default"], stdout=StringIO(), stderr=StringIO())
except SystemCheckError:
    raised = True
print("RESULT " + json.dumps({
    "ids": sorted({i.id for i in issues if i.id}),
    "messages": [i.msg for i in found],
    "raised": raised,
}))
"""


def test_every_expected_trigger_is_active_on_the_clone(migrated_clone: str) -> None:
    data = result_of(run_django(PRESENT_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert data["missing"] == []


def test_deactivated_trigger_is_reported_and_require_refuses(fb_clone: str) -> None:
    first = result_of(run_django(DEACTIVATE_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=fb_clone))
    assert first["missing"] == ["MOVEMENT_AI0"]
    assert first["cached_silent"] is True
    assert first["raised"] is True
    assert "MOVEMENT_AI0" in first["message"]

    again = result_of(run_django(AFTER_RESTART_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=fb_clone))
    assert again == {"missing": ["MOVEMENT_AI0"], "raised": True}


def test_require_refuses_when_employee_history_bd0_is_inactive(fb_clone: str) -> None:
    data = result_of(run_django(HISTORY_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=fb_clone))
    assert data["raised"] is True
    assert "EMPLOYEE_HISTORY_BD0" in data["message"]


def test_a_trigger_switched_off_after_the_first_write_is_noticed(fb_clone: str) -> None:
    data = result_of(run_django(RECHECK_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=fb_clone))
    assert data["within_window_raised"] is False
    assert data["raised"] is True
    assert "MOVEMENT_AI0" in data["message"]


def test_system_check_e011_is_silent_when_triggers_are_present(migrated_clone: str) -> None:
    data = result_of(run_django(E011_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert "infohr_firebird.E011" not in data["ids"]
    assert data["raised"] is False


def test_system_check_e011_reports_a_deactivated_trigger(fb_clone: str) -> None:
    deactivate = run_django(DEACTIVATE_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=fb_clone)
    assert result_of(deactivate)["missing"] == ["MOVEMENT_AI0"]
    data: dict[str, Any] = result_of(run_django(E011_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=fb_clone))
    assert "infohr_firebird.E011" in data["ids"]
    assert data["raised"] is True
    assert any("MOVEMENT_AI0" in message for message in data["messages"])
