"""The copy of the picked people's names and work emails (selected_copy): one line per person, report order."""

from dataclasses import replace
from typing import Any

import pytest
from accounts.models import AccessScope, SystemLogEntry, User
from django.test import Client
from employees.models import Employee
from employees.services import macs_writes
from employees.tests.conftest import named
from macs.models import Nationality

from reports import selection, selection_views, staff_list
from reports.filters import Filters, to_query
from reports.registry import REPORTS
from reports.table import build_table
from reports.tests.conftest import _make_user, legacy

pytestmark = pytest.mark.django_db

ALL = to_query(Filters(state="all"))
QUERY = f"{ALL}&cols=code&cols=name"  # the staff list, every person, code and name shown
BY_CODE = f"{QUERY}&sort=code"  # codes are distinct, so this order is fixed; the default order can swap ties
COPY = "/reports/staff-list/selected/copy/"
PERSONAL = "macs.view_personal"
SALARY = "macs.view_salary"  # the HR role does not hold it


@pytest.fixture
def people(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """A, B and C work in Санхүү, D in Маркетинг. A and C have emails; B and D have none."""
    marketing = macs_writes.save_department("Маркетинг")
    mongol = named(Nationality, "Монгол")
    made = {
        "A": legacy(actor, job_values, nationality=mongol),
        "B": legacy(actor, job_values, nationality=mongol),
        "C": legacy(actor, job_values, nationality=mongol),
        "D": legacy(actor, job_values, nationality=mongol, department=marketing),
    }
    Employee.objects.filter(pk=made["A"].pk).update(email="a@example.test")
    Employee.objects.filter(pk=made["C"].pk).update(email="c@example.test")
    return {k: Employee.objects.get(pk=e.pk) for k, e in made.items()}


@pytest.fixture
def scoped(people: dict[str, Employee]) -> User:
    """An HR user who may only see Санхүү: D (Маркетинг) is outside the scope."""
    user = _make_user("HR", "scoped-copy-hr")
    AccessScope.objects.create(user=user, limited=True, department_ids=[people["A"].department_id])
    return user


def _post(client: Client, user: User, query: str = QUERY, **data: Any) -> Any:
    client.force_login(user)
    return client.post(COPY, {"query": query, **data})


def _line(person: Employee, email: bool = True) -> str:
    return f"{person.full_name}\t{person.email or ''}" if email else person.full_name


def _in_code_order(user: User, people: dict[str, Employee], keys: tuple[str, ...]) -> list[str]:
    """The keys in the order the report shows them when sorted by code (the same pipeline the copy uses)."""
    person = staff_list.REPORT.person
    assert person is not None
    table = build_table(staff_list.REPORT, user, Filters(state="all", sort="code"))
    position = {person(row): i for i, row in enumerate(table.rows)}
    return sorted(keys, key=lambda k: position[people[k].pk])


def test_names_and_emails_in_report_order_whatever_the_posting_order(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    expected = "\n".join(_line(people[k]) for k in _in_code_order(hr_user, people, ("A", "C")))
    forward = _post(client, hr_user, query=BY_CODE, ids=[str(people["A"].pk), str(people["C"].pk)])
    backward = _post(client, hr_user, query=BY_CODE, ids=[str(people["C"].pk), str(people["A"].pk)])
    assert forward.status_code == 200 and backward.status_code == 200
    assert forward.json()["text"] == expected
    assert backward.json()["text"] == expected
    assert forward.json()["count"] == 2 and forward.json()["dropped"] == 0


def test_control_characters_in_a_name_keep_one_line_per_person(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    Employee.objects.filter(pk=people["A"].pk).update(family_name="", given_name="Бат\x0bX Y\x1cZ\u0085W\tQ\r\nR")
    resp = _post(client, hr_user, ids=[str(people["A"].pk), str(people["B"].pk)])
    assert resp.status_code == 200
    text = resp.json()["text"]
    assert len(text.split("\n")) == 2  # two people, two lines
    assert text.split("\n")[0].startswith("Бат X Y Z W Q  R\t")  # \r and \n each become a space
    assert text.count("\t") == 2  # one tab per person, none from the name
    assert not any(ch in text for ch in "\x0b\x0c\x1c\x1d\x1e\x85  \r")


def test_copy_writes_one_audit_entry_and_none_on_a_refusal(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    _post(client, hr_user)  # nothing picked: refused
    assert not SystemLogEntry.objects.filter(action="copy_selected").exists()
    _post(client, hr_user, ids=[str(people["A"].pk), str(people["B"].pk)])
    [row] = list(SystemLogEntry.objects.filter(action="copy_selected"))
    assert row.category == "export" and row.actor == hr_user
    assert "2 мөр" in row.message


def test_text_is_one_line_per_person_with_tab_and_email(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    resp = _post(client, hr_user, query=BY_CODE, ids=[str(people["A"].pk), str(people["B"].pk)])
    lines = resp.json()["text"].split("\n")
    expected = [_line(people[k]) for k in _in_code_order(hr_user, people, ("A", "B"))]
    assert lines == expected  # code order, fixed by the sort
    assert all(line.count("\t") == 1 for line in lines)  # B has no email: its tab stays


@pytest.mark.parametrize(("needs", "shown"), [("", True), (PERSONAL, True), (SALARY, False)])
def test_email_only_when_the_user_may_see_the_email_column(
    client: Client,
    hr_user: User,
    people: dict[str, Employee],
    monkeypatch: pytest.MonkeyPatch,
    needs: str,
    shown: bool,
) -> None:
    report = staff_list.REPORT
    columns = tuple(replace(c, needs=needs) if c.key == "email" else c for c in report.columns)
    monkeypatch.setitem(REPORTS, "staff-list", replace(report, columns=columns))
    resp = _post(client, hr_user, ids=[str(people["A"].pk)])
    assert resp.status_code == 200
    assert resp.json()["text"] == _line(people["A"], email=shown)


def test_forged_id_outside_scope_is_dropped_and_counted(
    client: Client, scoped: User, people: dict[str, Employee]
) -> None:
    resp = _post(client, scoped, ids=[str(people["A"].pk), str(people["D"].pk)])
    assert resp.status_code == 200
    assert resp.json() == {"text": _line(people["A"]), "count": 1, "dropped": 1}


def test_id_hidden_by_a_filter_is_dropped_and_counted(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    query = to_query(Filters(state="all", department=people["A"].department_id))  # D is in another department
    resp = _post(client, hr_user, query=query, ids=[str(people["A"].pk), str(people["D"].pk)])
    assert resp.status_code == 200
    assert resp.json() == {"text": _line(people["A"]), "count": 1, "dropped": 1}


def test_garbage_and_duplicate_ids_are_ignored(client: Client, hr_user: User, people: dict[str, Employee]) -> None:
    ids = ["abc", "-5", "", str(people["A"].pk), str(people["A"].pk)]
    resp = _post(client, hr_user, ids=ids)
    assert resp.status_code == 200
    assert resp.json() == {"text": _line(people["A"]), "count": 1, "dropped": 0}


def test_empty_selection_is_400_with_the_message(client: Client, hr_user: User, people: dict[str, Employee]) -> None:
    resp = _post(client, hr_user)
    assert resp.status_code == 400
    assert resp["Content-Type"].startswith("text/plain")
    assert resp.content.decode() == selection.NOTHING_PICKED


def test_get_is_405(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)
    assert client.get(COPY).status_code == 405


def test_user_without_report_access_is_403(client: Client, people: dict[str, Employee]) -> None:
    no_access = _make_user("Employee", "no-report-copy")  # the Employee role may not open reports
    assert _post(client, no_access, ids=[str(people["A"].pk)]).status_code == 403


def test_report_without_person_is_404(client: Client, hr_user: User, fake_report: Any) -> None:
    client.force_login(hr_user)
    assert client.post("/reports/fake/selected/copy/", {"ids": ["1"]}).status_code == 404


def test_no_allowed_name_column_is_400_with_the_message(
    client: Client, hr_user: User, people: dict[str, Employee], monkeypatch: pytest.MonkeyPatch
) -> None:
    report = staff_list.REPORT
    columns = tuple(replace(c, needs=SALARY) if c.key == "name" else c for c in report.columns)
    monkeypatch.setitem(REPORTS, "staff-list", replace(report, columns=columns))
    resp = _post(client, hr_user, ids=[str(people["A"].pk)])
    assert resp.status_code == 400
    assert resp.content.decode() == selection_views.NO_NAME_COLUMN
