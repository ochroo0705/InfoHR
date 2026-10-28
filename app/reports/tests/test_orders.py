from collections.abc import Callable
from datetime import date

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee, HrOrder

from reports.filters import Filters
from reports.orders import REPORT
from reports.table import build_table

pytestmark = pytest.mark.django_db


def test_orders_in_period_with_type_label(hr_user: User, hired: Employee) -> None:
    HrOrder.objects.filter(employee=hired, is_hire=True).update(number="12", date=date(2026, 1, 5), state="registered")
    got = REPORT.rows(hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)))
    assert [r.number for r in got] == ["12"]
    table = build_table(REPORT, hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)))
    by_key = dict(zip([c.key for c in table.columns], table.groups[0][1][0], strict=True))
    assert by_key["type"].value == "Ажилд орсон"


def test_undated_and_out_of_period_orders_left_out(hr_user: User, hired: Employee) -> None:
    year = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
    order = HrOrder.objects.filter(employee=hired, is_hire=True)
    order.update(number="12", state="registered", date=None)
    assert REPORT.rows(hr_user, year) == []
    order.update(date=date(2025, 12, 31))  # the day before the period
    assert REPORT.rows(hr_user, year) == []
    order.update(date=date(2026, 1, 5))
    assert [r.number for r in REPORT.rows(hr_user, year)] == ["12"]


def test_employee_role_cannot_open_orders(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "own")
    assert client.get("/reports/orders/").status_code == 403


def test_register_page_links_to_report(client: Client, login_hr: User) -> None:
    assert "/reports/orders/" in client.get("/employees/orders/").content.decode()
