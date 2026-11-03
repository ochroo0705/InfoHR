"""Position slots in the hire form, the rehire event and the recruitment convert (position-slots plan, Task 2)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import SystemLogEntry, User
from django.test import Client
from macs.models import Branch, FiredReason, NazgRow, Position
from recruitment.models import Candidate, Stage
from recruitment.services import pipeline
from recruitment.tests.conftest import make_vacancy

from employees.models import CompanySettings, Employee
from employees.services import events, history
from employees.services.events import EventError

from .conftest import hire_values, named
from .helpers import record_signed
from .test_views import add_payload, login_as

pytestmark = pytest.mark.django_db

REGISTER = "УК88010122"
OVERRIDE = "position_slot_overridden"


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


def _row(position: Position, branch: Branch | None, qty: int, kind: str = "Main") -> NazgRow:
    return NazgRow.objects.create(kind=kind, qty=qty, year=2026, position=position, branch=branch)  # type: ignore[misc]


def _post(client: Client, job_values: dict[str, Any], branch: Branch | None, **extra: str) -> Any:
    if branch is not None:
        extra["branch"] = str(branch.pk)
    return client.post("/employees/new/", add_payload(job_values, **extra))


FIXED = {
    "emptype": "5",
    "contract_type": "fixed_term",
    "contract_no": "1",
    "contract_start": "2026-02-01",
    "contract_end": "2027-02-01",
}


def _exists() -> bool:
    return Employee.objects.filter(register_no=REGISTER).exists()


# --- hire form ---


def test_switch_off_hires_without_any_row(client: Client, job_values: dict[str, Any], branch: Branch) -> None:
    login_as(client, "HR")
    assert _post(client, job_values, branch).status_code == 302 and _exists()


def test_refused_without_a_slot_and_nothing_is_created(
    client: Client, job_values: dict[str, Any], branch: Branch
) -> None:
    _switch()
    login_as(client, "HR")
    response = _post(client, job_values, branch)
    assert response.status_code == 400 and not _exists()
    assert "төлөвлөөгүй" in response.content.decode()


def test_allowed_with_a_free_slot_then_the_next_is_refused(
    client: Client, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    _switch()
    _row(position, branch, 1)
    login_as(client, "HR")
    assert _post(client, job_values, branch).status_code == 302 and _exists()
    second = _post(client, job_values, branch, register_no="ук 88010123")
    assert second.status_code == 400 and not Employee.objects.filter(register_no="УК88010123").exists()


def test_contract_hire_needs_a_temporary_row(
    client: Client, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    _switch()
    _row(position, branch, 1)  # Main only
    login_as(client, "HR")
    assert _post(client, job_values, branch, **FIXED).status_code == 400
    _row(position, branch, 1, kind="Temporary")
    assert _post(client, job_values, branch, **FIXED).status_code == 302


def test_no_branch_is_refused_and_says_to_choose_one(
    client: Client, job_values: dict[str, Any], branch: Branch
) -> None:
    _switch()
    login_as(client, "HR")
    response = _post(client, job_values, None)
    assert response.status_code == 400 and not _exists()
    assert "салбар" in response.content.decode()


def test_admin_override_with_reason_hires_and_logs(client: Client, job_values: dict[str, Any], branch: Branch) -> None:
    _switch()
    login_as(client, "Admin")
    page = client.get("/employees/new/").content.decode()
    assert 'name="slot_override"' in page
    assert _post(client, job_values, branch, slot_override="Яаралтай").status_code == 302 and _exists()
    assert "Яаралтай" in SystemLogEntry.objects.get(action=OVERRIDE).message


def test_override_without_a_reason_is_refused(client: Client, job_values: dict[str, Any], branch: Branch) -> None:
    _switch()
    login_as(client, "Admin")
    assert _post(client, job_values, branch, slot_override="  ").status_code == 400 and not _exists()


def test_field_is_hidden_and_a_posted_value_ignored_without_the_right(
    client: Client, job_values: dict[str, Any], branch: Branch
) -> None:
    _switch()
    login_as(client, "HR")
    assert 'name="slot_override"' not in client.get("/employees/new/").content.decode()
    assert _post(client, job_values, branch, slot_override="Яаралтай").status_code == 400
    assert not _exists() and not SystemLogEntry.objects.filter(action=OVERRIDE).exists()


# --- rehire ---


def _left(actor: User, job_values: dict[str, Any], branch: Branch | None, register: str = "УБ77010101") -> Employee:
    employee = history.hire(
        {**hire_values(register), "branch": branch},
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("1"),
        by=actor,
    )
    record_signed(
        employee,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
        note="",
        by=actor,
    )
    return employee


def _rehire(employee: Employee, actor: User, position: Position, **kw: Any) -> Any:
    return events.record(
        employee,
        type="rehire",
        effective=date(2026, 5, 1),
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
        **kw,
    )


def test_rehire_switch_off_is_unchanged(
    actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    employee = _left(actor, job_values, branch)
    assert _rehire(employee, actor, position).type == "rehire"


def test_rehire_refused_without_a_slot(
    actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    employee = _left(actor, job_values, branch)
    _switch()
    with pytest.raises(EventError) as exc:
        _rehire(employee, actor, position)
    assert "төлөвлөөгүй" in exc.value.errors["__all__"]
    assert employee.events.filter(type="rehire").count() == 0


def test_rehire_allowed_with_a_free_slot(
    actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    employee = _left(actor, job_values, branch)
    _switch()
    _row(position, branch, 1)
    assert _rehire(employee, actor, position).type == "rehire"


def test_rehire_without_a_branch_is_refused(actor: User, job_values: dict[str, Any], position: Position) -> None:
    employee = _left(actor, job_values, None)
    _switch()
    with pytest.raises(EventError) as exc:
        _rehire(employee, actor, position)
    assert "салбар" in exc.value.errors["__all__"]


def test_rehire_override_by_right_holder_logs(
    actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    from django.contrib.auth.models import Permission

    employee = _left(actor, job_values, branch)
    _switch()
    actor.user_permissions.add(Permission.objects.get(codename="override_position_slots"))
    boss = User.objects.get(pk=actor.pk)
    assert _rehire(employee, boss, position, slot_override="Яаралтай").type == "rehire"
    assert "Яаралтай" in SystemLogEntry.objects.get(action=OVERRIDE).message


def test_rehire_form_field_follows_the_right(
    client: Client, actor: User, job_values: dict[str, Any], branch: Branch
) -> None:
    employee = _left(actor, job_values, branch)
    login_as(client, "HR", "hr_one")
    assert 'name="slot_override"' not in client.get(f"/employees/{employee.pk}/event/rehire/").content.decode()
    login_as(client, "Admin", "adm_one")
    assert 'name="slot_override"' in client.get(f"/employees/{employee.pk}/event/rehire/").content.decode()


def test_rehire_view_ignores_a_posted_override_without_the_right(
    client: Client, actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    employee = _left(actor, job_values, branch)
    _switch()
    login_as(client, "HR")
    data = {
        "effective": "2026-05-01",
        "position": str(position.pk),
        "department": str(job_values["department"].pk),
        "employee_type": "full_time",
        "contract_type": "open_ended",
        "slot_override": "Яаралтай",
    }
    response = client.post(f"/employees/{employee.pk}/event/rehire/", data)
    assert response.status_code == 200 and "төлөвлөөгүй" in response.content.decode()
    assert not employee.events.filter(type="rehire").exists()


# --- a rehire that waits for its signed order holds its slot ---


def _waiting(employee: Employee, actor: User, position: Position) -> Any:
    event = _rehire(employee, actor, position)
    assert event.applied_at is None  # the hired-order switch is on: the rehire waits for its signature
    return event


def test_waiting_rehire_holds_the_only_post(
    client: Client, actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    first = _left(actor, job_values, branch, "УБ77010101")
    second = _left(actor, job_values, branch, "УБ77010102")
    _switch()
    _row(position, branch, 1)
    _waiting(first, actor, position)
    with pytest.raises(EventError) as exc:  # the second rehire is refused at record time
        _rehire(second, actor, position)
    assert "Орон тоо дүүрсэн" in exc.value.errors["__all__"]
    login_as(client, "HR")  # a new hire is refused too: the post is held by the waiting rehire
    assert _post(client, job_values, branch).status_code == 400 and not _exists()


def test_cancelling_the_waiting_rehire_frees_the_post(
    actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    first = _left(actor, job_values, branch, "УБ77010101")
    second = _left(actor, job_values, branch, "УБ77010102")
    _switch()
    _row(position, branch, 1)
    waiting = _waiting(first, actor, position)
    with pytest.raises(EventError):
        _rehire(second, actor, position)
    events.cancel(waiting, reason="Буцаав", by=actor)
    assert _rehire(second, actor, position).type == "rehire"


def test_signing_the_waiting_rehire_does_not_count_it_twice(
    actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    from employees.services import slots
    from employees.tests.helpers import sign_event

    employee = _left(actor, job_values, branch)
    _switch()
    _row(position, branch, 2)
    waiting = _waiting(employee, actor, position)
    assert slots.check(position, branch, kind="Main", on=date(2026, 5, 1)).used == 1
    assert sign_event(waiting, by=actor).applied_at is not None
    assert slots.check(position, branch, kind="Main", on=date(2026, 5, 1)).used == 1


def test_screen_count_equals_the_gate_count_with_a_waiting_rehire(
    actor: User, job_values: dict[str, Any], position: Position, branch: Branch
) -> None:
    from employees.services import slots

    employee = _left(actor, job_values, branch)
    _waiting(employee, actor, position)
    on = date(2026, 5, 1)  # after the person left, so only the waiting rehire counts
    batch = slots.used_by_key(2026, on)
    assert batch.get((position.pk, branch.pk, "Main"), 0) == slots.check(position, branch, kind="Main", on=on).used == 1


# --- recruitment convert (the hire form carries the candidate) ---


def test_convert_is_refused_without_a_slot_then_succeeds_after_one_is_added(
    client: Client, job_values: dict[str, Any], position: Position, branch: Branch, actor: User
) -> None:
    _switch()
    candidate: Candidate = pipeline.add_candidate(make_vacancy(), by=actor, surname="Дорж", given_name="Бат")
    login_as(client, "HR")
    payload = add_payload(job_values, branch=str(branch.pk))
    payload["candidate"] = str(candidate.pk)
    response = client.post("/employees/new/", payload)
    assert response.status_code == 400 and not _exists()
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW and candidate.employee_id is None
    assert f'name="candidate" value="{candidate.pk}"' in response.content.decode()
    _row(position, branch, 1)
    assert client.post("/employees/new/", payload).status_code == 302
    candidate.refresh_from_db()
    assert candidate.stage == Stage.HIRED and candidate.employee_id is not None
