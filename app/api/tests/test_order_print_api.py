"""GET /api/v1/orders/print: the order register's print page as the React page reads it.

Rows, filters and the department grouping come from the same services as the Django print page; these tests pin the
API's shape, the numbering that restarts in each group, the rights (any signed-in user, rows only inside the user's
scope), the one export log line and the no-store header."""

from datetime import date
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, SystemLogEntry, User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import CompanySettings, Employee, HrOrder, OrderState, OrderType
from employees.services import history, macs_writes
from employees.services.order_register import age_on
from employees.tests.conftest import hire_values
from macs.models import Branch

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/orders/print"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
BIRTH = date(1999, 11, 22)


def _user(name: str, group: str | None) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def hr() -> User:
    return _user("print_api_hr", roles.HR)


@pytest.fixture
def job_values() -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def bare(hr: User, job_values: dict[str, Any]) -> Employee:
    """An employee hired without an order, so a test adds only the orders it makes itself."""
    return history.hire(
        hire_values("УБ99112290"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=hr,
        with_order=False,
    )


def make_order(emp: Employee, number: str, day: date | None, **extra: Any) -> HrOrder:
    return HrOrder.objects.create(
        employee=emp,
        is_hire=True,
        order_type=extra.pop("order_type", OrderType.POSITION),
        state=extra.pop("state", OrderState.REGISTERED),
        number=number,
        date=day,
        summary=extra.pop("summary", "Тушаал " + number),
        **extra,
    )


def _get(client: Client, **params: str) -> Any:
    response = client.get(URL, params)
    assert response.status_code == 200, response.content.decode()
    return response.json()


def _print_rows() -> list[SystemLogEntry]:
    return list(SystemLogEntry.objects.filter(action="print_page").order_by("id"))


def test_print_requires_login(db: None) -> None:
    response = Client().get(URL)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_print_has_no_store_header(hr: User, bare: Employee) -> None:
    make_order(bare, "5", date(2026, 3, 1))
    response = _client(hr).get(URL)
    assert response.status_code == 200
    assert response.get("Cache-Control") == "no-store"


def test_print_empty_shape(hr: User) -> None:
    body = _get(_client(hr))
    assert body == {
        "company": CompanySettings.get().name,
        "today": timezone.localdate().isoformat(),
        "groups": [],
        "empty": True,
    }


def test_print_groups_and_numbering_restart_per_group(hr: User, bare: Employee, job_values: dict[str, Any]) -> None:
    marketing = history.hire(
        hire_values("УБ99112291"),
        {},
        start=date(2026, 1, 5),
        job={**job_values, "department": macs_writes.save_department("Маркетинг")},
        salary=None,
        by=hr,
        with_order=False,
    )
    make_order(bare, "1", date(2026, 3, 2))
    make_order(bare, "2", date(2026, 3, 1))
    make_order(marketing, "3", date(2026, 3, 1))

    body = _get(_client(hr))

    assert body["empty"] is False
    groups = {group["department"]: group["rows"] for group in body["groups"]}
    assert set(groups) == {"Санхүү", "Маркетинг"}
    assert [row["n"] for row in groups["Санхүү"]] == [1, 2]
    assert [row["number"] for row in groups["Санхүү"]] == ["2", "1"]  # sorted by date inside the group
    assert [row["n"] for row in groups["Маркетинг"]] == [1]


def test_print_row_fields(hr: User, bare: Employee) -> None:
    make_order(bare, "12", date(2026, 3, 1), summary="Албан тушаал өөрчлөлт")
    make_order(bare, "13", None)  # sorted last, shows an empty date
    body = _get(_client(hr))
    rows = body["groups"][0]["rows"]
    first, last = rows[0], rows[1]
    assert first == {
        "n": 1,
        "date": "2026-03-01",
        "employee_name": "Батын Сараа",
        "position": "Нягтлан",
        "number": "12",
        "summary": "Албан тушаал өөрчлөлт",
        "issued_by": "",
        "register_no": "УБ99112290",
        "gender": Employee.objects.get(pk=bare.pk).get_gender_display(),
        "age": str(age_on(BIRTH, timezone.localdate())),
    }
    assert last["n"] == 2
    assert last["date"] == ""


def test_print_logs_one_export_with_label_and_rows(hr: User, bare: Employee) -> None:
    make_order(bare, "20", date(2026, 3, 1))
    make_order(bare, "21", date(2026, 3, 2), state=OrderState.CANCELLED)

    response = _client(hr).get(URL, {"year": "2026", "q": "Батын"})
    assert response.status_code == 200
    assert len(response.json()["groups"][0]["rows"]) == 2  # no state filter: the cancelled order is listed too

    [row] = _print_rows()
    assert row.category == "export"
    assert row.actor == hr
    assert row.message == "Тушаалын бүртгэл · Он: 2026; Хайлт ашигласан · 2 мөр"
    assert "Батын" not in row.message


def test_print_does_not_log_when_refused(db: None) -> None:
    Client().get(URL)
    assert _print_rows() == []


def test_print_hides_people_outside_scope(hr: User, job_values: dict[str, Any]) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    inside = history.hire(
        {**hire_values("УБ00000011"), "family_name": "Дотно", "given_name": "Оюун"},
        {},
        start=date(2026, 1, 5),
        job=dict(job_values),
        salary=None,
        by=hr,
        with_order=False,
    )
    outside = history.hire(
        {**hire_values("УБ00000022"), "family_name": "Гадна", "given_name": "Мөнх"},
        {},
        start=date(2026, 1, 5),
        job=dict(job_values),
        salary=None,
        by=hr,
        with_order=False,
    )
    Employee.objects.filter(pk=inside.pk).update(branch_id=north.pk)
    Employee.objects.filter(pk=outside.pk).update(branch_id=south.pk)
    make_order(inside, "101", date(2026, 3, 1))
    make_order(outside, "102", date(2026, 3, 2))

    everyone = _get(_client(hr))
    names = [row["employee_name"] for group in everyone["groups"] for row in group["rows"]]
    assert "Гадна Мөнх" in names  # control

    limited = _user("print_api_limited", roles.HR)
    AccessScope.objects.create(user=limited, limited=True, branch_ids=[north.pk])
    limited = User.objects.get(pk=limited.pk)
    body = _get(_client(limited))
    names = [row["employee_name"] for group in body["groups"] for row in group["rows"]]
    assert "Дотно Оюун" in names
    assert all("Гадна" not in name for name in names)
