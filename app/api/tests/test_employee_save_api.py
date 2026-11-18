"""GET /api/v1/employees/{pk}/page-form and POST /api/v1/employees/{pk}/save: the employee page's form and save."""

import io
import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, link_login
from macs.models import Bank, Branch, EmployeePhoto, InsuredCategory
from PIL import Image

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("employee_save_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    return user


@pytest.fixture
def hired(hr_user: User) -> Employee:
    """A working employee hired on 2026-01-05 (work_phone 99112233 from hire_values)."""
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


def _client(user: User | None = None, *, enforce_csrf: bool = False) -> Client:
    client = Client(enforce_csrf_checks=enforce_csrf)
    if user is not None:
        client.force_login(user)
    return client


def _page(client: Client, pk: int) -> dict[str, Any]:
    response = client.get(f"/api/v1/employees/{pk}/page-form")
    assert response.status_code == 200, response.content
    return response.json()


def _values(page: dict[str, Any]) -> dict[str, str]:
    """The values the React page holds: every field's stored value and both snapshots, as strings."""
    values = {field["name"]: field["value"] for field in page["fields"]}
    values["loaded"] = page["loaded"]
    values["si-loaded"] = page["si_loaded"]
    return values


def _save(client: Client, pk: int, values: dict[str, str], **extra: Any) -> Any:
    return client.post(f"/api/v1/employees/{pk}/save", {"values_json": json.dumps(values), **extra})


def _png(size: tuple[int, int] = (40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "blue").save(buffer, "PNG")
    return buffer.getvalue()


def test_hr_gets_work_and_branch_fields_with_a_loaded_snapshot(hr_user: User, hired: Employee) -> None:
    Branch.objects.create(name="Төв салбар")
    page = _page(_client(hr_user), hired.pk)
    by_name = {field["name"]: field for field in page["fields"]}

    assert "work_phone" in by_name
    assert by_name["work_phone"]["value"] == "99112233"
    assert by_name["branch"]["kind"] == "select"
    assert by_name["branch"]["choices"], "the branch select must list its choices"
    assert page["loaded"] != ""
    assert json.loads(page["loaded"])["work_phone"] == "99112233"
    assert not any(name in by_name for name in ("photo", "photo_clear"))


def test_accountant_gets_only_the_salary_fields(hired: Employee) -> None:
    accountant = User.objects.create_user("employee_save_accountant", password=PASSWORD)
    accountant.groups.add(Group.objects.get_or_create(name=roles.ACCOUNTANT)[0])
    page = _page(_client(accountant), hired.pk)

    assert page["fields"], "the salary form has fields"
    assert all(field["name"].startswith("si-") for field in page["fields"])
    assert page["loaded"] == ""
    assert page["si_loaded"] != ""


def test_viewer_without_rights_is_403(hired: Employee) -> None:
    viewer = User.objects.create_user("employee_save_plain", password=PASSWORD)
    link_login(hired, viewer)  # the own record is visible; no manage or salary right is granted
    response = _client(viewer).get(f"/api/v1/employees/{hired.pk}/page-form")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_unknown_pk_is_404(hr_user: User) -> None:
    assert _client(hr_user).get("/api/v1/employees/999999/page-form").status_code == 404


def test_anonymous_is_401(hired: Employee) -> None:
    assert _client().get(f"/api/v1/employees/{hired.pk}/page-form").status_code == 401


def test_valid_save_writes_the_change(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    values = _values(_page(client, hired.pk))
    values["work_phone"] = "88887777"

    response = _save(client, hired.pk, values)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert Employee.objects.get(pk=hired.pk).work_phone == "88887777"


def test_invalid_save_is_200_with_field_errors(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    values = _values(_page(client, hired.pk))
    values["work_phone"] = "1" * 20  # longer than the 14 characters the column takes

    response = _save(client, hired.pk, values)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "work_phone" in body["field_errors"]
    assert Employee.objects.get(pk=hired.pk).work_phone == "99112233"


def test_clash_returns_conflicts_and_fresh_loaded_and_resolve_mine_saves(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    values = _values(_page(client, hired.pk))
    values["work_phone"] = "11111111"
    Employee.objects.filter(pk=hired.pk).update(work_phone="22222222")  # MACS wrote the field meanwhile

    clash = _save(client, hired.pk, values)

    body = clash.json()
    assert body["ok"] is False
    assert "work_phone" in body["conflicts"]
    assert json.loads(body["loaded"])["work_phone"] == "22222222"
    assert Employee.objects.get(pk=hired.pk).work_phone == "22222222"

    values["resolve-work_phone"] = "mine"
    values["loaded"] = body["loaded"]
    saved = _save(client, hired.pk, values)

    assert saved.json()["ok"] is True
    assert Employee.objects.get(pk=hired.pk).work_phone == "11111111"


def test_non_image_photo_is_a_field_error(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    values = _values(_page(client, hired.pk))
    not_image = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")

    body = _save(client, hired.pk, values, photo=not_image).json()

    assert body["ok"] is False
    assert "photo" in body["field_errors"]


def test_real_png_sets_the_photo_and_photo_clear_removes_it(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    values = _values(_page(client, hired.pk))
    picture = SimpleUploadedFile("face.png", _png(), content_type="image/png")

    assert _save(client, hired.pk, values, photo=picture).json()["ok"] is True
    assert EmployeePhoto.objects.filter(employee=hired).exists()

    values = _values(_page(client, hired.pk))
    assert _save(client, hired.pk, values, photo_clear="true").json()["ok"] is True
    assert not EmployeePhoto.objects.filter(employee=hired).exists()


def test_csrf_less_post_is_403_csrf_failed(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user, enforce_csrf=True)
    values = {"work_phone": "11111111", "loaded": "", "si-loaded": ""}

    response = _save(client, hired.pk, values)

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


def _accountant(hired: Employee, name: str = "employee_save_accountant_fix") -> User:
    accountant = User.objects.create_user(name, password=PASSWORD)
    accountant.groups.add(Group.objects.get_or_create(name=roles.ACCOUNTANT)[0])
    return accountant


def test_accountant_post_writes_salary_fields_and_ignores_work_fields(hired: Employee) -> None:
    accountant = _accountant(hired)
    client = _client(accountant)
    values = _values(_page(client, hired.pk))
    values["si-account_no"] = "ACC-555"
    values["work_phone"] = "77776666"  # not on the accountant's page: must not be written

    body = _save(client, hired.pk, values).json()

    assert body["ok"] is True
    stored = Employee.objects.get(pk=hired.pk)
    assert stored.account_no == "ACC-555"
    assert stored.work_phone == "99112233"


def test_post_without_edit_rights_is_403_forbidden(hired: Employee) -> None:
    viewer = User.objects.create_user("employee_save_viewer_fix", password=PASSWORD)
    link_login(hired, viewer)  # sees the own record, has neither manage nor salary right
    response = _save(_client(viewer), hired.pk, {"work_phone": "11111111", "loaded": "", "si-loaded": ""})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert Employee.objects.get(pk=hired.pk).work_phone == "99112233"


def test_salary_clash_returns_si_conflict_and_fresh_si_loaded(hired: Employee) -> None:
    accountant = _accountant(hired, "employee_save_accountant_clash")
    client = _client(accountant)
    values = _values(_page(client, hired.pk))  # takes si-loaded before MACS changes the salary row
    Employee.objects.filter(pk=hired.pk).update(account_no="STORED-2")  # MACS wrote the field meanwhile
    values["si-account_no"] = "MINE-1"

    body = _save(client, hired.pk, values).json()

    assert body["ok"] is False
    assert "si-account_no" in body["conflicts"]
    assert json.loads(body["si_loaded"])["account_no"] == "STORED-2"
    assert Employee.objects.get(pk=hired.pk).account_no == "STORED-2"


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", json.dumps({"work_phone": 5})])
def test_malformed_values_json_is_400_with_form_errors(hr_user: User, hired: Employee, raw: str) -> None:
    response = _client(hr_user).post(f"/api/v1/employees/{hired.pk}/save", {"values_json": raw})

    assert response.status_code == 400
    assert response.json()["form_errors"]


def test_page_save_without_loaded_is_400_and_writes_nothing(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    values = _values(_page(client, hired.pk))
    del values["loaded"]  # the snapshot the page showed is missing
    values["work_phone"] = "66665555"

    response = _save(client, hired.pk, values)

    assert response.status_code == 400
    assert response.json()["form_errors"] == ["Хуудсыг дахин ачаалж, дахин оролдоно уу."]
    assert Employee.objects.get(pk=hired.pk).work_phone == "99112233"


def test_accountant_save_without_si_loaded_is_400_and_writes_nothing(hired: Employee) -> None:
    accountant = _accountant(hired, "employee_save_accountant_no_snapshot")
    client = _client(accountant)
    values = _values(_page(client, hired.pk))
    del values["si-loaded"]  # the salary snapshot is missing; an accountant has no `loaded` to send
    values["si-account_no"] = "ACC-777"

    response = _save(client, hired.pk, values)

    assert response.status_code == 400
    assert response.json()["form_errors"] == ["Хуудсыг дахин ачаалж, дахин оролдоно уу."]
    assert Employee.objects.get(pk=hired.pk).account_no != "ACC-777"


def _set_salary_row(pk: int) -> None:
    """Stored salary and insurance values that a one-field post must leave alone."""
    bank = Bank.objects.create(name="Хаан банк")
    category = InsuredCategory.objects.create(name="Ажилтан")
    Employee.objects.filter(pk=pk).update(
        account_no="OLD-1",
        bank=bank,
        social_insurance_no="SOC-1",
        health_insurance_no="HEA-1",
        taxpayer_no="TAX-1",
        insured_category=category,
        has_disability=True,
    )


def _salary_state(pk: int) -> dict[str, Any]:
    stored = Employee.objects.get(pk=pk)
    return {
        "account_no": stored.account_no,
        "bank": stored.bank_id,
        "social_insurance_no": stored.social_insurance_no,
        "health_insurance_no": stored.health_insurance_no,
        "taxpayer_no": stored.taxpayer_no,
        "insured_category": stored.insured_category_id,
        "has_disability": bool(stored.has_disability),
    }


def test_accountant_posting_one_salary_field_changes_only_that_field(hired: Employee) -> None:
    accountant = _accountant(hired, "employee_save_accountant_one")
    _set_salary_row(hired.pk)
    before = _salary_state(hired.pk)
    client = _client(accountant)
    page = _page(client, hired.pk)

    body = _save(client, hired.pk, {"si-account_no": "NEW-9", "si-loaded": page["si_loaded"]}).json()

    assert body["ok"] is True
    after = _salary_state(hired.pk)
    assert after["account_no"] == "NEW-9"
    assert {k: v for k, v in after.items() if k != "account_no"} == {
        k: v for k, v in before.items() if k != "account_no"
    }


def test_user_with_both_rights_posting_one_salary_field_changes_only_that_field(hired: Employee) -> None:
    both = User.objects.create_user("employee_save_admin_one", password=PASSWORD)
    both.groups.add(Group.objects.get_or_create(name=roles.ADMIN)[0])
    _set_salary_row(hired.pk)
    before = _salary_state(hired.pk)
    client = _client(both)
    page = _page(client, hired.pk)

    # A user with the manage right must also post the header form's `loaded` (the save refuses a missing one).
    values = {"si-account_no": "NEW-8", "si-loaded": page["si_loaded"], "loaded": page["loaded"]}
    body = _save(client, hired.pk, values).json()

    assert body["ok"] is True
    after = _salary_state(hired.pk)
    assert after["account_no"] == "NEW-8"
    assert {k: v for k, v in after.items() if k != "account_no"} == {
        k: v for k, v in before.items() if k != "account_no"
    }


def test_salary_clash_on_a_posted_field_still_conflicts(hired: Employee) -> None:
    accountant = _accountant(hired, "employee_save_accountant_one_clash")
    _set_salary_row(hired.pk)
    client = _client(accountant)
    page = _page(client, hired.pk)
    Employee.objects.filter(pk=hired.pk).update(account_no="STORED-3")  # MACS wrote it after si-loaded
    before = _salary_state(hired.pk)

    body = _save(client, hired.pk, {"si-account_no": "MINE-3", "si-loaded": page["si_loaded"]}).json()

    assert body["ok"] is False
    assert "si-account_no" in body["conflicts"]
    assert json.loads(body["si_loaded"])["account_no"] == "STORED-3"
    assert _salary_state(hired.pk) == before


def test_unchecked_disability_posted_as_empty_clears_a_stored_true(hired: Employee) -> None:
    accountant = _accountant(hired, "employee_save_accountant_disability_off")
    _set_salary_row(hired.pk)
    client = _client(accountant)
    page = _page(client, hired.pk)

    body = _save(client, hired.pk, {"si-has_disability": "", "si-loaded": page["si_loaded"]}).json()

    assert body["ok"] is True
    assert _salary_state(hired.pk)["has_disability"] is False


def test_disability_omitted_from_the_post_stays_true(hired: Employee) -> None:
    accountant = _accountant(hired, "employee_save_accountant_disability_kept")
    _set_salary_row(hired.pk)
    client = _client(accountant)
    page = _page(client, hired.pk)

    body = _save(client, hired.pk, {"si-account_no": "KEEP-1", "si-loaded": page["si_loaded"]}).json()

    assert body["ok"] is True
    assert _salary_state(hired.pk)["has_disability"] is True
