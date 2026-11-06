"""The Firebird seed functions reproduce the final state the PostgreSQL migrations leave behind.

These tests run on PostgreSQL: the test database already holds what the PostgreSQL data migrations
created. The seeds are then re-run after the seeded rows are deleted, and the result must equal the
original state (ids and ordering ignored).

The golden file app/infohr_firebird/tests/seed_golden.json is the snapshot of that PostgreSQL state.
test_golden_file_matches_postgres_state keeps it honest: it fails when the file drifts from PostgreSQL.
The Firebird side compares its own snapshot with the same file (app/infohr_firebird/tests/test_seed_firebird.py).
To rewrite the golden file after a deliberate change to the PostgreSQL history, run:

    REGEN_SEED_GOLDEN=1 .venv\\Scripts\\python.exe -m pytest app/config/test_seed_firebird.py -k regenerate -q
"""

import json
import os
from pathlib import Path

import pytest
from checklists.models import ChecklistTemplate
from django.apps import apps
from django.contrib.auth.models import Permission
from django.db.models import Q

from config.seed_firebird import OFFBOARDING_NAME, ONBOARDING_NAME, seed_all
from config.seed_snapshot import permission_scope, snapshot_state

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "infohr_firebird" / "tests" / "seed_golden.json"

# Every codename the seeds create, across the seeded apps and the macs.employee content type.
SEEDED_CODENAMES = [
    "approve_leave",
    "issue_orders",
    "export_lists",
    "view_audit",
    "manage_lists",
    "view_leave",
    "record_leave",
    "manage_leave_settings",
    "request_own_leave",
    "manage_recruitment",
    "view_reports",
    "manage_saved_views",
    "view_employees",
    "manage_employees",
    "view_personal",
    "view_salary",
    "manage_salary",
    "manage_position_slots",
    "override_position_slots",
    "manage_checklists",
    "override_offboarding",
    "view_helpquestion",
    "view_helpexample",
    "add_helpexample",
    "change_helpexample",
    "view_assistantsettings",
    "change_assistantsettings",
]


def _forget_seeded_rows() -> None:
    from leave.models import AnnualLeaveRule

    Permission.objects.filter(permission_scope() & Q(codename__in=SEEDED_CODENAMES)).delete()
    AnnualLeaveRule.objects.all().delete()
    ChecklistTemplate.objects.filter(is_default=True, name__in=[OFFBOARDING_NAME, ONBOARDING_NAME]).delete()


def _run_seeds() -> None:
    seed_all(apps)


def _state_after_reseed() -> dict:
    _forget_seeded_rows()
    _run_seeds()
    return snapshot_state()


@pytest.mark.django_db
def test_seed_reproduces_the_postgres_migration_state() -> None:
    before = snapshot_state()
    _forget_seeded_rows()
    assert snapshot_state() != before, "deleting the seeded rows must change the state"
    _run_seeds()
    assert snapshot_state() == before


@pytest.mark.django_db
def test_seed_is_idempotent() -> None:
    before = snapshot_state()
    _run_seeds()
    assert snapshot_state() == before
    _run_seeds()
    assert snapshot_state() == before


@pytest.mark.django_db
def test_employee_group_can_request_leave_but_not_see_salary() -> None:
    groups = _state_after_reseed()["groups"]
    assert "leave.request_own_leave" in groups["Employee"]
    assert "macs.view_salary" not in groups["Employee"]


@pytest.mark.django_db
def test_hr_group_cannot_view_salary() -> None:
    groups = _state_after_reseed()["groups"]
    assert "macs.view_salary" not in groups["HR"]
    assert "macs.view_employees" in groups["HR"]


@pytest.mark.django_db
def test_accountant_group_can_view_salary() -> None:
    groups = _state_after_reseed()["groups"]
    assert "macs.view_salary" in groups["Accountant"]
    assert "macs.manage_salary" in groups["Accountant"]


@pytest.mark.django_db
def test_golden_file_matches_postgres_state() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert snapshot_state() == golden


@pytest.mark.django_db
@pytest.mark.skipif(
    os.environ.get("REGEN_SEED_GOLDEN") != "1", reason="set REGEN_SEED_GOLDEN=1 to rewrite the golden file"
)
def test_regenerate_golden_file() -> None:
    """Rewrites seed_golden.json from the PostgreSQL test database (see the module docstring)."""
    text = json.dumps(snapshot_state(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with open(GOLDEN_PATH, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(text)
