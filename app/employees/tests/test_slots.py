"""Position slots (орон тоо): the slot service, the switch and the permissions (position-slots plan, Task 1)."""

import importlib
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import SystemLogEntry, User
from django.apps import apps
from django.contrib.auth.models import Group, Permission
from macs.models import Branch, NazgRow, Position

from employees import slot_kind
from employees.models import CompanySettings, Employee
from employees.services import history, slots

from .conftest import hire_values

pytestmark = pytest.mark.django_db

DAY = date(2026, 6, 1)


@pytest.fixture
def position(job_values: dict[str, Any]) -> Position:
    return job_values["position"]  # type: ignore[no-any-return]


@pytest.fixture
def branch() -> Branch:
    return Branch.objects.create(name="Төв салбар")


def _switch(on: bool = True) -> None:
    row = CompanySettings.get()
    row.enforce_position_slots = on
    row.save()


def _row(position: Position, branch: Branch | None, qty: int, *, kind: str = "Main", year: int = 2026) -> NazgRow:
    return NazgRow.objects.create(kind=kind, qty=qty, year=year, position=position, branch=branch)  # type: ignore[misc]  # a branchless row cannot exist in production (NOT NULL)


def _hire(
    actor: User,
    job_values: dict[str, Any],
    branch: Branch | None,
    *,
    start: date = DAY,
    contract: bool = False,
    n: int = 0,
    status: str = "active",
) -> Employee:
    values = {**hire_values(f"УБ9911{n:04d}"), "branch": branch}
    # The contract flag follows the job's emptype (5 = contract), as everywhere in the hire path.
    job = {**job_values, "status": status, **({"emptype": 5} if contract else {})}
    return history.hire(values, {}, start=start, job=job, salary=Decimal("1"), by=actor)


def _gate(position: Position, branch: Branch | None, actor: User, *, reason: str = "", contract: bool = False) -> None:
    slots.gate(
        position=position,
        branch=branch,
        contract_flag="yes" if contract else "no",
        on=DAY,
        override_reason=reason,
        by=actor,
        employee_label="Бат",
    )


def test_kind_rule_is_shared() -> None:
    assert slots.kind_for("yes") == "Temporary" and slots.kind_for("no") == "Main" and slots.kind_for(None) == "Main"
    assert slot_kind.kind_for("yes") == "Temporary"
    assert slot_kind.kind_of(Employee(contract_flag="yes")) == "Temporary"
    assert slot_kind.kind_of(Employee(contract_flag="no")) == "Main"


def test_switch_defaults_off_and_gate_is_a_noop(position: Position, branch: Branch, actor: User) -> None:
    assert CompanySettings.get().enforce_position_slots is False
    _gate(position, branch, actor)  # no row, switch off: nothing happens
    slots.gate(position=None, branch=None, contract_flag="no", on=DAY, override_reason="", by=actor)


def test_switch_on_without_a_row_refuses(position: Position, branch: Branch, actor: User) -> None:
    _switch()
    with pytest.raises(slots.SlotBlocked) as blocked:
        _gate(position, branch, actor)
    message = blocked.value.message
    for part in (position.name, branch.name, "2026", "0"):
        assert part in message


def test_no_posts_message_names_the_kind_that_is_missing(position: Position, branch: Branch, actor: User) -> None:
    """Only main posts planned, a temporary hire: the message says the temporary kind has no post, not a generic gap."""
    _switch()
    _row(position, branch, 2, kind=slot_kind.MAIN)
    with pytest.raises(slots.SlotBlocked) as blocked:
        _gate(position, branch, actor, contract=True)
    message = blocked.value.message
    assert "Түр" in message and "төлөвлөөгүй" in message and "Орон тооны төлөвлөгөө» хэсэгт" in message
    assert "Үндсэн" not in message


def test_message_when_no_posts_are_planned(position: Position, branch: Branch, actor: User) -> None:
    _switch()  # no row at all: the post was never planned, so the message says so and points to the field
    with pytest.raises(slots.SlotBlocked) as blocked:
        _gate(position, branch, actor)
    message = blocked.value.message
    assert "төлөвлөөгүй" in message and "Орон тооны төлөвлөгөө» хэсэгт" in message
    assert "дүүрсэн" not in message


