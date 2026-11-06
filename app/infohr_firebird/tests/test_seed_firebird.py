"""The seeds on Firebird reproduce the PostgreSQL final state (plan Task 8b).

The module fixture ``migrated_clone`` (conftest.py) migrates a copy of the template through every app, so the
seeds have already run once by migration. Each check runs Django in a subprocess in Firebird mode, like
test_migrations_fb.py, so the snapshot and the seeds go through the clone's own ORM connection.

The expected state is seed_golden.json, which config/test_seed_firebird.py writes from the PostgreSQL test
database (REGEN_SEED_GOLDEN=1) and checks against PostgreSQL on every run, so this file cannot drift.
"""

import json
from pathlib import Path

from infohr_firebird.tests.test_settings_seam import result_of, run_django

GOLDEN_PATH = Path(__file__).resolve().parent / "seed_golden.json"

SNAPSHOT_CODE = """
import json
import django
django.setup()
from config.seed_snapshot import snapshot_state
print("RESULT " + json.dumps(snapshot_state()))
"""

# The state before and after a second run of every seed; the clone already holds the first run.
SECOND_RUN_CODE = """
import json
import django
django.setup()
from django.apps import apps
from config.seed_firebird import seed_all
from config.seed_snapshot import snapshot_state
before = snapshot_state()
seed_all(apps)
after = snapshot_state()
print("RESULT " + json.dumps({"before": before, "after": after}))
"""

# A new user, added to the Employee role group through the ORM, must get that group's permissions.
NEW_USER_CODE = """
import json
import django
django.setup()
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
User = get_user_model()
user = User(username="seed_probe_user")
user.set_unusable_password()
user.save()
Group.objects.get(name="Employee").user_set.add(user)
fresh = User.objects.get(pk=user.pk)
print("RESULT " + json.dumps({
    "request_own_leave": fresh.has_perm("leave.request_own_leave"),
    "view_salary": fresh.has_perm("macs.view_salary"),
}))
"""


def _golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_clone_state_matches_the_golden_file(migrated_clone: str) -> None:
    data = result_of(run_django(SNAPSHOT_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert data == _golden()


def test_second_seed_run_changes_nothing(migrated_clone: str) -> None:
    data = result_of(run_django(SECOND_RUN_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert data["after"] == data["before"]
    assert data["after"] == _golden()


def test_new_user_gets_group_permissions(migrated_clone: str) -> None:
    data = result_of(run_django(NEW_USER_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert data["request_own_leave"] is True
    assert data["view_salary"] is False
