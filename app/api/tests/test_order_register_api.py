"""GET /api/v1/orders/register: the order register's batch as the React page reads it.

Rows, filters, paging and sort come from the same services as the Django page; these tests pin the API's shape and
its rights (any signed-in user, rows only inside the user's scope, pickable only for a manager)."""

from datetime import date, timedelta
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from config import batching
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees.models import Department, DepartmentExt, Employee, HrOrder, OrderState, OrderType
from employees.services import events, history, macs_writes
from employees.tests.conftest import hire_values
from employees.tests.helpers import next_order_number
from macs.models import Branch, Command

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/orders/register"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
REGISTERED_CHIP = "whitespace-nowrap rounded-full px-2 py-0.5 text-xs bg-sky-100 text-sky-900"
OTHER_CHIP = "whitespace-nowrap rounded-full px-2 py-0.5 text-xs bg-slate-200 text-slate-700"
LEGACY_CHIP = "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700"


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
    return _user("register_api_hr", roles.HR)


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


def test_register_requires_login(db: None) -> None:
    response = Client().get(URL)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_register_rows_shape_for_ours_and_legacy_row(hr: User, bare: Employee) -> None:
    order = make_order(bare, "12", date(2026, 3, 1))
    Command.objects.create(employee_id=bare.pk, number="А/99", date=date(2025, 2, 2), summary="Хуучин тушаал")
    body = _get(_client(hr))
    ours = next(r for r in body["rows"] if r["order_id"] == order.pk)
    assert ours == {
        "key": f"o{order.pk}",
        "order_id": order.pk,
        "employee_id": bare.pk,
        "number_label": "№ 12 / 2026",
        "date_label": "2026-03-01",
        "employee_name": "Батын Сараа",
        "department": "Санхүү",
        "summary": "Тушаал 12",
        "state": "registered",
        "state_label": "Бүртгэсэн",
        "chip_class": REGISTERED_CHIP,
        "awaiting": False,
        "cancelled": False,
        "pickable": True,
        "opens": "detail",
        "awaiting_chip": None,
        "number_muted": False,
    }
    legacy = next(r for r in body["rows"] if r["order_id"] is None)
    assert legacy == {
        "key": legacy["key"],
        "order_id": None,
        "employee_id": bare.pk,
        "number_label": "№ А/99 / 2025",
        "date_label": "2025-02-02",
        "employee_name": "Батын Сараа",
        "department": "Санхүү",
        "summary": "Хуучин тушаал",
        "state": "legacy",
        "state_label": "MACS",
        "chip_class": LEGACY_CHIP,
        "awaiting": False,
        "cancelled": False,
        "pickable": False,
        "opens": "employee",
        "awaiting_chip": None,
        "number_muted": False,
    }
    assert legacy["key"].startswith("c")


def test_register_row_without_number_shows_grey_dash(hr: User, bare: Employee) -> None:
    Command.objects.create(employee_id=bare.pk, number="", date=None, summary="Дугаargүй тушаал")
    body = _get(_client(hr))
    row = next(r for r in body["rows"] if r["summary"] == "Дугаargүй тушаал")
    assert row["number_label"] == "—"
    assert row["number_muted"] is True
    assert row["date_label"] == "—"


def test_register_awaiting_row_has_the_amber_chip_others_none(hr: User, bare: Employee) -> None:
    plain = make_order(bare, "30", date(2026, 3, 1))
    waiting = _waiting_promotion(bare, hr)
    body = _get(_client(hr))
    by_id = {r["order_id"]: r for r in body["rows"]}
    assert by_id[waiting.pk]["awaiting"] is True
    assert by_id[waiting.pk]["awaiting_chip"] == {
        "label": "Гарын үсэг хүлээж байна",
        "class_name": (
            "whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-900 "
            "no-underline"
        ),
    }
    assert by_id[plain.pk]["awaiting"] is False
    assert by_id[plain.pk]["awaiting_chip"] is None