def test_message_when_the_posts_are_full(
    position: Position, branch: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    _switch()
    _row(position, branch, 1)
    _hire(actor, job_values, branch, n=2)  # the one planned post is taken
    with pytest.raises(slots.SlotBlocked) as blocked:
        _gate(position, branch, actor)
    message = blocked.value.message
    assert "дүүрсэн" in message and "төлөвлөөгүй" not in message


def test_gate_with_no_position_is_a_noop_when_on(actor: User) -> None:
    _switch()
    slots.gate(position=None, branch=None, contract_flag="no", on=DAY, override_reason="", by=actor)


def test_one_post_allows_the_first_and_refuses_the_second(
    position: Position, branch: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    _switch()
    _row(position, branch, 1)
    _gate(position, branch, actor)
    _hire(actor, job_values, branch, n=1)
    result = slots.check(position, branch, kind="Main", on=DAY)
    assert result == slots.SlotResult(kind="Main", year=2026, posts=1, used=1, free=0)
    with pytest.raises(slots.SlotBlocked):
        _gate(position, branch, actor)


def test_posts_come_from_the_row(position: Position, branch: Branch) -> None:
    # `nazg` has a unique key (kind, year, branch, position), so there is one row per slot; posts are its qty
    # (the service still sums, as report A9 does).
    _row(position, branch, 3)
    assert slots.check(position, branch, kind="Main", on=DAY).posts == 3


def test_contract_hire_counts_temporary_rows_only(position: Position, branch: Branch, actor: User) -> None:
    _switch()
    _row(position, branch, 5, kind="Main")
    with pytest.raises(slots.SlotBlocked):
        _gate(position, branch, actor, contract=True)  # only a Main row exists
    _row(position, branch, 1, kind="Temporary")
    _gate(position, branch, actor, contract=True)
    assert slots.check(position, branch, kind="Temporary", on=DAY).posts == 1


def test_contract_people_use_up_temporary_slots_not_main(
    position: Position, branch: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    _row(position, branch, 1, kind="Main")
    _row(position, branch, 1, kind="Temporary")
    _hire(actor, job_values, branch, contract=True, n=2)
    assert slots.check(position, branch, kind="Main", on=DAY).used == 0
    assert slots.check(position, branch, kind="Temporary", on=DAY).used == 1


def test_branch_none_matches_only_branchless_rows(position: Position, branch: Branch) -> None:
    # Production `nazg.branch_ident` is NOT NULL, so no branchless row can exist: a branchless hire has zero posts.
    _row(position, branch, 4)
    assert slots.check(position, None, kind="Main", on=DAY).posts == 0
    assert slots.check(position, branch, kind="Main", on=DAY).posts == 4


def test_other_branch_people_do_not_count(
    position: Position, branch: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    other = Branch.objects.create(name="Хойд салбар")
    _row(position, branch, 1)
    _hire(actor, job_values, other, n=3)
    assert slots.check(position, branch, kind="Main", on=DAY).used == 0


def test_year_comes_from_the_start_date(position: Position, branch: Branch) -> None:
    _row(position, branch, 3, year=2027)
    assert slots.check(position, branch, kind="Main", on=DAY).posts == 0
    assert slots.check(position, branch, kind="Main", on=date(2027, 2, 1)).posts == 3


def test_future_start_hire_in_the_same_year_counts(
    position: Position, branch: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    _switch()
    _row(position, branch, 1)
    _hire(actor, job_values, branch, start=date(2026, 9, 1), n=4)  # starts after DAY, same year
    assert slots.check(position, branch, kind="Main", on=DAY).used == 1
    with pytest.raises(slots.SlotBlocked):
        _gate(position, branch, actor)


def test_a_hire_starting_next_year_does_not_count(
    position: Position, branch: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    _row(position, branch, 1)
    _hire(actor, job_values, branch, start=date(2027, 1, 10), n=5)
    assert slots.check(position, branch, kind="Main", on=DAY).used == 0


def test_a_person_who_left_does_not_count(
    position: Position, branch: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    _row(position, branch, 1)
    _hire(actor, job_values, branch, status="left", n=6)
    assert slots.check(position, branch, kind="Main", on=DAY).used == 0


def test_exclude_employee_leaves_that_person_out(
    position: Position, branch: Branch, actor: User, job_values: dict[str, Any]
) -> None:
    _row(position, branch, 1)
    employee = _hire(actor, job_values, branch, n=7)
    assert slots.check(position, branch, kind="Main", on=DAY).used == 1
    assert slots.check(position, branch, kind="Main", on=DAY, exclude_employee=employee).used == 0


def test_override_needs_reason_and_right_and_is_logged(position: Position, branch: Branch, actor: User) -> None:
    _switch()
    admin = User.objects.create_user("slot_admin", password="x-long-pass-123")  # noqa: S106
    admin.user_permissions.add(Permission.objects.get(codename="override_position_slots"))
    admin = User.objects.get(pk=admin.pk)

    with pytest.raises(slots.SlotBlocked):
        _gate(position, branch, admin, reason="   ")  # right but no reason
    with pytest.raises(slots.SlotBlocked):
        _gate(position, branch, actor, reason="Яаралтай")  # reason but no right
    assert not SystemLogEntry.objects.filter(action="position_slot_overridden").exists()

    _gate(position, branch, admin, reason="Яаралтай")
    entry = SystemLogEntry.objects.get(action="position_slot_overridden")
    assert "Яаралтай" in entry.message and entry.category == "hr"


def test_override_not_needed_when_a_slot_is_free(position: Position, branch: Branch, actor: User) -> None:
    _switch()
    _row(position, branch, 1)
    _gate(position, branch, actor, reason="x")
    assert not SystemLogEntry.objects.filter(action="position_slot_overridden").exists()


def test_gate_locks_the_matching_rows(position: Position, branch: Branch, actor: User) -> None:
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from macs import dialect

    _switch()
    _row(position, branch, 2)
    with CaptureQueriesContext(connection) as queries:
        _gate(position, branch, actor)
    # The backend's own lock clause and table name: FOR UPDATE and "nazg" on PostgreSQL, WITH LOCK and NAZG on Firebird.
    table = connection.ops.quote_name(NazgRow._meta.db_table)
    assert any(dialect.lock_suffix().strip() in q["sql"] and table in q["sql"] for q in queries)


def test_permissions_are_declared_and_defaulted() -> None:
    codes = set(Permission.objects.filter(content_type__app_label="employees").values_list("codename", flat=True))
    assert {"manage_position_slots", "override_position_slots"} <= codes
    held = {
        name: set(
            Group.objects.get(name=name)
            .permissions.filter(codename__in=["manage_position_slots", "override_position_slots"])
            .values_list("codename", flat=True)
        )
        for name in (roles.ADMIN, roles.HR, roles.ACCOUNTANT, roles.EMPLOYEE, roles.AUDITOR)
    }
    assert held[roles.ADMIN] == {"manage_position_slots", "override_position_slots"}
    assert held[roles.HR] == {"manage_position_slots"}
    assert held[roles.ACCOUNTANT] == held[roles.EMPLOYEE] == held[roles.AUDITOR] == set()
    assert roles.DEFAULT_SLOT_PERMS[roles.ADMIN] == ("manage_position_slots", "override_position_slots")
    assert roles.DEFAULT_SLOT_PERMS[roles.HR] == ("manage_position_slots",)


def test_migration_is_tolerant_and_reversible() -> None:
    migration = importlib.import_module("employees.migrations.0022_position_slot_perms")
    Group.objects.filter(name=roles.HR).update(name="HR-renamed")  # a missing group must not crash
    migration.revoke(apps, None)
    assert not Group.objects.get(name=roles.ADMIN).permissions.filter(codename__endswith="position_slots").exists()
    migration.grant(apps, None)
    migration.grant(apps, None)  # idempotent
    assert Group.objects.get(name=roles.ADMIN).permissions.filter(codename__endswith="position_slots").count() == 2
