"""Who may open the signed scan of an order (OQ-080): a hire or rehire order shows the salary, so it needs
macs.view_salary; other orders keep the visible-employee rule. The data scope still applies first (404)."""

from datetime import date
from decimal import Decimal

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from macs.models import Branch, FiredReason

from employees.models import Employee, HrOrder, OrderState, OrderType
from employees.services import macs_writes, orders
from employees.tests.conftest import link_login, named
from employees.tests.helpers import record_signed
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n%test\n"


def scan_url(emp: Employee, order: HrOrder) -> str:
    return f"/employees/{emp.pk}/order/{order.pk}/file/"


def detail_url(emp: Employee, order: HrOrder) -> str:
    return f"/employees/{emp.pk}/order/{order.pk}/detail/"


def as_user(role: str, name: str) -> Client:
    client = Client()
    login_as(client, role, name)
    return client


def signed_hire(emp: Employee, actor: User) -> HrOrder:
    order = HrOrder.objects.get(employee=emp, is_hire=True)
    orders.register(order, number="15", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    order.refresh_from_db()
    orders.attach_signed_file(order, SimpleUploadedFile("scan.pdf", PDF, content_type="application/pdf"), by=actor)
    order.refresh_from_db()
    return order


def test_hr_cannot_open_a_hire_scan_and_sees_no_link(hired: Employee, actor: User) -> None:
    order = signed_hire(hired, actor)
    hr = as_user("HR", "hr_scan")  # HR holds view_employees, not view_salary
    assert hr.get(scan_url(hired, order)).status_code == 403
    body = hr.get(detail_url(hired, order)).content.decode()
    assert scan_url(hired, order) not in body
    assert "Цалингийн эрх шаардлагатай" in body
    assert scan_url(hired, order) not in hr.get(f"/employees/{hired.pk}/").content.decode()


def test_hr_sees_the_same_placeholder_with_or_without_a_scan(hired: Employee, actor: User) -> None:
    """The detail page does not reveal whether a scan exists: HR gets the same placeholder before and after one."""
    hr = as_user("HR", "hr_placeholder")
    pending = HrOrder.objects.get(employee=hired, is_hire=True)  # no file yet
    before = hr.get(detail_url(hired, pending)).content.decode()
    assert "Цалингийн эрх шаардлагатай" in before and "хавсаргаагүй" not in before
    order = signed_hire(hired, actor)  # the same order, now with a scan
    after = hr.get(detail_url(hired, order)).content.decode()
    assert "Цалингийн эрх шаардлагатай" in after and "хавсаргаагүй" not in after
    assert scan_url(hired, order) not in after


def test_unclaimed_hire_scan_sits_in_other_orders(hired: Employee, actor: User) -> None:
    """The gate at _orders.html line 17: an order that no change row claims sits in «Бусад тушаал», and its scan link
    follows the same rule. The model allows an unclaimed order only as a hire order (an order with no event must be a
    hire), so the case is built by hand: the hire job claims the newer order, and this older one stays unclaimed."""
    extra = HrOrder.objects.create(
        employee=hired,
        is_hire=True,
        order_type=OrderType.HIRED,
        state=OrderState.SIGNED,
        number="9",
        date=date(2025, 12, 1),
        file=ContentFile(PDF, name="old-scan.pdf"),
    )
    hr_body = as_user("HR", "hr_other").get(f"/employees/{hired.pk}/").content.decode()
    assert f'id="order-{extra.pk}"' in hr_body  # listed under other orders
    assert scan_url(hired, extra) not in hr_body  # but no scan link for HR
    acc_body = as_user("Accountant", "acc_other").get(f"/employees/{hired.pk}/").content.decode()
    assert f'id="order-{extra.pk}"' in acc_body
    assert scan_url(hired, extra) in acc_body


def test_accountant_opens_a_hire_scan_and_sees_the_link(hired: Employee, actor: User) -> None:
    order = signed_hire(hired, actor)
    accountant = as_user("Accountant", "acc_scan")  # view_employees and view_salary
    got = accountant.get(scan_url(hired, order))
    assert got.status_code == 200 and b"".join(got.streaming_content) == PDF  # type: ignore[attr-defined]
    assert scan_url(hired, order) in accountant.get(detail_url(hired, order)).content.decode()


def test_hr_opens_a_scan_of_a_non_salary_order(hired: Employee, actor: User) -> None:
    position = macs_writes.save_position("Ахлах нягтлан")
    record_signed(
        hired,
        type="promotion",
        effective=date(2026, 3, 1),
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    order = HrOrder.objects.get(employee=hired, event__type="promotion")
    assert (order.is_hire, order.order_type) == (False, OrderType.POSITION) and order.file
    got = as_user("HR", "hr_position").get(scan_url(hired, order))  # the helper signs with its own PDF bytes
    assert got.status_code == 200 and b"".join(got.streaming_content).startswith(b"%PDF-")  # type: ignore[attr-defined]


def test_rehire_scan_needs_the_salary_right(hired: Employee, actor: User) -> None:
    fired = named(FiredReason, "Өөрийн хүсэлтээр")
    record_signed(
        hired,
        type="termination",
        effective=date(2026, 3, 1),
        fired_reason=fired,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    position = macs_writes.save_position("Ахлах")
    record_signed(
        hired,
        type="rehire",
        effective=date(2026, 5, 1),
        changes={"position": position},
        salary=Decimal("3100000"),
        reason="",
        note="",
        by=actor,
    )
    # The code: a rehire order is not is_hire, but it is OrderType.HIRED, and the rehire records a salary.
    order = HrOrder.objects.get(employee=hired, event__type="rehire")
    assert (order.is_hire, order.order_type) == (False, OrderType.HIRED) and order.file
    assert as_user("HR", "hr_rehire").get(scan_url(hired, order)).status_code == 403
    assert as_user("Accountant", "acc_rehire").get(scan_url(hired, order)).status_code == 200


def test_out_of_scope_scan_is_404_even_with_the_salary_right(hired: Employee, actor: User) -> None:
    order = signed_hire(hired, actor)
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    user = User.objects.create_user("acc_limited", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name="Accountant"))
    AccessScope.objects.create(user=user, limited=True, branch_ids=[north.pk])
    client = Client()
    client.force_login(User.objects.get(pk=user.pk))

    Employee.objects.filter(pk=hired.pk).update(branch_id=south.pk)
    assert client.get(scan_url(hired, order)).status_code == 404  # outside the scope: the scope answers first
    Employee.objects.filter(pk=hired.pk).update(branch_id=north.pk)
    assert client.get(scan_url(hired, order)).status_code == 200  # the control: inside the scope


def test_employee_refused_on_own_hire_scan(hired: Employee, actor: User) -> None:
    order = signed_hire(hired, actor)
    client = Client()
    link_login(hired, login_as(client, "Employee", "me"))
    assert client.get(scan_url(hired, order)).status_code == 403
