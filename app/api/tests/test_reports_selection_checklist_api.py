"""The checklist routes of the report selection (api/reports.py): the form (POST .../selected/checklist/form) and the
start (POST .../selected/checklist). The rules live in reports.services.selection_checklist and checklists; these tests
pin the routes: their rights (401 without a login, 404 for a missing or person-less report, 403 without the right to
open the report or to start a checklist), the form's shape, the selection being checked before the fields, the
refusals (400 with the message in form_errors), the per-person outcomes and the no-store header.
"""

import json
from datetime import date
from typing import Any

import pytest
from accounts.models import AccessScope, SystemLogEntry, User
from checklists.models import Checklist, ChecklistKind, ChecklistTemplate, ChecklistTemplateTask
from checklists.services import lifecycle
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, Employee
from employees.services import macs_writes
from employees.tests.conftest import _no_offboarding_templates, named  # noqa: F401 (autouse fixture)
from macs.models import FiredReason, Nationality
from reports.registry import REPORTS
from reports.selection import NOTHING_PICKED
from reports.services.selection_checklist import MSG_DATE, MSG_RANGE, MSG_REASON
from reports.tests.conftest import legacy
from reports.types import Column, Report

from api.tests.logs_support import FORBIDDEN, NOT_LOGGED_IN

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
STAFF = "staff-list"  # the real registry report with a person
QUERY = "state=all&cols=code&cols=name"  # the staff list, every person, code and name shown
HELD_OUT = "api-checklist-held-out"  # a report no route knows about; the checklist route needs no code for it
NO_PERSON = "api-checklist-no-person"
DISMISSED = 3  # a MACS emptype the listing counts as not working: such a person has left
OFFBOARDING = ChecklistKind.OFFBOARDING.value
ANCHOR = "2026-12-01"
FORM = "selected/checklist/form"
START = "selected/checklist"
NO_OUTCOMES = {"started": 0, "already_open": 0, "no_template": 0, "not_allowed": 0, "left": 0, "error": 0}


