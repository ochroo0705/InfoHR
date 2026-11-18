"""The salary set and correction routes and the job correction route: GET .../form (the pop-up) and POST (the save).
A scheduled row is 403, another employee's row is 404, and each route needs its own right (salary or manage)."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from employees.models import ActivityEntry, ActivityKind, Employee, Event, EventType, JobRecord, SalaryRecord
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
FUTURE = date(2030, 1, 1)


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


@pytest.fixture
def admin(db: None) -> User:
    return _user("employee_correct_admin", roles.ADMIN)


@pytest.fixture
def hr(db: None) -> User:
    return _user("employee_correct_hr", roles.HR)


@pytest.fixture
def accountant(db: None) -> User:
    return _user("employee_correct_accountant", roles.ACCOUNTANT)


def _job_values() -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def _hire(admin: User, register_no: str, *, salary: Decimal | None, order_number: str) -> Employee:
    return history.hire(
        hire_values(register_no),
        {},
        start=date(2026, 1, 5),
        job=_job_values(),
        salary=salary,
        by=admin,
        order_number=order_number,
        order_date=date(2026, 1, 5),
    )


@pytest.fixture
def paid(admin: User) -> Employee:
    """A working employee hired on 2026-01-05 at 2,500,000 (one salary row, one job row)."""
    return _hire(admin, "УБ99112233", salary=Decimal("2500000"), order_number="1")


@pytest.fixture
def unpaid(admin: User) -> Employee:
    """A working employee hired without a salary: the set-salary route applies."""
    return _hire(admin, "УБ99112235", salary=None, order_number="3")


@pytest.fixture
def other(admin: User, paid: Employee) -> Employee:
    return _hire(admin, "УБ99112234", salary=Decimal("1800000"), order_number="2")


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _base(employee: Employee) -> str:
    return f"/api/v1/employees/{employee.pk}"


def _form(client: Client, url: str) -> Any:
    response = client.get(url)
    assert response.status_code == 200, response.content
    return response.json()


def _values(body: dict[str, Any]) -> dict[str, str]:
    """What the browser would post from the pop-up: each field's value, then the hidden values."""
    fields = {
        f["name"]: ("on" if f["checked"] else "") if f["kind"] == "checkbox" else f["value"] for f in body["fields"]
    }
    return {**fields, **body["hidden"]}


def _post(client: Client, url: str, values: dict[str, str]) -> Any:
    return client.post(url, data=json.dumps({"values": values}), content_type="application/json")


def _salary_url(employee: Employee, record: SalaryRecord) -> str:
    return f"{_base(employee)}/salary/{record.pk}/correct"


def _job_url(employee: Employee, record: JobRecord) -> str:
    return f"{_base(employee)}/job/{record.pk}/correct"


def test_set_salary_writes_the_first_record_and_an_activity_entry(admin: User, unpaid: Employee) -> None:
    client = _client(admin)
    url = f"{_base(unpaid)}/salary/set"
    body = _form(client, f"{url}/form")
    assert body["title"] == "Цалин тогтоох"
    assert SalaryRecord.objects.filter(employee=unpaid).count() == 0

    response = _post(client, url, {"effective": "2026-01-05", "amount": "2,500,000"})

    assert response.status_code == 200, response.content
    assert response.json()["ok"] is True
    assert SalaryRecord.objects.filter(employee=unpaid).count() == 1
    assert SalaryRecord.objects.get(employee=unpaid).base_salary == Decimal("2500000")
    entry = ActivityEntry.objects.filter(employee=unpaid, kind=ActivityKind.HISTORY).latest("pk")
    assert "цалин өөрчлөгдөв" in entry.message


def test_second_set_salary_is_403(admin: User, paid: Employee) -> None:
    client = _client(admin)
    response = client.get(f"{_base(paid)}/salary/set/form")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    response = _post(client, f"{_base(paid)}/salary/set", {"effective": "2026-01-05", "amount": "1"})
    assert response.status_code == 403
    assert SalaryRecord.objects.filter(employee=paid).count() == 1


def test_correct_salary_with_a_reason_changes_the_amount(admin: User, paid: Employee) -> None:
    client = _client(admin)
    record = SalaryRecord.objects.get(employee=paid)
    body = _form(client, f"{_salary_url(paid, record)}/form")
    assert body["title"] == "Цалин засварлах"
    assert body["can_delete"] is False
    assert body["empty_lists"] == []

    response = _post(client, _salary_url(paid, record), {"amount": "2600000", "reason": "Алдаа засав"})

    assert response.status_code == 200, response.content
    assert response.json()["ok"] is True
    record.refresh_from_db()
    assert record.base_salary == Decimal("2600000")


def test_blank_reason_gives_a_field_error(admin: User, paid: Employee) -> None:
    client = _client(admin)
    record = SalaryRecord.objects.get(employee=paid)
    response = _post(client, _salary_url(paid, record), {"amount": "2600000", "reason": "  "})
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False
    assert "reason" in body["field_errors"]
    record.refresh_from_db()
    assert record.base_salary == Decimal("2500000")


def test_money_kind_is_on_the_salary_amount(admin: User, paid: Employee) -> None:
    client = _client(admin)
    record = SalaryRecord.objects.get(employee=paid)
    body = _form(client, f"{_salary_url(paid, record)}/form")
    fields = {f["name"]: f for f in body["fields"]}
    assert fields["amount"]["kind"] == "money"
    assert fields["amount"]["value"] == "2500000"  # a whole amount without the ".00" tail
    assert fields["reason"]["kind"] == "textarea"


