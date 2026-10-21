"""The order register (Тушаалын бүртгэл) and its print view."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from macs.models import Command, Employee

from employees.models import CompanySettings, HrOrder, OrderState, OrderType
from employees.services import macs_writes

from .conftest import link_login
from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


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


def test_register_lists_info_hr_and_legacy_orders(hr: Client, hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    make_order(hired, "15", date(2026, 3, 1))
    Command.objects.create(employee_id=hired.pk, number="А/99", date=date(2025, 2, 2), summary="Хуучин тушаал")
    resp = hr.get("/employees/orders/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Тушаал 15" in body
    assert "Хуучин тушаал" in body
    assert "Хуучин програм" in body
    assert "Хуучин програм" in body and "Бүртгэсэн" in body
    from employees.services.order_register import register_rows

    user = User.objects.get(username="hr1")
    states = {
        r.number: r.state for r in register_rows(user, year=None, order_type=None, department_id=None, state=None)
    }
    assert states == {"15": "registered", "А/99": "legacy"}


def test_linked_command_not_listed_twice(hr: Client, hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    cmd = Command.objects.create(employee_id=hired.pk, number="7", date=date(2026, 1, 1), summary="x")
    make_order(hired, "7", date(2026, 1, 1), command_id=cmd.pk)
    from employees.services.order_register import register_rows

    user = User.objects.get(username="hr1")
    assert len(register_rows(user, year=None, order_type=None, department_id=None, state=None)) == 1


def test_register_filters(hr: Client, hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    make_order(hired, "1", date(2025, 1, 1), OrderType.POSITION, summary="Эхний")
    make_order(hired, "2", date(2026, 1, 1), OrderType.FIRED, summary="Хоёр", state=OrderState.SIGNED)
    Command.objects.create(employee_id=hired.pk, number="L1", date=date(2026, 6, 1), summary="Хуучин нэг", order_type=3)

    def get(q: dict[str, str]) -> str:
        return hr.get("/employees/orders/", q).content.decode()

    assert "Хоёр" in get({"year": "2026"}) and "Эхний" not in get({"year": "2026"})
    assert "Эхний" in get({"order_type": str(OrderType.POSITION)})
    assert "Хоёр" not in get({"order_type": str(OrderType.POSITION)})
    assert "Хуучин нэг" in get({"order_type": "3"})
    assert "Хоёр" in get({"state": "signed"}) and "Эхний" not in get({"state": "signed"})
    assert "Хуучин нэг" in get({"state": "legacy"}) and "Хоёр" not in get({"state": "legacy"})
    assert "Эхний" in get({"department": str(hired.department_id)})
    assert "Эхний" not in get({"department": str((hired.department_id or 0) + 999)})
    bad = hr.get("/employees/orders/", {"year": "abc", "department": "x", "order_type": "!", "state": "zzz"})
    assert bad.status_code == 200  # bad values are ignored, never a 500
    assert "Эхний" in bad.content.decode() and "Хоёр" in bad.content.decode()


def test_register_hides_invisible_employees(client: Client, hired: Employee, actor: User) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    make_order(hired, "1", date(2026, 1, 1), summary="Тусдаа")
    other = macs_writes.create_employee(
        {"family_name": "Бат", "given_name": "Дорж", "register_no": "УБ11223344"}, {}, code="E9", by=actor
    )
    make_order(other, "2", date(2026, 1, 2), summary="Миний")
    user = User.objects.create_user("plain", password="x-long-pass-123")  # noqa: S106
    link_login(other, user)
    client.force_login(user)
    body = client.get("/employees/orders/").content.decode()
    assert "Миний" in body and "Тусдаа" not in body


def test_print_grouped_by_department_with_age_column(hr: Client, hired: Employee, settings: Any) -> None:
    CompanySettings.objects.update_or_create(pk=1, defaults={"name": "Инфо ХХК"})
    HrOrder.objects.filter(employee=hired).delete()
    make_order(hired, "15", date(2026, 3, 1))
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
def test_out_of_range_filters_are_ignored(hr: Client, hired: Employee, path: str, query: str) -> None:
    HrOrder.objects.filter(employee=hired).delete()
    make_order(hired, "15", date(2026, 3, 1), summary="Үлдэнэ")
    Command.objects.create(employee_id=hired.pk, number="L1", date=date(2025, 6, 1), summary="Хуучин үлдэнэ")
    resp = hr.get(f"{path}?{query}")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Үлдэнэ" in body and "Хуучин үлдэнэ" in body
