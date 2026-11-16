"""The order register (Тушаалын бүртгэл) and its print view."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from macs.models import Command, Employee

from employees.models import CompanySettings, HrOrder, OrderState, OrderType
from employees.services import history, macs_writes
from employees.services.order_register import register_page, register_rows

from .conftest import hire_values, link_login
from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


@pytest.fixture
def bare(actor: User, job_values: dict[str, Any]) -> Employee:
    """An employee hired without an order, so the register holds only the orders a test makes itself."""
    return history.hire(
        hire_values("УБ99112290"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=actor,
        with_order=False,
    )


def make_order(emp: Employee, number: str, day: date, order_type: int = OrderType.POSITION, **extra: Any) -> HrOrder:
    return HrOrder.objects.create(
        employee=emp,
        is_hire=True,
        order_type=order_type,
        state=extra.pop("state", OrderState.REGISTERED),
        number=number,
        date=day,
        summary=extra.pop("summary", "Тушаал " + number),
        **extra,
    )


def test_register_lists_info_hr_and_legacy_orders(hr: Client, bare: Employee) -> None:
    make_order(bare, "15", date(2026, 3, 1))
    Command.objects.create(employee_id=bare.pk, number="А/99", date=date(2025, 2, 2), summary="Хуучин тушаал")
    resp = hr.get("/employees/orders/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Тушаал 15" in body
    assert "Хуучин тушаал" in body
    assert "MACS" in body
    assert "MACS" in body and "Бүртгэсэн" in body
    from employees.services.order_register import register_rows

    user = User.objects.get(username="hr1")
    states = {
        r.number: r.state for r in register_rows(user, year=None, order_type=None, department_id=None, state=None)
    }
    assert states == {"15": "registered", "А/99": "legacy"}


def test_linked_command_not_listed_twice(hr: Client, bare: Employee) -> None:
    cmd = Command.objects.create(employee_id=bare.pk, number="7", date=date(2026, 1, 1), summary="x")
    make_order(bare, "7", date(2026, 1, 1), command_id=cmd.pk)
    from employees.services.order_register import register_rows

    user = User.objects.get(username="hr1")
    assert len(register_rows(user, year=None, order_type=None, department_id=None, state=None)) == 1


def test_register_filters(hr: Client, bare: Employee) -> None:
    make_order(bare, "1", date(2025, 1, 1), OrderType.POSITION, summary="Эхний")
    make_order(bare, "2", date(2026, 1, 1), OrderType.FIRED, summary="Хоёр", state=OrderState.SIGNED)
    Command.objects.create(employee_id=bare.pk, number="L1", date=date(2026, 6, 1), summary="Хуучин нэг", order_type=3)

    def get(q: dict[str, str]) -> str:
        return hr.get("/employees/orders/", q).content.decode()

    assert "Хоёр" in get({"year": "2026"}) and "Эхний" not in get({"year": "2026"})
    assert "Эхний" in get({"order_type": str(OrderType.POSITION)})
    assert "Хоёр" not in get({"order_type": str(OrderType.POSITION)})
    assert "Хуучин нэг" in get({"order_type": "3"})
    assert "Хоёр" in get({"state": "signed"}) and "Эхний" not in get({"state": "signed"})
    assert "Хуучин нэг" in get({"state": "legacy"}) and "Хоёр" not in get({"state": "legacy"})
    assert "Эхний" in get({"department": str(bare.department_id)})
    assert "Эхний" not in get({"department": str((bare.department_id or 0) + 999)})
    bad = hr.get("/employees/orders/", {"year": "abc", "department": "x", "order_type": "!", "state": "zzz"})
    assert bad.status_code == 200  # bad values are ignored, never a 500
    assert "Эхний" in bad.content.decode() and "Хоёр" in bad.content.decode()


def test_register_hides_invisible_employees(client: Client, bare: Employee, actor: User) -> None:
    make_order(bare, "1", date(2026, 1, 1), summary="Тусдаа")
    other = macs_writes.create_employee(
        {"family_name": "Бат", "given_name": "Дорж", "register_no": "УБ11223344"}, {}, code="E9", by=actor
    )
    make_order(other, "2", date(2026, 1, 2), summary="Миний")
    user = User.objects.create_user("plain", password="x-long-pass-123")  # noqa: S106
    link_login(other, user)
    client.force_login(user)
    body = client.get("/employees/orders/").content.decode()
    assert "Миний" in body and "Тусдаа" not in body


def test_print_grouped_by_department_with_age_column(hr: Client, bare: Employee, settings: Any) -> None:
    CompanySettings.objects.update_or_create(pk=1, defaults={"name": "Инфо ХХК"})
    make_order(bare, "15", date(2026, 3, 1))
    body = hr.get("/employees/orders/print/").content.decode()
    assert "Хүний нөөцийн тушаалууд" in body
    assert "Инфо ХХК" in body
    assert "Хэлтэс: Санхүү" in body
    assert "Нас" in body
    assert body.count("Хүйс") == 1
    assert "Хүний нөөцийн мэргэжилтэн" in body
    assert "<nav" not in body


@pytest.mark.parametrize("path", ["/employees/orders/", "/employees/orders/print/"])
@pytest.mark.parametrize(
    "query", ["year=0", "year=10000", "year=99999999999", "department=999999999999", "order_type=999999999999"]
)
def test_out_of_range_filters_are_ignored(hr: Client, bare: Employee, path: str, query: str) -> None:
    make_order(bare, "15", date(2026, 3, 1), summary="Үлдэнэ")
    Command.objects.create(employee_id=bare.pk, number="L1", date=date(2025, 6, 1), summary="Хуучин үлдэнэ")
    resp = hr.get(f"{path}?{query}")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Үлдэнэ" in body and "Хуучин үлдэнэ" in body


def test_order_number_shows_its_year_in_list_and_detail(hr: Client, bare: Employee) -> None:
    order = make_order(bare, "1", date(2026, 1, 9))
    body = hr.get("/employees/orders/").content.decode()
    assert "№ 1 / 2026" in body
    assert ">Тушаалын огноо<" in body  # the date column header
    detail = hr.get(reverse("employees:order_detail", args=[bare.pk, order.pk])).content.decode()
    assert "№ 1 / 2026" in detail
    assert "Хүчинтэй огноо" in detail


def test_order_year_shows_on_the_work_tab_and_other_orders(hr: Client, bare: Employee) -> None:
    make_order(bare, "7", date(2026, 2, 3))  # no change behind it: listed under «Бусад тушаал»
    body = hr.get(reverse("employees:detail", args=[bare.pk])).content.decode()
    assert "№ 7 / 2026" in body


def _numbers(sort: str) -> list[str]:
    user = User.objects.get(username="hr1")
    return [
        r.number for r in register_rows(user, year=None, order_type=None, department_id=None, state=None, sort=sort)
    ]


def test_register_sort_by_date_oldest_first_and_default_newest_first(hr: Client, bare: Employee) -> None:
    make_order(bare, "1", date(2026, 1, 1))
    make_order(bare, "2", date(2026, 3, 1))
    assert _numbers("date") == ["1", "2"]
    assert _numbers("-date") == ["2", "1"]
    assert _numbers("bogus") == ["2", "1"]  # an unknown value is the default
    user = User.objects.get(username="hr1")
    page, more = register_page(
        user, year=None, order_type=None, department_id=None, state=None, offset=0, size=1, sort="date"
    )
    assert [r.number for r in page] == ["1"] and more


def test_register_sort_by_employee_name_ascending(hr: Client, bare: Employee, actor: User) -> None:
    other = macs_writes.create_employee(
        {"family_name": "Ааа", "given_name": "Дорж", "register_no": "УБ55667788"}, {}, code="E10", by=actor
    )
    make_order(bare, "1", date(2026, 1, 1))
    make_order(other, "2", date(2026, 1, 2))
    user = User.objects.get(username="hr1")
    names = [
        r.employee_name
        for r in register_rows(user, year=None, order_type=None, department_id=None, state=None, sort="employee")
    ]
    assert len(set(names)) == 2 and names == sorted(names)
    desc = [
        r.employee_name
        for r in register_rows(user, year=None, order_type=None, department_id=None, state=None, sort="-employee")
    ]
    assert desc == names[::-1]


def test_orders_page_sort_marks_the_active_header(hr: Client, bare: Employee) -> None:
    make_order(bare, "1", date(2026, 1, 1))
    resp = hr.get("/employees/orders/", {"sort": "number"})
    assert resp.status_code == 200
    assert 'aria-sort="ascending"' in resp.content.decode()
    default = hr.get("/employees/orders/", {"sort": "bogus"}).content.decode()
    assert 'aria-sort="descending"' in default  # the date column, newest first


@pytest.mark.parametrize("sort", ["number", "-number", "employee", "-employee", "date", "-date"])
def test_register_batches_join_up_to_the_whole_register_in_every_sort(
    hr: Client, bare: Employee, actor: User, sort: str
) -> None:
    # «Цааш харуулах» batches must neither drop nor repeat a row, whatever the column: mixed-case and Cyrillic
    # names, an empty number and equal numbers included.
    other = macs_writes.create_employee(
        {"family_name": "өлзий", "given_name": "Бат", "register_no": "УБ55667789"}, {}, code="E11", by=actor
    )
    for i, (who, number) in enumerate([(bare, "10"), (other, "2"), (bare, ""), (other, "2"), (bare, "b7")]):
        make_order(who, number, date(2026, 1, 1 + i))
    user = User.objects.get(username="hr1")
    filters: dict[str, Any] = {"year": None, "order_type": None, "department_id": None, "state": None, "sort": sort}
    whole = register_rows(user, **filters)
    joined, offset, more = [], 0, True
    while more:
        batch, more = register_page(user, **filters, offset=offset, size=2)
        joined += batch
        offset += 2
    assert [(r.order_id, r.command_id) for r in joined] == [(r.order_id, r.command_id) for r in whole]


def test_number_sort_reads_digits_as_numbers_and_ignores_case() -> None:
    from employees.services.order_register import _natural

    numbers = ["10/2026", "2/2026", "Б/9", "б/10", ""]
    assert sorted(numbers, key=_natural) == ["", "2/2026", "10/2026", "Б/9", "б/10"]