def test_fractional_salary_keeps_its_fraction_in_the_pop_up(admin: User, paid: Employee) -> None:
    client = _client(admin)
    record = SalaryRecord.objects.get(employee=paid)
    SalaryRecord.objects.filter(pk=record.pk).update(base_salary=Decimal("2500000.50"))
    body = _form(client, f"{_salary_url(paid, record)}/form")
    fields = {f["name"]: f for f in body["fields"]}
    assert fields["amount"]["value"] == "2500000.50"


@pytest.mark.parametrize("amount", ["2500000", "2500000.00"])
def test_whole_amount_is_accepted_with_or_without_the_tail(admin: User, paid: Employee, amount: str) -> None:
    client = _client(admin)
    record = SalaryRecord.objects.get(employee=paid)
    SalaryRecord.objects.filter(pk=record.pk).update(base_salary=Decimal("2000000"))
    response = _post(client, _salary_url(paid, record), {"amount": amount, "reason": "Засав"})
    assert response.status_code == 200, response.content
    assert response.json()["ok"] is True
    record.refresh_from_db()
    assert record.base_salary == Decimal("2500000")


def test_money_kind_is_on_the_set_salary_amount(admin: User, unpaid: Employee) -> None:
    body = _form(_client(admin), f"{_base(unpaid)}/salary/set/form")
    fields = {f["name"]: f for f in body["fields"]}
    assert fields["amount"]["kind"] == "money"
    assert fields["effective"]["value"] == "2026-01-05"


def test_correct_job_changes_a_field(admin: User, paid: Employee) -> None:
    client = _client(admin)
    record = JobRecord.objects.get(employee=paid)
    body = _form(client, f"{_job_url(paid, record)}/form")
    assert body["title"] == "Ажлын түүх засварлах"

    values = _values(body)
    values["contract_no"] = "Г-15"
    values["reason"] = "Буруу бичсэн"
    response = _post(client, _job_url(paid, record), values)

    assert response.status_code == 200, response.content
    assert response.json()["ok"] is True
    record.refresh_from_db()
    assert record.contract_no == "Г-15"


def test_scheduled_salary_row_is_403_on_form_and_post(admin: User, paid: Employee) -> None:
    event = Event.objects.create(employee=paid, type=EventType.SALARY_CHANGE, effective=FUTURE, created_by=admin)
    history.change_salary(
        paid,
        effective=FUTURE,
        amount=Decimal("3000000"),
        change_type=EventType.SALARY_CHANGE.change_type,
        note="",
        by=admin,
        event=event,
    )
    scheduled = SalaryRecord.objects.get(event=event)
    client = _client(admin)
    assert client.get(f"{_salary_url(paid, scheduled)}/form").status_code == 403
    response = _post(client, _salary_url(paid, scheduled), {"amount": "2600000", "reason": "x"})
    assert response.status_code == 403
    scheduled.refresh_from_db()
    assert scheduled.base_salary == Decimal("3000000")


def test_scheduled_job_row_is_403_on_form_and_post(admin: User, paid: Employee) -> None:
    event = Event.objects.create(employee=paid, type=EventType.CONTRACT, effective=FUTURE, created_by=admin)
    history.change_job(
        paid,
        effective=FUTURE,
        changes={"contract_no": "Г-9"},
        change_type=EventType.CONTRACT.change_type,
        note="",
        by=admin,
        event=event,
    )
    scheduled = JobRecord.objects.get(event=event)
    client = _client(admin)
    assert client.get(f"{_job_url(paid, scheduled)}/form").status_code == 403
    assert _post(client, _job_url(paid, scheduled), {"contract_no": "Г-10", "reason": "x"}).status_code == 403


def test_hr_without_the_salary_right_is_403_for_salary_routes(hr: User, paid: Employee) -> None:
    client = _client(hr)
    record = SalaryRecord.objects.get(employee=paid)
    assert client.get(f"{_salary_url(paid, record)}/form").status_code == 403
    assert _post(client, _salary_url(paid, record), {"amount": "1", "reason": "x"}).status_code == 403
    assert client.get(f"{_base(paid)}/salary/set/form").status_code == 403


def test_accountant_without_the_manage_right_is_403_for_a_job_correction(accountant: User, paid: Employee) -> None:
    client = _client(accountant)
    record = JobRecord.objects.get(employee=paid)
    assert client.get(f"{_job_url(paid, record)}/form").status_code == 403
    assert _post(client, _job_url(paid, record), {"contract_no": "Г-1", "reason": "x"}).status_code == 403
    assert JobRecord.objects.get(pk=record.pk).contract_no != "Г-1"


def test_accountant_with_the_salary_right_corrects_the_salary(accountant: User, paid: Employee) -> None:
    client = _client(accountant)
    record = SalaryRecord.objects.get(employee=paid)
    response = _post(client, _salary_url(paid, record), {"amount": "2700000", "reason": "Засав"})
    assert response.status_code == 200, response.content
    assert response.json()["ok"] is True


def test_record_id_of_another_employee_is_404(admin: User, paid: Employee, other: Employee) -> None:
    client = _client(admin)
    other_salary = SalaryRecord.objects.get(employee=other)
    other_job = JobRecord.objects.get(employee=other)
    assert client.get(f"{_salary_url(paid, other_salary)}/form").status_code == 404
    assert _post(client, _salary_url(paid, other_salary), {"amount": "1", "reason": "x"}).status_code == 404
    assert client.get(f"{_job_url(paid, other_job)}/form").status_code == 404
    assert _post(client, _job_url(paid, other_job), {"contract_no": "x", "reason": "x"}).status_code == 404


def test_unknown_record_id_is_404(admin: User, paid: Employee) -> None:
    client = _client(admin)
    assert client.get(f"{_base(paid)}/salary/999999/correct/form").status_code == 404
    assert client.get(f"{_base(paid)}/job/999999/correct/form").status_code == 404
