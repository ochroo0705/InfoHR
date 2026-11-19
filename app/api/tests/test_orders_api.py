"""The order pop-up routes: GET/POST .../orders/{order_id}/edit (the number, date and text), GET/POST .../upload (the
signed scan) and GET .../history (the order's activity). A refusal answers 200 with ok false and writes nothing; a
missing right is 403 (code "forbidden"); an employee or order outside the user's scope, a signed or cancelled order
(for edit) are 404."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from employees.models import Employee, HrOrder, OrderState
from employees.services import history, macs_writes, orders
from employees.tests.conftest import hire_values
from employees.views import ORDER_WARNING_KEY
from macs.models import Command

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
NOT_FOUND = "Хуудас олдсонгүй"
FORBIDDEN = "Хандах эрх байхгүй."
UPLOAD_TITLE = "Гарын үсэгтэй файл хавсаргах"
EDIT_HINT = "Дугаарыг автоматаар санал болгосон, шаардлагатай бол өөрчилнө үү."
PDF = b"%PDF-1.4\n%test\n"
TXT_REFUSED = "Зөвхөн PDF, JPG эсвэл PNG файл оруулна уу."
SIGNED_REFUSED = "Зөвхөн бүртгэсэн тушаалд гарын үсэгтэй файл хавсаргана."


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


@pytest.fixture
def hr_user(db: None) -> User:
    return _user("orders_api_hr", roles.HR)


@pytest.fixture
def accountant(db: None) -> User:
    return _user("orders_api_accountant", roles.ACCOUNTANT)


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
def hired(hr_user: User, job_values: dict[str, Any]) -> Employee:
    """A working employee hired on 2026-01-05 by an order numbered 1."""
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


@pytest.fixture
def other(hr_user: User, job_values: dict[str, Any]) -> Employee:
    """A second employee, hired by order 2, for the foreign-order checks."""
    return history.hire(
        hire_values("УБ99112244"),
        {},
        start=date(2026, 1, 6),
        job=job_values,
        salary=Decimal("2000000"),
        by=hr_user,
        order_number="2",
        order_date=date(2026, 1, 6),
    )


@pytest.fixture
def order_root(settings: Any) -> Path:
    """Where order scans are written: the temporary folder conftest sets for every test (never app/private)."""
    return Path(settings.ORDER_FILES_ROOT)


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _url(employee: Employee, order: HrOrder, tail: str) -> str:
    return f"/api/v1/employees/{employee.pk}/orders/{order.pk}/{tail}"


def _post_json(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, data=json.dumps(body), content_type="application/json")


def _hire_order(employee: Employee) -> HrOrder:
    return HrOrder.objects.get(employee=employee, is_hire=True)


def _edit_values(**extra: str) -> dict[str, str]:
    values = {"number": "31", "date": "2026-03-02", "summary": "Шилжүүлэв", "issued_by": "Б. Дорж"}
    values.update(extra)
    return values


NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}


def test_anonymous_order_routes_answer_401(hired: Employee) -> None:
    """The five concrete order routes, with no login: django_auth refuses each before the handler runs."""
    order = _hire_order(hired)
    anonymous = Client()  # a fresh client, never logged in

    responses = [
        anonymous.get(_url(hired, order, "edit")),
        _post_json(anonymous, _url(hired, order, "edit"), {"values": _edit_values()}),
        anonymous.get(_url(hired, order, "upload")),
        anonymous.post(_url(hired, order, "upload"), {}),
        anonymous.get(_url(hired, order, "history")),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.json() == NOT_LOGGED_IN
    order.refresh_from_db()
    assert order.number == "1"  # nothing changed


# --- The edit pop-up ---


def test_edit_get_suggests_number(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(number="", date=date.today())
    order.refresh_from_db()

    response = _client(hr_user).get(_url(hired, order, "edit"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == "Тушаал: Ажилд орсон"
    assert body["hint"] == EDIT_HINT and body["multipart"] is False
    fields = {field["name"]: field for field in body["fields"]}
    assert {"number", "date", "summary", "issued_by"} <= set(fields)  # unprefixed names
    assert fields["number"]["value"] == orders.suggest_number(date.today())
    assert fields["number"]["required"] is True


def test_edit_post_ok_registers(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)

    response = _post_json(_client(hr_user), _url(hired, order, "edit"), {"values": _edit_values()})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": True, "field_errors": {}, "form_errors": []}
    order.refresh_from_db()
    assert order.number == "31" and order.date == date(2026, 3, 2)


def test_edit_post_refused_field_errors_unprefixed(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)

    response = _post_json(_client(hr_user), _url(hired, order, "edit"), {"values": _edit_values(number="")})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is False
    assert "number" in body["field_errors"] and body["field_errors"]["number"]
    order.refresh_from_db()
    assert order.number == "1"  # nothing written


def test_edit_post_ok_sets_order_warning_on_macs_clash(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    Command.objects.create(employee_id=hired.pk, number="31", date=date(2026, 3, 2), order_type=1)
    client = _client(hr_user)

    response = _post_json(client, _url(hired, order, "edit"), {"values": _edit_values()})

    assert response.json()["ok"] is True
    assert "MACS-д" in client.session[ORDER_WARNING_KEY]


def test_edit_signed_order_404(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.SIGNED)
    client = _client(hr_user)

    get_response = client.get(_url(hired, order, "edit"))
    post_response = _post_json(client, _url(hired, order, "edit"), {"values": _edit_values()})

    assert get_response.status_code == 404
    assert get_response.json()["form_errors"] == [NOT_FOUND]
    assert post_response.status_code == 404
    order.refresh_from_db()
    assert order.number == "1"  # the signed order is not changed


def test_edit_without_manage_403(hired: Employee, accountant: User) -> None:
    order = _hire_order(hired)
    client = _client(accountant)

    get_response = client.get(_url(hired, order, "edit"))
    post_response = _post_json(client, _url(hired, order, "edit"), {"values": _edit_values()})

    for response in (get_response, post_response):
        assert response.status_code == 403
        assert response.json() == {"field_errors": {}, "form_errors": [FORBIDDEN], "code": "forbidden"}
    order.refresh_from_db()
    assert order.number == "1"


# --- The upload pop-up ---


def test_upload_get_is_multipart_with_file_field(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)

    response = _client(hr_user).get(_url(hired, order, "upload"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == UPLOAD_TITLE and body["multipart"] is True
    assert [field["name"] for field in body["fields"]] == ["file"]


def test_upload_post_ok_attaches(hired: Employee, hr_user: User, order_root: Path) -> None:
    order = _hire_order(hired)
    scan = SimpleUploadedFile("order.pdf", PDF, content_type="application/pdf")

    response = _client(hr_user).post(_url(hired, order, "upload"), {"file": scan})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": True, "field_errors": {}, "form_errors": []}
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED
    assert order.file.name and (order_root / order.file.name).read_bytes().startswith(b"%PDF-")


def test_upload_wrong_type_ok_false_with_message(hired: Employee, hr_user: User, order_root: Path) -> None:
    order = _hire_order(hired)
    note = SimpleUploadedFile("note.txt", b"hello text", content_type="text/plain")

    response = _client(hr_user).post(_url(hired, order, "upload"), {"file": note})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": False, "field_errors": {"file": [TXT_REFUSED]}, "form_errors": []}
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED and not order.file
    assert not any(order_root.rglob("*.txt"))


def test_upload_missing_file_ok_false(hired: Employee, hr_user: User, order_root: Path) -> None:
    order = _hire_order(hired)

    response = _client(hr_user).post(_url(hired, order, "upload"), {})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is False and list(body["field_errors"]) == ["file"]
    assert body["field_errors"]["file"]
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED and not order.file


def test_upload_to_signed_order_is_form_error(hired: Employee, hr_user: User, order_root: Path) -> None:
    """The pop-up does not check the state (GET shows it); the service refuses at the save, as a form message."""
    order = _hire_order(hired)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.SIGNED)
    scan = SimpleUploadedFile("order.pdf", PDF, content_type="application/pdf")

    response = _client(hr_user).post(_url(hired, order, "upload"), {"file": scan})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": False, "field_errors": {}, "form_errors": [SIGNED_REFUSED]}
    order.refresh_from_db()
    assert not order.file and order.state == OrderState.SIGNED


# --- The history ---


def test_history_returns_entries_newest_first(hired: Employee, hr_user: User) -> None:
    order = _hire_order(hired)
    client = _client(hr_user)
    _post_json(client, _url(hired, order, "edit"), {"values": _edit_values(number="2")})

    response = client.get(_url(hired, order, "history"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == "Тушаалын түүх: Ажилд орсон · № 2"
    entries = body["entries"]
    assert len(entries) >= 2
    assert entries[0]["by"] == "orders_api_hr"
    assert {"field": "Дугаар", "old": "1", "new": "2"} in entries[0]["changes"]
    assert entries[0]["at"] >= entries[-1]["at"]
    assert len(entries[0]["at"]) == 16  # "Y-m-d H:i"


def test_history_visible_to_non_manager_who_sees_employee(hired: Employee, accountant: User) -> None:
    order = _hire_order(hired)

    response = _client(accountant).get(_url(hired, order, "history"))

    assert response.status_code == 200, response.content
    assert response.json()["entries"]


def test_order_of_other_employee_404(hired: Employee, other: Employee, hr_user: User) -> None:
    foreign = _hire_order(hired)  # belongs to `hired`, asked through `other`
    client = _client(hr_user)

    for tail in ("edit", "upload", "history"):
        response = client.get(f"/api/v1/employees/{other.pk}/orders/{foreign.pk}/{tail}")
        assert response.status_code == 404, tail
        assert response.json()["form_errors"] == [NOT_FOUND]


def test_employee_outside_scope_404(hired: Employee) -> None:
    order = _hire_order(hired)
    outsider = _user("orders_api_outsider", roles.EMPLOYEE)  # sees no employee but its own

    response = _client(outsider).get(_url(hired, order, "history"))

    assert response.status_code == 404
    assert response.json()["form_errors"] == [NOT_FOUND]