def _user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _as(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _post(client: Client, path: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(path, data=json.dumps(body or {}), content_type="application/json")


def _base(key: str = STAFF) -> str:
    return f"/api/v1/reports/{key}"


def _template(kind: str, *, default: bool, reasons: tuple[str, ...] = (), active: bool = True) -> ChecklistTemplate:
    """A template of `kind` with one task. A default is made by replacing the seeded one (one default per kind)."""
    if default:
        ChecklistTemplate.objects.filter(kind=kind, is_default=True).delete()
    template = ChecklistTemplate.objects.create(
        kind=kind, name=f"{kind} {default} {reasons}", is_default=default, reasons=list(reasons), active=active
    )
    ChecklistTemplateTask.objects.create(template=template, title="Даалгавар", manager=True, due_offset_days=0)
    return template


def _started(employee: Employee) -> int:
    return Checklist.objects.filter(employee=employee).count()


def _activity_and_log(employee: Employee) -> tuple[int, int]:
    """How many «added» activity entries and checklist_started log lines the person has now."""
    added = ActivityEntry.objects.filter(employee=employee, kind=ActivityKind.ADDED).count()
    logged = SystemLogEntry.objects.filter(action="checklist_started", message__endswith=employee.code).count()
    return added, logged


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("api_checklist_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hr() -> User:
    return _user("HR", "api_checklist_hr")


@pytest.fixture
def offboarding_ready() -> ChecklistTemplate:
    """One active default offboarding template: starting offboarding works for everyone."""
    return _template(OFFBOARDING, default=True)


@pytest.fixture
def people(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """A, B and C work in Санхүү, D in Маркетинг."""
    marketing = macs_writes.save_department("Маркетинг")
    mongol = named(Nationality, "Монгол")
    return {
        "A": legacy(actor, job_values, nationality=mongol),
        "B": legacy(actor, job_values, nationality=mongol),
        "C": legacy(actor, job_values, nationality=mongol),
        "D": legacy(actor, job_values, nationality=mongol, department=marketing),
    }


@pytest.fixture
def trio(
    actor: User, job_values: dict[str, Any], people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> dict[str, Employee]:
    """A has an open offboarding checklist, B has left, C is fine. The active template exists before A is started."""
    lifecycle.start(people["A"], ChecklistKind.OFFBOARDING, reason=None, anchor_day=date(2026, 12, 1), by=actor)
    left = legacy(actor, job_values, nationality=named(Nationality, "Монгол"), emptype=DISMISSED)
    return {"A": people["A"], "B": left, "C": people["C"]}


@pytest.fixture
def held_out(monkeypatch: pytest.MonkeyPatch, people: dict[str, Employee]) -> str:
    """A report with a person column over the same people, registered for this test only."""
    rows = [people[name] for name in "ABCD"]
    report = Report(
        key=HELD_OUT,
        title="Тестийн тайлан",
        filters=(),
        columns=(
            Column(key="code", label="Код", value=lambda r: r.code),
            Column(key="name", label="Нэр", value=lambda r: r.full_name),
        ),
        default_columns=("code", "name"),
        rows=lambda user, f: list(rows),
        saved_views=True,
        layouts=(),
        person=lambda r: r.pk,
    )
    monkeypatch.setitem(REPORTS, HELD_OUT, report)
    return HELD_OUT


@pytest.fixture
def no_person_report(monkeypatch: pytest.MonkeyPatch) -> str:
    report = Report(
        key=NO_PERSON,
        title="Тестийн тайлан",
        filters=(),
        columns=(Column(key="code", label="Код", value=lambda r: r.code),),
        default_columns=("code",),
        rows=lambda user, f: [],
        saved_views=True,
        layouts=(),
        person=None,
    )
    monkeypatch.setitem(REPORTS, NO_PERSON, report)
    return NO_PERSON


# --- rights and refusals ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [FORM, START])
def test_no_login_is_401(path: str, people: dict[str, Employee]) -> None:
    body = {"query": QUERY, "ids": [str(people["A"].pk)], "anchor_day": ANCHOR}
    response = _post(Client(), f"{_base()}/{path}", body)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


@pytest.mark.parametrize("path", [FORM, START])
def test_unknown_report_and_a_report_without_a_person_are_404(path: str, hr: User, no_person_report: str) -> None:
    client = _as(hr)
    body = {"ids": ["1"], "anchor_day": ANCHOR}
    assert _post(client, f"/api/v1/reports/no-such-report/{path}", body).status_code == 404
    assert _post(client, f"{_base(no_person_report)}/{path}", body).status_code == 404


@pytest.mark.parametrize("path", [FORM, START])
def test_no_open_right_is_403(path: str, people: dict[str, Employee], offboarding_ready: ChecklistTemplate) -> None:
    auditor = _user("Auditor", "api_checklist_auditor")  # may not open reports
    body = {"query": QUERY, "ids": [str(people["A"].pk)], "anchor_day": ANCHOR}
    response = _post(_as(auditor), f"{_base()}/{path}", body)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert Checklist.objects.count() == 0


@pytest.mark.parametrize("path", [FORM, START])
def test_user_who_cannot_start_gets_403(
    path: str, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    accountant = _user("Accountant", "api_checklist_accountant")  # may open the report, may not record a termination
    body = {"query": QUERY, "ids": [str(people["A"].pk)], "anchor_day": ANCHOR}
    response = _post(_as(accountant), f"{_base()}/{path}", body)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert Checklist.objects.count() == 0


# --- the form -------------------------------------------------------------------------------------------------------


def test_form_counts_the_picked_people_and_carries_the_template_facts(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    reason = named(FiredReason, "Өөрийн хүсэлтээр")
    _template(OFFBOARDING, default=False, reasons=(str(reason.pk),))
    body = {"query": QUERY, "ids": [str(people["A"].pk), str(people["B"].pk)]}
    response = _post(_as(hr), f"{_base()}/{FORM}", body)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    data = response.json()
    assert data["count"] == 2
    assert data["all"] is False
    assert data["reasons"] == [{"value": str(reason.pk), "label": "Өөрийн хүсэлтээр"}]
    assert data["template_missing"] is False
    assert data["anchor_min"] == "1990-01-01"
    assert data["anchor_max"] == "2100-12-31"
    assert data["today"] == timezone.localdate().isoformat()


def test_form_in_all_matching_mode_counts_every_person(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    data = _post(_as(hr), f"{_base()}/{FORM}", {"query": QUERY, "all": True}).json()
    assert data["all"] is True
    assert data["count"] == len(people)


def test_form_without_an_active_offboarding_template_says_so(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    ChecklistTemplate.objects.filter(kind=OFFBOARDING).update(active=False)
    data = _post(_as(hr), f"{_base()}/{FORM}", {"query": QUERY, "ids": [str(people["A"].pk)]}).json()
    assert data["template_missing"] is True
    assert data["reasons"] == []


def test_form_with_nothing_picked_is_400(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    response = _post(_as(hr), f"{_base()}/{FORM}", {"query": QUERY, "ids": []})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [NOTHING_PICKED]


# --- the start -------------------------------------------------------------------------------------------------------


def test_start_gives_each_person_one_outcome_in_their_own_words(
    hr: User, trio: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    ids = [str(trio[name].pk) for name in "ABC"]
    before = {name: _activity_and_log(trio[name]) for name in "ABC"}
    response = _post(_as(hr), f"{_base()}/{START}", {"query": QUERY, "ids": ids, "anchor_day": "2026-12-15"})
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    data = response.json()
    assert data["counts"] == {**NO_OUTCOMES, "started": 1, "already_open": 1, "left": 1}
    assert data["dropped"] == 0
    rows = {row["code"]: row for row in data["rows"]}
    assert rows == {
        trio["A"].code: {"code": trio["A"].code, "name": trio["A"].full_name, "outcome": "Нээлттэй байсан"},
        trio["B"].code: {"code": trio["B"].code, "name": trio["B"].full_name, "outcome": "Ажлаас гарсан"},
        trio["C"].code: {"code": trio["C"].code, "name": trio["C"].full_name, "outcome": "Эхэлсэн"},
    }
    # only the fine person gets a checklist; the open one keeps its day; the left one gets nothing
    assert _started(trio["C"]) == 1
    assert Checklist.objects.get(employee=trio["C"]).anchor_day == date(2026, 12, 15)
    assert Checklist.objects.get(employee=trio["A"]).anchor_day == date(2026, 12, 1)
    assert _started(trio["B"]) == 0
    # the start writes one activity entry and one log line for the fine person only: the open one's were written
    # when its checklist was started (in the fixture), the left one gets none
    assert _activity_and_log(trio["C"]) == (before["C"][0] + 1, before["C"][1] + 1)
    assert _activity_and_log(trio["A"]) == before["A"]
    assert _activity_and_log(trio["B"]) == before["B"]


def test_rows_come_back_in_the_order_the_people_were_picked(
    hr: User, people: dict[str, Employee], held_out: str, offboarding_ready: ChecklistTemplate
) -> None:
    """The held-out report lists its people as A, B, C, D, so the picked order is that order whatever order the ids
    were posted in: here C, A, B are posted and the rows must come back A, B, C."""
    ids = [str(people[name].pk) for name in "CAB"]
    body = {"query": "", "ids": ids, "anchor_day": ANCHOR}
    data = _post(_as(hr), f"{_base(held_out)}/{START}", body).json()
    assert [row["code"] for row in data["rows"]] == [people[name].code for name in "ABC"]
    assert data["counts"]["started"] == 3


def test_an_omitted_anchor_day_is_400_with_the_date_message(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    response = _post(_as(hr), f"{_base()}/{START}", {"query": QUERY, "ids": [str(people["A"].pk)]})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [MSG_DATE]
    assert Checklist.objects.count() == 0


def test_all_matching_starts_every_person_the_report_shows(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    data = _post(_as(hr), f"{_base()}/{START}", {"query": QUERY, "all": True, "anchor_day": ANCHOR}).json()
    assert data["counts"]["started"] == len(people)
    assert all(_started(e) == 1 for e in people.values())


@pytest.mark.parametrize("bad", ["2026-13-01", "2026/12/01", "2026-1-1", "", "2026-W49-2"])
def test_bad_date_is_400_with_the_date_message_and_writes_nothing(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate, bad: str
) -> None:
    body = {"query": QUERY, "ids": [str(people["A"].pk)], "anchor_day": bad}
    response = _post(_as(hr), f"{_base()}/{START}", body)
    assert response.status_code == 400
    assert response.json()["form_errors"] == [MSG_DATE]
    assert Checklist.objects.count() == 0


def test_date_out_of_range_is_400(hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate) -> None:
    body = {"query": QUERY, "ids": [str(people["A"].pk)], "anchor_day": "1900-01-01"}
    response = _post(_as(hr), f"{_base()}/{START}", body)
    assert response.status_code == 400
    assert response.json()["form_errors"] == [MSG_RANGE]
    assert Checklist.objects.count() == 0


def test_reason_not_listed_by_any_active_template_is_400(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    body = {"query": QUERY, "ids": [str(people["A"].pk)], "anchor_day": ANCHOR, "reason": "no-such-type"}
    response = _post(_as(hr), f"{_base()}/{START}", body)
    assert response.status_code == 400
    assert response.json()["form_errors"] == [MSG_REASON]
    assert Checklist.objects.count() == 0


def test_selection_is_checked_before_the_fields(
    hr: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    response = _post(_as(hr), f"{_base()}/{START}", {"query": QUERY, "ids": [], "anchor_day": "bad"})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [NOTHING_PICKED]


def test_forged_out_of_scope_id_never_gets_a_checklist_and_is_dropped(
    people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    scoped = _user("HR", "api_checklist_scoped")
    AccessScope.objects.create(user=scoped, limited=True, department_ids=[people["A"].department_id])
    body = {"query": QUERY, "ids": [str(people["A"].pk), str(people["D"].pk)], "anchor_day": ANCHOR}
    data = _post(_as(scoped), f"{_base()}/{START}", body).json()
    assert data["counts"]["started"] == 1
    assert data["dropped"] == 1
    assert _started(people["D"]) == 0
    assert _started(people["A"]) == 1


def test_a_held_out_report_with_a_person_works_with_no_route_of_its_own(
    hr: User, people: dict[str, Employee], held_out: str, offboarding_ready: ChecklistTemplate
) -> None:
    client = _as(hr)
    form = _post(client, f"{_base(held_out)}/{FORM}", {"query": "", "ids": [str(people["B"].pk)]})
    assert form.status_code == 200
    assert form.json()["count"] == 1
    body = {"query": "", "ids": [str(people["B"].pk)], "anchor_day": ANCHOR}
    start = _post(client, f"{_base(held_out)}/{START}", body)
    assert start.status_code == 200
    assert start.json()["counts"]["started"] == 1
    assert _started(people["B"]) == 1
