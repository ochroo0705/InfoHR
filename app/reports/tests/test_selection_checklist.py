"""The checklist action of the report selection: the form pop-up (POST without `confirm`) and the start of an
offboarding checklist for each picked person (POST with `confirm`). Refused fields come back as the pop-up with
status 200 and the error in it."""

from datetime import date
from typing import Any

import pytest
from accounts.models import AccessScope, SystemLogEntry, User
from checklists import access as checklist_access
from checklists.access import can_start
from checklists.models import Checklist, ChecklistKind, ChecklistTemplate, ChecklistTemplateTask
from checklists.services import lifecycle
from django.test import Client
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, Employee
from employees.services import macs_writes
from employees.tests.conftest import named
from macs.models import FiredReason, Nationality

from reports.filters import Filters, to_query

from .conftest import _make_user, legacy

pytestmark = pytest.mark.django_db

ALL = to_query(Filters(state="all"))
QUERY = f"{ALL}&cols=code&cols=name"  # the staff list, every person, code and name shown
URL = "/reports/staff-list/selected/checklist/"
ANCHOR = "2026-12-01"
DISMISSED = 3  # a MACS emptype the listing counts as not working (LEGACY_NOT_WORKING): such a person has left
OFFBOARDING = ChecklistKind.OFFBOARDING.value


def _template(kind: str, *, default: bool, reasons: tuple[str, ...] = (), active: bool = True) -> ChecklistTemplate:
    """A template of `kind` with one task. A default is made by replacing the seeded one (one default per kind)."""
    if default:
        ChecklistTemplate.objects.filter(kind=kind, is_default=True).delete()
    template = ChecklistTemplate.objects.create(
        kind=kind, name=f"{kind} {default} {reasons}", is_default=default, reasons=list(reasons), active=active
    )
    ChecklistTemplateTask.objects.create(template=template, title="Даалгавар", manager=True, due_offset_days=0)
    return template


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


def _form(client: Client, user: User, **data: Any) -> Any:
    """POST without `confirm`: the pop-up's first load, with the selection as posted."""
    client.force_login(user)
    payload: dict[str, Any] = {"query": QUERY}
    payload.update(data)
    return client.post(URL, payload)


def _post(client: Client, user: User, **data: Any) -> Any:
    """POST with `confirm`: the action, with a valid date unless the test overrides it."""
    client.force_login(user)
    payload: dict[str, Any] = {"query": QUERY, "confirm": "1", "anchor_day": ANCHOR}
    payload.update(data)
    return client.post(URL, payload)


def _started(employee: Employee) -> int:
    return Checklist.objects.filter(employee=employee).count()


