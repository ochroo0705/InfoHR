"""seed_demo scenarios: the demo database holds every kind of data the screens show (see _demo_scenarios)."""

from io import StringIO

import pytest
from accounts.models import AccessScope, User
from checklists.models import Checklist, ChecklistTemplate
from django.core.management import call_command
from django.db.models import Count
from django.utils import timezone
from leave.models import LeaveRequest
from macs.models import Branch, NazgRow, Position
from pytest_django.fixtures import SettingsWrapper
from recruitment.models import Candidate, Vacancy

from employees.models import CompanySettings, Employee, EmployeeExt, Event, HrOrder
from employees.services import slots

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def seeded(settings: SettingsWrapper) -> None:
    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())


def test_slots_come_in_every_state() -> None:
    today = timezone.localdate()
    assert Branch.objects.count() == 2
    assert CompanySettings.get().enforce_position_slots is True
    free = full = over = 0
    for row in NazgRow.objects.filter(year=today.year):
        used = slots.used_by_key(today.year, today).get((row.position_id, row.branch_id, row.kind), 0)
        free += row.qty > used
        full += row.qty == used and used > 0
        over += row.qty < used
    assert free and full and over
    driver = Position.objects.get(name="Жолооч")
    assert not NazgRow.objects.filter(position=driver, year=today.year).exists()  # no row = no posts


def test_events_orders_and_checklists() -> None:
    events = {(e.type, e.applied_at is not None, e.cancelled_at is not None) for e in Event.objects.all()}
    assert ("termination", True, False) in events
    assert ("leave_start", True, False) in events
    assert ("promotion", False, False) in events  # waits for its signed order
    assert ("salary_change", True, True) in events  # cancelled
    assert {"pending", "registered", "signed"} <= set(HrOrder.objects.values_list("state", flat=True))
    if (
        ChecklistTemplate.objects.exists()
    ):  # the starter templates come from migrations; the test database may lack them
        kinds = set(Checklist.objects.values_list("kind", "state"))
        assert {("onboarding", "open"), ("offboarding", "open"), ("offboarding", "completed")} <= kinds
    assert EmployeeExt.objects.filter(is_pensioner=True).exists()


def test_recruitment_has_every_stage() -> None:
    stages = set(Candidate.objects.values_list("stage", flat=True))
    assert stages == {"new", "screening", "interview", "offer", "hired", "rejected", "withdrawn"}
    assert set(Vacancy.objects.values_list("status", flat=True)) == {"open", "closed", "filled"}
    assert Vacancy.objects.filter(branch__isnull=True).exists()  # the line asks for a branch
    assert Vacancy.objects.annotate(n=Count("candidates")).filter(headcount__gt=1).exists()


def test_logins_roles_and_scope() -> None:
    assert User.objects.get(username="auditor").groups.filter(name="Auditor").exists()
    assert AccessScope.objects.get(user__username="darkhan_hr").limited is True
    assert User.objects.get(username="munkh_erdene").is_active is False
    assert User.objects.filter(username="temuulen", is_active=True).exists()


def test_leave_request_states_birthdays_and_children() -> None:
    assert {"waiting", "approved", "withdrawn", "rejected"} <= set(
        LeaveRequest.objects.values_list("status", flat=True)
    )
    today = timezone.localdate()
    near = [
        e
        for e in Employee.objects.exclude(birth_date__isnull=True)
        if 0 <= (e.birth_date.replace(year=today.year) - today).days <= 7
    ]
    assert near  # a birthday this week, whenever the demo is built
    from macs.models import FamilyRow

    assert FamilyRow.objects.filter(relation__fm_type__in=["son", "daughter"]).count() >= 4
