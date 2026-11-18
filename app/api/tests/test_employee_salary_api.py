"""GET /api/v1/employees/{pk}/salary: the Salary tab's pay, history rows, rights and bank block."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.utils import timezone
from employees.models import Employee, Event, EventType, SalaryRecord
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, link_login
from macs.models import Bank, InsuredCategory

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
FUTURE = date(2030, 1, 1)
BANK_LABELS = [
    "Банк",
    "Дансны дугаар",
    "НДД",
    "ЭМДД",
    "Даатгуулагчийн төрөл",
    "ТТД",
    "Хөгжлийн бэрхшээл",
]


@pytest.fixture
def salary_user(db: None) -> User:
    """An administrator: may view and manage salary, and sees every employee."""
    user = User.objects.create_user("employee_salary_admin", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.ADMIN)[0])
    return user


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(salary_user: User, job_values: dict[str, Any]) -> Employee:
    """A working employee hired on 2026-01-05 at 2,500,000₮."""
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=salary_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _body(user: User, employee: Employee) -> dict[str, Any]:
    response = _client(user).get(f"/api/v1/employees/{employee.pk}/salary")
    assert response.status_code == 200
    return response.json()


def test_salary_without_the_salary_right_is_403(hired: Employee) -> None:
    viewer = User.objects.create_user("employee_salary_plain", password=PASSWORD)
    link_login(hired, viewer)  # the own record is visible; no salary right is granted
    assert _client(viewer).get(f"/api/v1/employees/{hired.pk}/salary").status_code == 403


def test_salary_outside_the_scope_is_404(hired: Employee) -> None:
    accountant = User.objects.create_user("employee_salary_scoped", password=PASSWORD)
    accountant.groups.add(Group.objects.get_or_create(name=roles.ACCOUNTANT)[0])  # the admin group is never limited
    AccessScope.objects.create(user=accountant, limited=True)  # a limited scope with no branch, department or team
    assert _client(accountant).get(f"/api/v1/employees/{hired.pk}/salary").status_code == 404


def test_unknown_pk_is_404(salary_user: User) -> None:
    assert _client(salary_user).get("/api/v1/employees/999999/salary").status_code == 404


def test_current_salary_is_mnt_of_the_base_salary(salary_user: User, hired: Employee) -> None:
    body = _body(salary_user, hired)
    assert body["current"] == "2,500,000₮"
    assert body["missing_label"] == ""
    assert body["has_rows"] is True


def test_can_set_only_without_rows_and_with_the_right(salary_user: User, hired: Employee) -> None:
    assert _body(salary_user, hired)["can_set"] is False
    assert _body(salary_user, hired)["set_label"] == ""
    SalaryRecord.objects.filter(employee=hired).delete()  # no pay history left; MACS pay still shows as current
    body = _body(salary_user, hired)
    assert body["rows"] == []
    assert body["has_rows"] is False
    assert body["can_set"] is True
    assert body["set_label"] == "Цалин тогтоох"


def test_scheduled_cancellable_row_has_its_period_and_cancel_action(salary_user: User, hired: Employee) -> None:
    event = Event.objects.create(employee=hired, type=EventType.SALARY_CHANGE, effective=FUTURE, created_by=salary_user)
    history.change_salary(
        hired,
        effective=FUTURE,
        amount=Decimal("3000000"),
        change_type=EventType.SALARY_CHANGE.change_type,
        note="",
        by=salary_user,
        event=event,
    )
    Event.objects.filter(pk=event.pk).update(applied_at=timezone.now())
    body = _body(salary_user, hired)
    assert body["current"] == "2,500,000₮"  # the scheduled pay is not current yet
    future = next(row for row in body["rows"] if row["scheduled"])
    assert future["period_text"] == "2030-01-01 –"
    assert future["amount"] == "3,000,000₮"
    assert future["scheduled_label"] == "Төлөвлөсөн"
    assert future["event_id"] == event.pk
    assert future["cancellable"] is True
    assert future["correctable"] is False
    assert future["action_label"] == "Цуцлах"
    assert future["action_class"] == "rounded px-2 py-1 text-red-600 hover:bg-red-50"


def test_scheduled_row_without_an_event_is_correctable(salary_user: User, hired: Employee) -> None:
    history.change_salary(
        hired,
        effective=FUTURE,
        amount=Decimal("3000000"),
        change_type="correction",
        note="",
        by=salary_user,
    )
    body = _body(salary_user, hired)
    future = next(row for row in body["rows"] if row["scheduled"])
    assert future["event_id"] is None
    assert future["cancellable"] is False
    assert future["correctable"] is True
    assert future["action_label"] == "Засвар"
    assert future["action_class"] == "text-violet-700 hover:underline"


def test_past_open_row_is_correctable_and_not_cancellable(salary_user: User, hired: Employee) -> None:
    body = _body(salary_user, hired)
    past = next(row for row in body["rows"] if not row["scheduled"])
    assert past["scheduled_label"] == ""
    assert past["cancellable"] is False
    assert past["correctable"] is True
    assert past["action_label"] == "Засвар"
    assert past["action_class"] == "text-violet-700 hover:underline"
    assert past["period_text"].endswith(" одоо")


def test_bank_block_is_in_template_order_and_editable_for_managers(salary_user: User, hired: Employee) -> None:
    body = _body(salary_user, hired)
    assert body["editable"] is True
    assert [field["label"] for field in body["bank_fields"]] == BANK_LABELS
    disability = body["bank_fields"][-1]
    assert disability["kind"] == "checkbox"
    assert disability["text"] == "Үгүй"
    assert disability["aria_label"] == "Хөгжлийн бэрхшээлтэй"
    assert body["bank_fields"][2]["aria_label"] == "НДД-ийн дугаар"
    assert body["bank_fields"][3]["aria_label"] == "ЭМДД-ийн дугаар"
    assert body["bank_fields"][5]["aria_label"] == "Татвар төлөгчийн дугаар"
    assert disability["checked"] is False
    assert body["bank_fields"][0]["kind"] == "select"
    assert body["bank_fields"][0]["value"] == ""
    assert body["bank_fields"][0]["choice"] == "---------"  # no bank on file: Django's empty option
    assert body["bank_fields"][0]["text"] == "—"
    assert [field["kind"] for field in body["bank_fields"]] == [
        "select",
        "text",
        "text",
        "text",
        "select",
        "text",
        "checkbox",
    ]


def test_bank_and_category_are_selects_with_their_pk_and_name(salary_user: User, hired: Employee) -> None:
    bank = Bank.objects.create(name="Хаан банк")
    category = InsuredCategory.objects.create(name="Тест ангилал")
    Employee.objects.filter(pk=hired.pk).update(bank=bank, insured_category=category, account_no="5001234567")
    body = _body(salary_user, hired)
    bank_field, account_field, _, _, category_field, _, _ = body["bank_fields"]
    assert bank_field == {
        "name": "si-bank",
        "label": "Банк",
        "aria_label": "Банк",
        "kind": "select",
        "value": str(bank.pk),
        "choice": "Хаан банк",
        "text": "Хаан банк",
        "checked": False,
    }
    assert account_field["kind"] == "text"
    assert account_field["value"] == "5001234567"
    assert account_field["text"] == "5001234567"
    assert category_field["kind"] == "select"
    assert category_field["value"] == str(category.pk)
    assert category_field["choice"] == "Тест ангилал"


def test_view_only_salary_user_sees_the_bank_block_read_only(hired: Employee) -> None:
    viewer = User.objects.create_user("employee_salary_viewer", password=PASSWORD)
    viewer.groups.add(Group.objects.get_or_create(name=roles.HR)[0])  # sees the employee; HR has no salary right
    viewer.user_permissions.add(Permission.objects.get(content_type__app_label="macs", codename="view_salary"))
    body = _body(viewer, hired)
    assert body["current"] == "2,500,000₮"
    assert body["editable"] is False
    assert body["can_set"] is False
    assert body["set_label"] == ""
    assert [field["label"] for field in body["bank_fields"]] == BANK_LABELS
    assert body["bank_fields"][-1]["kind"] == "checkbox"
    assert all(row["correctable"] is False for row in body["rows"])
    assert all(row["action_label"] == "" for row in body["rows"])


BANK_NAMES = [
    "si-bank",
    "si-account_no",
    "si-social_insurance_no",
    "si-health_insurance_no",
    "si-insured_category",
    "si-taxpayer_no",
    "si-has_disability",
]


def test_bank_fields_carry_their_si_form_names_that_page_form_has(salary_user: User, hired: Employee) -> None:
    body = _client(salary_user).get(f"/api/v1/employees/{hired.pk}/salary").json()
    page = _client(salary_user).get(f"/api/v1/employees/{hired.pk}/page-form").json()
    form_names = {field["name"] for field in page["fields"]}
    assert [field["name"] for field in body["bank_fields"]] == BANK_NAMES
    for field in body["bank_fields"]:
        assert field["name"] in form_names
