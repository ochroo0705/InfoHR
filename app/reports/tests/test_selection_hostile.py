"""Hostile input to the selection endpoints (Review Focus 1 to 5): forged, hidden, garbage and oversized ids, junk
addresses, and who may call what. Every request answers 200, 400, 403 or 404, never 500, and no person the user may
not act on reaches an output."""

import csv
import io
import json
import re
from typing import Any
from urllib.parse import urlencode

import openpyxl
import pytest
from accounts.models import AccessScope, User
from checklists.models import Checklist, ChecklistKind, ChecklistTemplate, ChecklistTemplateTask
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees.models import Employee
from employees.services import macs_writes
from employees.tests.conftest import named
from macs.models import Nationality

from reports import selection
from reports.filters import Filters, to_query

from .conftest import _make_user, legacy

pytestmark = pytest.mark.django_db

ALL = to_query(Filters(state="all"))
QUERY = f"{ALL}&cols=code&cols=name"  # the staff list, every person, code and name shown
PAGE = "/reports/staff-list/"
ENDPOINTS = {
    "excel": "/reports/staff-list/selected/excel/",
    "csv": "/reports/staff-list/selected/csv/",
    "print": "/reports/staff-list/selected/print/",
    "copy": "/reports/staff-list/selected/copy/",
    "checklist": "/reports/staff-list/selected/checklist/",
}
FILES = ("excel", "csv", "print")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OK_STATUSES = {200, 400, 403, 404}
CASE_NAMES = (
    "forged_ids",
    "hidden_by_filter",
    "hidden_by_rule",
    "garbage_ids",
    "duplicate_ids",
    "empty",
    "ids_501",
    "all_matching",
    "pivot_grouped",
    "junk_params",
    "long_value",
    "invalid_rules",
    "no_query",
    "no_query_all",
)


def _rule(code: str) -> str:
    """A rule that keeps every person whose code is not `code` (the staff list's code column)."""
    tree = {"op": "and", "items": [{"c": "code", "o": "neq", "v": code}]}
    return json.dumps(tree, separators=(",", ":"))


def _remove_export_switch() -> None:
    """Take `accounts.export_lists` away from the HR group (the accounts migrations give it to HR)."""
    export = Permission.objects.get(codename="export_lists", content_type__app_label="accounts")
    Group.objects.get(name="HR").permissions.remove(export)


def _rows_of_sheet(data: bytes) -> list[list[Any]]:
    ws: Any = openpyxl.load_workbook(io.BytesIO(data)).active  # untyped: openpyxl stubs type `active` as Optional
    return [[c.value for c in row] for row in ws.iter_rows()]


def _cells(resp: Any) -> set[str]:
    """The table cells of a file or print page. Checked as cells, not as raw text: the rule line of the page repeats
    the values the user typed, so a code can appear there without any row of that person being shown."""
    content_type = resp["Content-Type"]
    if content_type == XLSX:
        return {str(v) for row in _rows_of_sheet(resp.content) for v in row if v is not None}
    if content_type.startswith("text/csv"):
        text = resp.content.decode("utf-8-sig")
        return {field for row in csv.reader(io.StringIO(text)) for field in row}
    return set(re.findall(r">([^<>]*)</td>", resp.content.decode("utf-8", "replace")))


def _cases(p: dict[str, Employee]) -> dict[str, dict[str, Any]]:
    """The posted bodies. A, B, C and D are the people of the `people` fixture; C has another nationality."""
    a, b, c, d = (str(p[k].pk) for k in "ABCD")
    all_ids = [a, b, c, d]
    return {
        "forged_ids": {"query": QUERY, "ids": ["98765", "98766", "99999999"]},
        "hidden_by_filter": {"query": f"{ALL}&nationality={p['A'].nationality_id}&cols=code&cols=name", "ids": all_ids},
        "hidden_by_rule": {"query": f"{ALL}&{urlencode({'rules': _rule(str(p['C'].code))})}", "ids": all_ids},
        "garbage_ids": {
            "query": QUERY,
            "ids": ["abc", "-5", "", "1.5", "²", "٣", "+7", " 3 ", "9" * 5000, a],
        },
        "duplicate_ids": {"query": QUERY, "ids": [a] * 50},
        "empty": {"query": QUERY},
        "ids_501": {"query": QUERY, "ids": [str(n) for n in range(1, 502)]},
        "all_matching": {"query": QUERY, "all": "1"},
        "pivot_grouped": {
            "query": f"{QUERY}&layout=pivot&lby=department&lby2=name&lval=count&group=department",
            "ids": all_ids,
        },
        "junk_params": {
            "query": f"{ALL}&{'k' * 300}=1&=&%00=x&cols=%FF&sort=;;;&totals=x:y:z&marks=!!&pin=99&layout=board&lby=%00",
            "all": "1",
        },
        "long_value": {"query": f"{QUERY}&nationality={'9' * 4000}", "ids": all_ids},
        "invalid_rules": {"query": f"{QUERY}&rules={'{' * 50}", "ids": all_ids},
        "no_query": {"ids": all_ids},
        "no_query_all": {"all": "1"},
    }


