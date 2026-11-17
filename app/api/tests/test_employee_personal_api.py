"""GET /api/v1/employees/{pk}/personal: the personal tab's groups, field sections and lists (detail_page facts)."""

import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees.forms import EmployeeForm
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values
from macs.models import BeforeWorkRow, FamilyRelation, FamilyRow

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("employee_personal_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    return user


@pytest.fixture
def hired(hr_user: User) -> Employee:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _list(body: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(item for item in body["lists"] if item["kind"] == kind)


def test_accountant_without_the_personal_right_is_403(hired: Employee) -> None:
    accountant = User.objects.create_user("employee_personal_acc", password=PASSWORD)
    accountant.groups.add(Group.objects.get_or_create(name=roles.ACCOUNTANT)[0])  # sees employees, no personal right
    assert _client(accountant).get(f"/api/v1/employees/{hired.pk}/personal").status_code == 403


def test_unknown_pk_is_404(hr_user: User) -> None:
    assert _client(hr_user).get("/api/v1/employees/999999/personal").status_code == 404


def test_employee_outside_the_scope_is_404(hr_user: User, hired: Employee) -> None:
    AccessScope.objects.create(user=hr_user, limited=True)  # a limited scope with no branch, department or team
    assert _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").status_code == 404


def test_chips_hide_zero_counts_and_show_other_once_filled(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json()
    chips = [chip for group in body["groups"] for chip in group["chips"]]
    list_chips = [chip for chip in chips if chip["key"] != "other"]
    assert not any(chip["visible"] for chip in list_chips)  # an employee with no personal rows: every count is 0
    other = next(chip for chip in chips if chip["key"] == "other")
    assert other["count_text"].startswith("0/")  # nothing filled yet
    assert other["visible"] is False  # «Бусад мэдээлэл» stays hidden

    Employee.objects.filter(pk=hired.pk).update(prior_service_years=2)  # one field filled
    filled = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json()
    other = next(chip for group in filled["groups"] for chip in group["chips"] if chip["key"] == "other")
    assert other["visible"] is True
    assert not other["count_text"].startswith("0/")


def test_sections_and_lists_carry_their_group_and_parent(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json()
    groups = {section["name"]: section["group"] for section in body["sections"]}
    assert groups == {"identity": "basic", "contact": "basic", "education": "edu", "other": "other"}
    assert [lst["kind"] for lst in body["lists"]][:3] == ["address", "contact", "family"]  # template order
    address, contact = _list(body, "address"), _list(body, "contact")
    assert (address["group"], address["parent"]) == ("basic", "contact")
    assert (contact["group"], contact["parent"]) == ("basic", "contact")
    assert (_list(body, "family")["group"], _list(body, "family")["parent"]) == ("basic", None)
    assert (_list(body, "education")["group"], _list(body, "education")["parent"]) == ("edu", "education")
    assert (_list(body, "body")["group"], _list(body, "body")["parent"]) == ("health", None)
    assert _list(body, "gift")["group"] == "award"


def test_other_count_is_filled_over_total(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json()
    assert re.fullmatch(r"\d+/\d+", body["counts"]["other"])
    other_chip = next(chip for group in body["groups"] for chip in group["chips"] if chip["key"] == "other")
    assert other_chip["count_text"] == body["counts"]["other"]


def test_seeded_family_row_shows_its_display_values(hr_user: User, hired: Employee) -> None:
    relation = FamilyRelation.objects.create(name="Хүү", fm_type="son")
    FamilyRow.objects.create(
        employee=hired, relation=relation, given_name="Б", surname="Бат", birth_date=date(2015, 1, 1)
    )
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json()
    family = _list(body, "family")
    assert family["inline"] is True
    assert family["count"] == 1
    assert family["empty_label"] == ""
    assert [col["header"] for col in family["columns"]] == [
        "Хамаарал",
        "Овог",
        "Нэр",
        "Төрсөн огноо",
        "Ажил, албан тушаал",
        "Утас",
    ]
    assert family["rows"][0]["cells"] == ["Хүү", "Бат", "Б", "2015-01-01", "—", "—"]


def test_empty_table_list_has_no_rows_and_its_empty_line(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json()
    body_list = _list(body, "body")
    assert body_list["rows"] == []
    assert body_list["count"] == 0
    assert body_list["empty_label"] == "бүртгэгдээгүй"
    assert body_list["inline"] is False


def test_before_work_period_falls_back_to_the_years(hr_user: User, hired: Employee) -> None:
    BeforeWorkRow.objects.create(employee=hired, worked_place="Төмөр зам", start_year=2010, end_year=2015)
    BeforeWorkRow.objects.create(
        employee=hired, worked_place="Банк", start_text="2016.03", end_text="", start_year=2016, end_year=0
    )
    rows = _list(_client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json(), "before_work")["rows"]
    periods = {row["cells"][0]: row["cells"][2] for row in rows}
    assert periods["Төмөр зам"] == "2010 – 2015"  # no month text: the years
    assert periods["Банк"] == "2016.03 – …"  # the month text wins; an empty end shows «…»


def test_editable_sections_send_soft_fields_and_read_only_sends_rows(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/personal").json()
    assert body["editable"] is True
    identity = next(s for s in body["sections"] if s["name"] == "identity")
    assert identity["editable"] is True
    fields = {f["name"]: f for f in identity["fields"]}
    form = EmployeeForm(employee=hired, user=hr_user)

    register = fields["register_no"]  # a text box, value as stored, required as the form says
    assert register["kind"] == "text"
    assert register["value"] == "УБ99112233"
    assert register["required"] is bool(form.fields["register_no"].required)
    assert register["placeholder"] == "—"
    assert register["choices"] == []
    assert register["choice"] == ""

    birth_date = fields["birth_date"]  # a date box posts YYYY-MM-DD
    assert birth_date["kind"] == "date"
    assert birth_date["value"] == "1999-11-22"

    gender = fields["gender"]  # a select: the stored code is the value and is among the choices
    assert gender["kind"] == "select"
    assert gender["value"] == "F"
    assert "F" in {choice["value"] for choice in gender["choices"]}
    assert gender["placeholder"] == ""
    assert gender["choice"] == next(c["label"] for c in gender["choices"] if c["value"] == "F")
    assert gender["combo"] is (len(gender["choices"]) >= 8)  # a short list stays a native select (select.js)

    birth_city = fields["birth_city"]  # the birth place picker: data-placeholder, blank entry first, not required
    assert birth_city["kind"] == "select"
    assert birth_city["placeholder"] == "Аймаг, хот…"
    assert birth_city["choices"][0] == {"value": "", "label": birth_city["choices"][0]["label"]}
    assert birth_city["required"] is False
    assert birth_city["choice"] == ""  # nothing chosen: the box shows no text
    assert birth_city["combo"] is True  # many cities: a typing box, as select.js draws it
    assert fields["birth_district"]["placeholder"] == "Сум, дүүрэг…"
    assert fields["birth_place_text"]["placeholder"] == "Тодруулга"

    reader = User.objects.create_user("employee_personal_reader", password=PASSWORD)
    reader.user_permissions.add(
        Permission.objects.get(content_type__app_label="macs", codename="view_personal"),
        Permission.objects.get(content_type__app_label="macs", codename="view_employees"),
    )
    read_body = _client(reader).get(f"/api/v1/employees/{hired.pk}/personal").json()
    assert read_body["editable"] is False
    read_identity = next(s for s in read_body["sections"] if s["name"] == "identity")
    assert read_identity["fields"] == []
    assert read_identity["rows"][0]["label"] == "Регистрийн дугаар"