def test_post_without_confirm_renders_the_form_without_a_kind_select(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    resp = _form(client, hr_user, ids=[str(people["B"].pk), str(people["C"].pk)])
    assert resp.status_code == 200
    page = resp.content.decode()
    assert 'name="kind"' not in page  # offboarding only: nothing to choose
    assert 'name="reason"' in page and 'name="anchor_day"' in page and 'name="confirm" value="1"' in page
    assert "Ажлаас гарах жагсаалт эхлүүлэх" in page
    assert f'name="ids" value="{people["B"].pk}"' in page and f'name="ids" value="{people["C"].pk}"' in page
    assert f'name="ids" value="{people["A"].pk}"' not in page  # only the picked people are sent back
    assert 'name="query"' in page
    assert f'value="{timezone.localdate().isoformat()}"' in page  # the anchor day starts on today
    assert Checklist.objects.count() == 0


def test_post_without_confirm_in_all_matching_mode_has_no_ids(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    resp = _form(client, hr_user, all="1")
    assert resp.status_code == 200
    assert 'name="all" value="1"' in resp.content.decode()
    assert 'name="ids"' not in resp.content.decode()


def test_get_is_405(client: Client, hr_user: User, people: dict[str, Employee]) -> None:
    client.force_login(hr_user)
    assert client.get(URL, {"query": QUERY, "ids": [str(people["A"].pk)]}).status_code == 405
    assert Checklist.objects.count() == 0


def test_post_starts_an_offboarding_checklist_for_each_picked_person(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    picked = [people["A"], people["B"], people["C"]]
    resp = _post(client, hr_user, ids=[str(e.pk) for e in picked])
    assert resp.status_code == 200
    assert "Эхэлсэн 3" in resp.content.decode()
    for employee in picked:
        checklist = Checklist.objects.get(employee=employee)
        assert checklist.kind == OFFBOARDING and checklist.anchor_day == date(2026, 12, 1)
        assert checklist.tasks.count() == 1
        logged = SystemLogEntry.objects.filter(action="checklist_started", message__endswith=str(employee.code))
        assert logged.count() == 1
        assert ActivityEntry.objects.filter(employee=employee, kind=ActivityKind.ADDED).count() == 1
    assert _started(people["D"]) == 0  # not picked


def test_all_matching_starts_every_person_the_report_shows(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    resp = _post(client, hr_user, all="1")
    assert resp.status_code == 200
    assert "Эхэлсэн 4" in resp.content.decode()
    assert all(_started(e) == 1 for e in people.values())


def test_open_checklist_is_left_untouched_and_reported_as_already_open(
    client: Client,
    hr_user: User,
    actor: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
) -> None:
    lifecycle.start(people["A"], ChecklistKind.OFFBOARDING, reason=None, anchor_day=date(2026, 12, 1), by=actor)
    before = list(Checklist.objects.get(employee=people["A"]).tasks.values_list("due_on", flat=True))
    resp = _post(client, hr_user, ids=[str(people["A"].pk), str(people["B"].pk)], anchor_day="2026-12-15")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Эхэлсэн 1" in body and "Нээлттэй байсан 1" in body
    checklist = Checklist.objects.get(employee=people["A"])
    assert checklist.anchor_day == date(2026, 12, 1)  # not moved
    assert list(checklist.tasks.values_list("due_on", flat=True)) == before  # task dates not moved either
    assert _started(people["A"]) == 1  # no second open checklist
    assert _started(people["B"]) == 1


def test_no_active_template_reports_no_template_and_creates_nothing(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    ChecklistTemplate.objects.filter(kind=OFFBOARDING).update(active=False)
    resp = _post(client, hr_user, ids=[str(people["A"].pk), str(people["B"].pk)])
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Загвар алга 2" in body
    assert Checklist.objects.count() == 0


def test_one_unexpected_error_is_that_persons_outcome_and_the_others_still_run(
    client: Client,
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_start = lifecycle.start

    def failing_for_b(employee: Employee, *args: Any, **kwargs: Any) -> Any:
        if employee.pk == people["B"].pk:
            raise RuntimeError("boom")
        return real_start(employee, *args, **kwargs)

    monkeypatch.setattr(lifecycle, "start", failing_for_b)
    ids = [str(people["A"].pk), str(people["B"].pk), str(people["C"].pk)]
    resp = _post(client, hr_user, ids=ids)
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Эхэлсэн 2" in body and "Алдаа гарлаа 1" in body
    assert _started(people["A"]) == 1 and _started(people["C"]) == 1
    assert _started(people["B"]) == 0


def test_person_who_has_left_gets_no_checklist_and_is_counted_as_left(
    client: Client, hr_user: User, actor: User, job_values: dict[str, Any], offboarding_ready: ChecklistTemplate
) -> None:
    gone = legacy(actor, job_values, nationality=named(Nationality, "Монгол"), emptype=DISMISSED)
    resp = _post(client, hr_user, ids=[str(gone.pk)])
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Ажлаас гарсан 1" in body
    assert "Эхэлсэн 0" in body  # the one picked person was not started
    assert _started(gone) == 0
    assert Checklist.objects.count() == 0


def test_person_who_has_left_with_an_open_checklist_is_reported_left_and_left_alone(
    client: Client,
    hr_user: User,
    actor: User,
    job_values: dict[str, Any],
    offboarding_ready: ChecklistTemplate,
) -> None:
    gone = legacy(actor, job_values, nationality=named(Nationality, "Монгол"), emptype=DISMISSED)
    lifecycle.start(gone, ChecklistKind.OFFBOARDING, reason=None, anchor_day=date(2026, 12, 1), by=actor)
    resp = _post(client, hr_user, ids=[str(gone.pk)], anchor_day="2026-12-15")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Ажлаас гарсан 1" in body and "Нээлттэй байсан 0" in body  # left wins over the open checklist
    checklist = Checklist.objects.get(employee=gone)
    assert checklist.anchor_day == date(2026, 12, 1)  # left alone
    assert checklist.state == "open"


def test_forged_out_of_scope_id_never_gets_a_checklist(
    client: Client, actor: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    scoped = _make_user("HR", "scoped-checklist-hr")
    AccessScope.objects.create(user=scoped, limited=True, department_ids=[people["A"].department_id])
    resp = _post(client, scoped, ids=[str(people["A"].pk), str(people["D"].pk)])
    assert resp.status_code == 200
    assert "Эхэлсэн 1" in resp.content.decode()
    assert _started(people["D"]) == 0
    assert _started(people["A"]) == 1


def test_user_who_cannot_start_gets_403_on_post(
    client: Client, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    accountant = _make_user("Accountant", "checklist-accountant")
    assert not can_start(accountant)  # the accountant has the report but may not record a termination
    ids = [str(people["A"].pk)]
    assert _form(client, accountant, ids=ids).status_code == 403
    assert _post(client, accountant, ids=ids).status_code == 403
    assert Checklist.objects.count() == 0


@pytest.mark.parametrize(
    "bad",
    ["2026-13-01", "2026/12/01", "2026-1-1", "", "２０２６-12-01", "2026-12-01x", "2026-W49-2", "٢٠٢٦-١٢-٠١"],
)
def test_bad_date_shows_the_form_with_the_error(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate, bad: str
) -> None:
    resp = _post(client, hr_user, ids=[str(people["A"].pk)], anchor_day=bad)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Огноог 2026-11-07 хэлбэрээр оруулна уу." in body
    assert 'name="anchor_day"' in body
    assert Checklist.objects.count() == 0


def test_date_out_of_range_shows_the_error(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    resp = _post(client, hr_user, ids=[str(people["A"].pk)], anchor_day="1900-01-01")
    assert resp.status_code == 200
    assert "1990-01-01" in resp.content.decode()
    assert Checklist.objects.count() == 0


@pytest.mark.parametrize("kind", ["onboarding", "payroll"])
def test_a_kind_other_than_offboarding_shows_the_error(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate, kind: str
) -> None:
    resp = _post(client, hr_user, ids=[str(people["A"].pk)], kind=kind)
    assert resp.status_code == 200
    assert "зөвхөн «Ажлаас гарах» жагсаалт эхлүүлнэ" in resp.content.decode()
    assert Checklist.objects.count() == 0


def test_offboarding_kind_posted_explicitly_is_accepted(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    resp = _post(client, hr_user, ids=[str(people["A"].pk)], kind=OFFBOARDING)
    assert resp.status_code == 200
    assert "Эхэлсэн 1" in resp.content.decode()


def test_reason_not_listed_by_any_active_template_shows_the_error(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    resp = _post(client, hr_user, ids=[str(people["A"].pk)], reason="no-such-type")
    assert resp.status_code == 200
    assert "Шалтгаан буруу байна" in resp.content.decode()
    assert Checklist.objects.count() == 0


def test_reason_selects_the_template_that_lists_it(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    reason = named(FiredReason, "Өөрийн хүсэлтээр")
    special = _template(OFFBOARDING, default=False, reasons=(str(reason.pk),))
    resp = _post(client, hr_user, ids=[str(people["A"].pk)], reason=str(reason.pk))
    assert resp.status_code == 200
    assert Checklist.objects.get(employee=people["A"]).template_id == special.pk


def test_empty_selection_shows_the_form_with_the_error(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    resp = _post(client, hr_user)
    assert resp.status_code == 200
    assert "Ядаж нэг хүнийг сонгоно уу." in resp.content.decode()
    assert Checklist.objects.count() == 0


@pytest.mark.parametrize("method", ["put", "delete"])
def test_other_methods_are_405(client: Client, hr_user: User, method: str) -> None:
    client.force_login(hr_user)
    assert getattr(client, method)(URL).status_code == 405


def test_person_outside_the_checklist_rules_is_not_allowed_and_gets_no_checklist(
    client: Client,
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = people["B"].pk
    monkeypatch.setattr(checklist_access, "can_see_employee", lambda user, employee: employee.pk != blocked)
    resp = _post(client, hr_user, ids=[str(people["A"].pk), str(people["B"].pk)])
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Эхэлсэн 1" in body and "Харах эрх алга 1" in body
    assert _started(people["B"]) == 0
    assert _started(people["A"]) == 1


def test_picked_id_missing_on_read_back_is_counted_as_not_allowed(
    client: Client,
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Employee.objects, "in_bulk", lambda *args, **kwargs: {})
    resp = _post(client, hr_user, ids=[str(people["A"].pk), str(people["B"].pk)])
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Харах эрх алга 2" in body  # both picked ids are counted, none silently dropped
    assert Checklist.objects.count() == 0


def test_refused_form_keeps_the_typed_date(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    resp = _post(client, hr_user, anchor_day="2026-12-15")  # no ids: the selection is refused
    body = resp.content.decode()
    assert resp.status_code == 200
    assert 'value="2026-12-15"' in body
    assert "Ядаж нэг хүнийг сонгоно уу." in body