def _post(client: Client, user: User, url: str, data: dict[str, Any], *, confirm: bool = True) -> Any:
    """POST as `user`. The checklist gets `confirm` and a valid date unless `confirm` is False (the first load)."""
    client.force_login(user)
    payload = dict(data)
    if url == ENDPOINTS["checklist"] and confirm:
        payload.setdefault("confirm", "1")
        payload.setdefault("anchor_day", "2026-12-01")
    return client.post(url, payload)


def _started(employee: Employee) -> int:
    return Checklist.objects.filter(employee=employee).count()


@pytest.fixture
def people(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """A, B and D have Монгол nationality, C has another one. A, B and C work in Санхүү, D in Маркетинг."""
    marketing = macs_writes.save_department("Маркетинг")
    mongol = named(Nationality, "Монгол")
    other = named(Nationality, "Бусад")
    return {
        "A": legacy(actor, job_values, nationality=mongol),
        "B": legacy(actor, job_values, nationality=mongol),
        "C": legacy(actor, job_values, nationality=other),
        "D": legacy(actor, job_values, nationality=mongol, department=marketing),
    }


@pytest.fixture
def scoped(people: dict[str, Employee]) -> User:
    """An HR user who may only see Санхүү: D (Маркетинг) is outside the scope."""
    user = _make_user("HR", "scoped-hostile-hr")
    AccessScope.objects.create(user=user, limited=True, department_ids=[people["A"].department_id])
    return user


@pytest.fixture
def offboarding_ready() -> ChecklistTemplate:
    """One active default offboarding template, so a checklist start can succeed."""
    ChecklistTemplate.objects.filter(kind=ChecklistKind.OFFBOARDING.value, is_default=True).delete()
    template = ChecklistTemplate.objects.create(
        kind=ChecklistKind.OFFBOARDING.value, name="hostile default", is_default=True, reasons=[], active=True
    )
    ChecklistTemplateTask.objects.create(template=template, title="Даалгавар", manager=True, due_offset_days=0)
    return template


@pytest.mark.parametrize("case", CASE_NAMES)
@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_hostile_body_never_gives_500(
    client: Client,
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    endpoint: str,
    case: str,
) -> None:
    resp = _post(client, hr_user, ENDPOINTS[endpoint], _cases(people)[case])
    assert resp.status_code != 500
    assert resp.status_code in OK_STATUSES


@pytest.mark.parametrize("case", CASE_NAMES)
def test_checklist_pop_up_without_confirm_always_answers_200(
    client: Client, hr_user: User, people: dict[str, Employee], case: str
) -> None:
    resp = _post(client, hr_user, ENDPOINTS["checklist"], _cases(people)[case], confirm=False)
    assert resp.status_code == 200  # a refused selection comes back as the pop-up with its message
    assert Checklist.objects.count() == 0


@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
@pytest.mark.parametrize("case", ["hidden_by_filter", "hidden_by_rule"])
def test_person_hidden_by_a_filter_or_rule_never_reaches_the_output(
    client: Client,
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    endpoint: str,
    case: str,
) -> None:
    resp = _post(client, hr_user, ENDPOINTS[endpoint], _cases(people)[case])
    assert resp.status_code == 200  # A is still chosen and visible, so the action runs
    if endpoint == "checklist":
        assert _started(people["C"]) == 0 and _started(people["A"]) == 1
    elif endpoint == "copy":
        assert resp.json()["count"] == 3  # A, B and D; C is hidden. Copy text holds names only, all alike here
    else:
        cells = _cells(resp)  # codes tell people apart: every fixture person has the same name
        assert people["C"].code not in cells
        assert people["A"].code in cells


@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_forged_out_of_scope_person_never_reaches_any_output(
    client: Client,
    scoped: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    endpoint: str,
) -> None:
    ids = [str(people["A"].pk), str(people["D"].pk), "98765"]
    for body, copied in (({"query": QUERY, "ids": ids}, 1), ({"query": QUERY, "all": "1"}, 3)):
        Checklist.objects.all().delete()
        resp = _post(client, scoped, ENDPOINTS[endpoint], body)
        assert resp.status_code == 200
        if endpoint == "checklist":
            assert _started(people["D"]) == 0 and _started(people["A"]) == 1
        elif endpoint == "copy":
            assert resp.json()["count"] == copied  # the scoped user sees A, B, C: D never counts
        else:
            cells = _cells(resp)
            assert people["D"].code not in cells
            assert people["A"].code in cells


@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_all_matching_over_the_cap_is_refused(
    client: Client,
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    monkeypatch.setattr(selection, "MAX_PEOPLE", 2)
    resp = _post(client, hr_user, ENDPOINTS[endpoint], {"query": QUERY, "all": "1"})
    if endpoint == "checklist":
        assert resp.status_code == 200 and selection.too_many() in resp.content.decode()
        assert Checklist.objects.count() == 0
    else:
        assert resp.status_code == 400 and resp.content.decode() == selection.too_many()


@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_501_posted_ids_are_refused(
    client: Client, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate, endpoint: str
) -> None:
    ids = [str(n) for n in range(1, selection.MAX_PEOPLE + 2)]  # 501 distinct ids, no monkeypatch
    resp = _post(client, hr_user, ENDPOINTS[endpoint], {"query": QUERY, "ids": ids})
    if endpoint == "checklist":
        assert resp.status_code == 200 and selection.too_many() in resp.content.decode()
        assert Checklist.objects.count() == 0
    else:
        assert resp.status_code == 400 and resp.content.decode() == selection.too_many()


@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_forged_ids_alone_are_refused_with_the_count(
    client: Client, scoped: User, people: dict[str, Employee], endpoint: str
) -> None:
    resp = _post(client, scoped, ENDPOINTS[endpoint], {"query": QUERY, "ids": [str(people["D"].pk), "98765"]})
    if endpoint == "checklist":
        assert resp.status_code == 200 and selection.not_allowed(2) in resp.content.decode()
    else:
        assert resp.status_code == 400 and resp.content.decode() == selection.not_allowed(2)


def test_copy_of_people_without_a_work_email_carries_no_email_text(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    """The copy adds the work email after a tab when the user may see the email column (a permission, not `cols`).
    These people have none, so the tab is followed by nothing and no address appears."""
    resp = _post(client, hr_user, ENDPOINTS["copy"], {"query": QUERY, "ids": [str(people["A"].pk)]})
    assert resp.status_code == 200
    text = resp.json()["text"]
    assert "@" not in text
    assert text.count("\t") <= 1 and text.split("\t")[-1] == ""


def test_user_without_export_switch_is_refused_files_but_may_print_and_copy(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    _remove_export_switch()
    body = {"query": QUERY, "ids": [str(people["A"].pk)]}
    assert _post(client, hr_user, ENDPOINTS["excel"], body).status_code == 403
    assert _post(client, hr_user, ENDPOINTS["csv"], body).status_code == 403
    assert _post(client, hr_user, ENDPOINTS["print"], body).status_code == 200
    assert _post(client, hr_user, ENDPOINTS["copy"], body).status_code == 200


def test_user_who_cannot_start_checklists_gets_403_on_form_and_action(
    client: Client, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    accountant = _make_user("Accountant", "hostile-accountant")
    body = {"query": QUERY, "ids": [str(people["A"].pk)]}
    assert _post(client, accountant, ENDPOINTS["checklist"], body, confirm=False).status_code == 403
    assert _post(client, accountant, ENDPOINTS["checklist"], body).status_code == 403
    assert Checklist.objects.count() == 0


@pytest.mark.parametrize("key", ["children", "no-such-report"])
@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_report_that_does_not_opt_in_is_404_on_every_endpoint(
    client: Client, hr_user: User, people: dict[str, Employee], endpoint: str, key: str
) -> None:
    url = ENDPOINTS[endpoint].replace("staff-list", key)
    assert _post(client, hr_user, url, {"query": QUERY, "ids": [str(people["A"].pk)]}).status_code == 404


@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_get_on_each_endpoint_is_405(client: Client, hr_user: User, endpoint: str) -> None:
    client.force_login(hr_user)
    assert client.get(ENDPOINTS[endpoint], {"query": QUERY, "ids": ["1"]}).status_code == 405


@pytest.mark.parametrize("case", CASE_NAMES)
def test_report_page_answers_200_for_hostile_addresses(
    client: Client, hr_user: User, people: dict[str, Employee], case: str
) -> None:
    query = _cases(people)[case].get("query", "")
    client.force_login(hr_user)
    resp = client.get(f"{PAGE}?{query}" if query else PAGE)
    assert resp.status_code == 200