def _waiting_promotion(employee: Employee, actor: User) -> HrOrder:
    """An order whose change (a promotion next month) waits for its signed order: the register shows the chip."""
    position = macs_writes.save_position("Дарга")
    events.record(
        employee,
        type="promotion",
        effective=date.today() + timedelta(days=30),
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        order_number=next_order_number(),
        by=actor,
    )
    return HrOrder.objects.get(employee=employee, state=OrderState.REGISTERED, event__isnull=False)


def test_register_labels_for_signed_and_undated_rows(hr: User, bare: Employee) -> None:
    signed = make_order(bare, "7", None, state=OrderState.SIGNED)
    body = _get(_client(hr))
    row = next(r for r in body["rows"] if r["order_id"] == signed.pk)
    assert row["number_label"] == "№ 7"
    assert row["date_label"] == "—"
    assert row["chip_class"] == "seal"


def test_register_other_states_get_the_grey_chip(hr: User, bare: Employee) -> None:
    make_order(bare, "8", date(2026, 3, 2), state=OrderState.CANCELLED)
    body = _get(_client(hr))
    row = body["rows"][0]
    assert row["chip_class"] == OTHER_CHIP
    assert row["cancelled"] is True


def test_register_next_offset_none_on_last_batch_and_set_when_more(
    hr: User, bare: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    for number in ("1", "2", "3"):
        make_order(bare, number, date(2026, 3, int(number)))
    client = _client(hr)
    first = _get(client)
    assert len(first["rows"]) == 2
    assert first["next_offset"] == 2
    second = _get(client, offset="2")
    assert len(second["rows"]) == 1
    assert second["next_offset"] is None
    assert second["background_from"] == 11


def test_register_bad_filter_values_are_ignored_and_echoed_clean(hr: User, bare: Employee) -> None:
    make_order(bare, "9", date(2026, 3, 3))
    body = _get(
        _client(hr), year="abc", order_type="99", department="x", state="bogus", q="  ", sort="evil", offset="-3"
    )
    assert body["query"] == {
        "year": None,
        "order_type": None,
        "department": None,
        "state": "",
        "q": "",
        "sort": "-date",
    }
    assert len(body["rows"]) == 1


def test_register_non_numeric_offset_starts_at_zero(hr: User, bare: Employee) -> None:
    make_order(bare, "10", date(2026, 3, 4))
    body = _get(_client(hr), offset="abc")
    assert len(body["rows"]) == 1


def test_register_valid_filters_are_echoed(hr: User, bare: Employee) -> None:
    make_order(bare, "11", date(2026, 3, 5))
    body = _get(_client(hr), year="2026", order_type=str(OrderType.POSITION), state="registered", q=" Батын ")
    assert body["query"]["year"] == 2026
    assert body["query"]["order_type"] == OrderType.POSITION
    assert body["query"]["state"] == "registered"
    assert body["query"]["q"] == "Батын"
    assert [r["number_label"] for r in body["rows"]] == ["№ 11 / 2026"]


def test_register_options_exclude_inactive_and_pending(hr: User, bare: Employee) -> None:
    inactive = Department.objects.create(name="Идэвхгүй хэлтэс")
    DepartmentExt.objects.create(department=inactive, active=False)
    body = _get(_client(hr))
    assert str(inactive.pk) not in [d["value"] for d in body["options"]["departments"]]
    assert "pending" not in [s["value"] for s in body["options"]["states"]]


def test_register_department_with_null_name_has_empty_label(hr: User, bare: Employee) -> None:
    nameless = Department.objects.create(name=None)
    body = _get(_client(hr))
    assert {"value": str(nameless.pk), "label": ""} in body["options"]["departments"]


def test_register_options_and_all_labels(hr: User, bare: Employee) -> None:
    body = _get(_client(hr))
    assert body["all_labels"] == {
        "year": "Бүх он",
        "order_type": "Бүх төрөл",
        "department": "Бүх хэлтэс",
        "state": "Бүх төлөв",
    }
    assert {"value": str(OrderType.POSITION), "label": "Албан тушаал сольсон"} in body["options"]["types"]
    assert {"value": "legacy", "label": "MACS"} in body["options"]["states"]
    assert "" not in [o["value"] for o in body["options"]["years"]]


def test_register_hides_people_outside_scope(hr: User, job_values: dict[str, Any]) -> None:
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
    Command.objects.create(employee_id=outside.pk, number="А/77", date=date(2025, 2, 2), summary="Гадны хуучин")

    everyone = _get(_client(hr))
    assert "Гадна Мөнх" in [r["employee_name"] for r in everyone["rows"]]  # control

    limited = _user("register_api_limited", roles.HR)
    AccessScope.objects.create(user=limited, limited=True, branch_ids=[north.pk])
    limited = User.objects.get(pk=limited.pk)
    body = _get(_client(limited))
    names = [r["employee_name"] for r in body["rows"]]
    assert "Дотно Оюун" in names
    assert all("Гадна" not in name for name in names)
    assert "Гадны хуучин" not in [r["summary"] for r in body["rows"]]


def test_register_pickable_only_for_manager_and_not_cancelled(hr: User, bare: Employee) -> None:
    registered = make_order(bare, "20", date(2026, 3, 1))
    cancelled = make_order(bare, "21", date(2026, 3, 2), state=OrderState.CANCELLED)
    manager = _get(_client(hr))
    by_id = {r["order_id"]: r for r in manager["rows"]}
    assert by_id[registered.pk]["pickable"] is True
    assert by_id[cancelled.pk]["pickable"] is False
    assert by_id[cancelled.pk]["opens"] == "detail"
    assert manager["can_manage"] is True

    accountant = _user("register_api_accountant", roles.ACCOUNTANT)
    body = _get(_client(accountant))
    assert body["can_manage"] is False
    assert all(r["pickable"] is False for r in body["rows"])


def test_register_sort_heads_flip_on_current_column(hr: User, bare: Employee) -> None:
    client = _client(hr)
    newest = _get(client)  # default: -date
    assert newest["sort_heads"]["date"] == {"next": "date", "arrow": "↓", "aria": "descending"}
    assert newest["sort_heads"]["number"] == {"next": "number", "arrow": "", "aria": ""}
    by_date = _get(client, sort="date")
    assert by_date["sort_heads"]["date"] == {"next": "-date", "arrow": "↑", "aria": "ascending"}
    by_number = _get(client, sort="-number")
    assert by_number["sort_heads"]["number"] == {"next": "number", "arrow": "↓", "aria": "descending"}
    assert by_number["sort_heads"]["date"] == {"next": "date", "arrow": "", "aria": ""}


def test_register_search_matches_number_and_name(hr: User, bare: Employee, job_values: dict[str, Any]) -> None:
    other = history.hire(
        {**hire_values("УБ99112291"), "family_name": "Дорж", "given_name": "Болд"},
        {},
        start=date(2026, 1, 5),
        job=dict(job_values),
        salary=None,
        by=hr,
        with_order=False,
    )
    make_order(bare, "15", date(2026, 3, 1))
    make_order(other, "27", date(2026, 3, 2))
    client = _client(hr)
    by_number = _get(client, q="15")
    assert [r["number_label"] for r in by_number["rows"]] == ["№ 15 / 2026"]
    by_name = _get(client, q="Дорж")
    assert [r["employee_name"] for r in by_name["rows"]] == ["Дорж Болд"]
    assert _get(client, q="zzzz-none")["rows"] == []


def test_register_report_link_needs_both_permissions(db: None) -> None:
    reports_only = _user("register_api_reports_only", None)
    reports_only.user_permissions.add(
        Permission.objects.get(codename="view_reports", content_type__app_label="reports")
    )
    reports_only = User.objects.get(pk=reports_only.pk)
    assert _get(_client(reports_only))["report_link"] is False

    both = _user("register_api_both", None)
    both.user_permissions.add(
        Permission.objects.get(codename="view_reports", content_type__app_label="reports"),
        Permission.objects.get(codename="view_employees", content_type__app_label="macs"),
    )
    both = User.objects.get(pk=both.pk)
    assert _get(_client(both))["report_link"] is True
