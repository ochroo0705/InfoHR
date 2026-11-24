"""GET /api/v1/slots and GET /api/v1/slots/options: the position-slot screen as the React page reads it.

Rows, counting and totals come from employees.services.slot_page; these tests pin the API's shape, its paging, its
year fallback and its rights (only holders of employees.manage_position_slots)."""

from datetime import date
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from config import batching
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import CompanySettings
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values
from macs.models import Branch, NazgRow, Position

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/slots"
OPTIONS_URL = "/api/v1/slots/options"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
FREE_NEGATIVE = "font-medium text-red-600"
FREE_ZERO = "text-amber-700"
TODAY = timezone.localdate()
YEAR = TODAY.year
HIRED_FROM = date(YEAR - 1, 1, 5)  # counted on every day of this year, so the tests do not depend on the date


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def hr() -> User:
    return _user("slots_api_hr", roles.HR)


@pytest.fixture
def position() -> Position:
    return macs_writes.save_position("Нягтлан")


@pytest.fixture
def job_values(position: Position) -> dict[str, Any]:
    return {
        "position": position,
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def _branch(name: str) -> Branch:
    return Branch.objects.create(name=name)


def _row(position: Position, branch: Branch, qty: int, *, kind: str = "Main", year: int = YEAR) -> NazgRow:
    return NazgRow.objects.create(kind=kind, qty=qty, year=year, position=position, branch=branch)


def _hire(actor: User, job_values: dict[str, Any], branch: Branch, n: int) -> None:
    values = {**hire_values(f"УБ9944{n:04d}"), "branch": branch}
    history.hire(values, {}, start=HIRED_FROM, job=job_values, salary=None, by=actor, with_order=False)


def test_list_requires_login_and_permission(hr: User) -> None:
    anonymous = Client().get(URL)
    assert anonymous.status_code == 401
    assert anonymous.json() == NOT_LOGGED_IN

    employee = _client(_user("slots_api_employee", roles.EMPLOYEE)).get(URL)
    assert employee.status_code == 403
    assert employee.json() == FORBIDDEN

    assert _client(hr).get(URL).status_code == 200


def test_list_rows_and_totals(hr: User, position: Position, job_values: dict[str, Any]) -> None:
    branch = _branch("Төв салбар")
    accountant = macs_writes.save_position("Бухгалтер")
    _row(position, branch, 2)
    _row(accountant, branch, 1, kind="Temporary")
    _hire(hr, job_values, branch, 1)

    body = _client(hr).get(URL).json()

    assert body["year"] == YEAR
    assert body["next_offset"] is None
    # ordered by position name: «Бухгалтер» before «Нягтлан»
    temporary, main = body["rows"]
    assert {k: v for k, v in main.items() if k != "id"} == {
        "position": "Нягтлан",
        "position_id": position.pk,
        "branch": "Төв салбар",
        "branch_id": branch.pk,
        "kind": "Main",
        "kind_label": "Үндсэн",
        "posts": 2,
        "used": 1,
        "free": 1,
        "free_class": "",
    }
    assert temporary["kind"] == "Temporary"
    assert temporary["kind_label"] == "Түр"
    assert temporary["used"] == 0
    assert body["totals"] == {"posts": 3, "used": 1, "free": 2}
    assert body["enforce"] is False
    assert body["settings_url"].startswith("/")
    assert body["empty_text"] == f"{YEAR} оны орон тоо бүртгэгдээгүй"


def test_totals_cover_rows_beyond_the_first_batch(
    hr: User, position: Position, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    for name in ("А салбар", "Б салбар", "В салбар"):
        _row(position, _branch(name), 1)

    body = _client(hr).get(URL).json()

    assert [r["branch"] for r in body["rows"]] == ["А салбар", "Б салбар"]
    assert body["next_offset"] == 2
    assert body["totals"] == {"posts": 3, "used": 0, "free": 3}


def test_next_batch_by_offset(hr: User, position: Position, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    for name in ("А салбар", "Б салбар", "В салбар"):
        _row(position, _branch(name), 1)
    client = _client(hr)

    second = client.get(URL, {"offset": "2"}).json()
    assert [r["branch"] for r in second["rows"]] == ["В салбар"]
    assert second["next_offset"] is None
    assert second["totals"] == {"posts": 3, "used": 0, "free": 3}

    bad = client.get(URL, {"offset": "-4"}).json()  # a bad offset starts at the first batch, never an error
    assert [r["branch"] for r in bad["rows"]] == ["А салбар", "Б салбар"]


def test_bad_year_falls_back_to_this_year(hr: User, position: Position) -> None:
    _row(position, _branch("Төв салбар"), 1, year=YEAR)
    client = _client(hr)

    for raw in ("abc", "99", "1999", "2101", "２０２６"):
        body = client.get(URL, {"year": raw}).json()
        assert body["year"] == YEAR, raw

    assert client.get(URL, {"year": "2024"}).json()["year"] == 2024


def test_free_class_for_negative_zero_positive(hr: User, position: Position, job_values: dict[str, Any]) -> None:
    over, exact, spare = _branch("А салбар"), _branch("Б салбар"), _branch("В салбар")
    _row(position, over, 1)  # two people, one post: negative
    _row(position, exact, 1)  # one person, one post: zero
    _row(position, spare, 2)  # one person, two posts: positive
    _hire(hr, job_values, over, 1)
    _hire(hr, job_values, over, 2)
    _hire(hr, job_values, exact, 3)
    _hire(hr, job_values, spare, 4)

    rows = {r["branch"]: r for r in _client(hr).get(URL).json()["rows"]}

    assert rows["А салбар"]["free"] == -1
    assert rows["А салбар"]["free_class"] == FREE_NEGATIVE
    assert rows["Б салбар"]["free"] == 0
    assert rows["Б салбар"]["free_class"] == FREE_ZERO
    assert rows["В салбар"]["free"] == 1
    assert rows["В салбар"]["free_class"] == ""


def test_enforce_flag_follows_company_settings(hr: User) -> None:
    client = _client(hr)
    assert client.get(URL).json()["enforce"] is False

    settings = CompanySettings.get()
    settings.enforce_position_slots = True
    settings.save()

    assert client.get(URL).json()["enforce"] is True


def test_options_lists_positions_branches_kinds(hr: User, position: Position) -> None:
    branch = _branch("Төв салбар")
    accountant = macs_writes.save_position("Бухгалтер")

    body = _client(hr).get(OPTIONS_URL, {"year": "2024"}).json()

    assert body["positions"] == [
        {"value": accountant.pk, "label": "Бухгалтер"},
        {"value": position.pk, "label": "Нягтлан"},
    ]
    assert body["branches"] == [{"value": branch.pk, "label": "Төв салбар"}]
    assert body["kinds"] == [{"value": "Main", "label": "Үндсэн"}, {"value": "Temporary", "label": "Түр"}]
    assert body["year"] == 2024
    assert body["min_year"] == 2000
    assert body["max_year"] == 2100
    assert body["hint"] == "Нэг албан тушаал, салбар, төрөл, оны хувьд нэг мөр байна."


def test_options_say_position_and_branch_are_addable(hr: User) -> None:
    # The pop-up's selects take a new entry (the Django SlotForm is marked by mark_addable): the payload says so.
    body = _client(hr).get(OPTIONS_URL, {"year": "2024"}).json()

    assert body["add_position"] == {"slug": "position", "modal": False, "parent": None}
    assert body["add_branch"] == {"slug": "branch", "modal": False, "parent": None}


def test_options_requires_login_and_permission() -> None:
    assert Client().get(OPTIONS_URL).status_code == 401
    employee = _client(_user("slots_api_employee2", roles.EMPLOYEE)).get(OPTIONS_URL)
    assert employee.status_code == 403
    assert employee.json()["code"] == "forbidden"
