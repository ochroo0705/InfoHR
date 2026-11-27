"""The editor routes of a report cell (api/reports_edit.py): GET cell/editor and POST cell, GET row-cell/editor and
POST row-cell, GET correct/editor and POST correct. The rules live in reports.services.cell_editors; these tests pin the
routes: their rights (401 without a login, 404 for an unknown field, kind or key, an unseen person or row, 403 without
the right to change the field or correct the cell), the editor's shape, a clash giving the stored value in a fresh
editor, a blocked correction writing nothing, the no-store header, and the path order (the editor routes are not read
as report keys).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import CompanySettings, Employee, JobRecord
from employees.services import history, macs_writes, personal_writes, report_corrections
from employees.tests.conftest import actor, hire_values, named  # noqa: F401 (fixtures the hired fixture needs)
from macs.models import ContactRow, ContactType, FamilyRelation, FamilyRow

from api.popups import FORBIDDEN, NOT_FOUND
from api.tests.logs_support import NOT_LOGGED_IN, job_values, scoped  # noqa: F401 (fixtures)

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
BASE = "/api/v1/reports"
CELL_EDITOR = f"{BASE}/cell/editor"
CELL = f"{BASE}/cell"
ROW_EDITOR = f"{BASE}/row-cell/editor"
ROW = f"{BASE}/row-cell"
CORRECT_EDITOR = f"{BASE}/correct/editor"
CORRECT = f"{BASE}/correct"
NOT_FOUND_BODY = {"field_errors": {}, "form_errors": [NOT_FOUND]}
FORBIDDEN_BODY = {"field_errors": {}, "form_errors": [FORBIDDEN], "code": "forbidden"}
NOTE = "Анхны утгыг засна. Шилжүүлэх, цалин нэмэх бол тушаалаар."
CLASH = "Өөр хэрэглэгч энэ утгыг өөрчилсөн байна. Хуудсаа шинэчилнэ үү."
EDITOR_KEYS = {
    "kind",
    "name",
    "value",
    "label",
    "choices",
    "required",
    "maxlength",
    "loaded",
    "hidden",
    "reason",
    "reason_text",
    "old",
    "note",
    "blocked",
    "error",
}


@pytest.fixture
def hired(actor: User, job_values: dict[str, Any]) -> Employee:  # noqa: F811 (the imported fixtures)
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


@pytest.fixture
def hr() -> User:
    user = User.objects.create_user("report_edit_hr", password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    return User.objects.get(pk=user.pk)  # fresh permission cache


@pytest.fixture
def accountant() -> User:
    user = User.objects.create_user("report_edit_accountant", password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name="Accountant"))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _as(user: User | None) -> Client:
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def _post(client: Client, path: str, body: dict[str, Any]) -> Any:
    return client.post(path, data=json.dumps(body), content_type="application/json")


def _job(employee: Employee) -> JobRecord:
    record = history.job_on(employee, timezone.localdate())
    assert record is not None
    return record


def _child(employee: Employee, given: str = "Бат") -> FamilyRow:
    relation = FamilyRelation.objects.create(name=f"Хүү {given}", fm_type="son")
    return FamilyRow.objects.create(employee=employee, relation=relation, given_name=given, birth_date=date(2015, 1, 2))


def _contact(employee: Employee, value: str = "99112233") -> ContactRow:
    return ContactRow.objects.create(
        employee=employee, contact_type=named(ContactType, "Утас"), value=value, name="Эх", relative="Ээж"
    )


# --- GET cell/editor and POST cell -----------------------------------------------------------------------------------


def test_cell_editor_requires_login(hired: Employee) -> None:
    response = _as(None).get(CELL_EDITOR, {"person": hired.pk, "field": "private_phone"})
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_cell_editor_reaches_the_editor_not_a_report_key(hr: User, hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")
    response = _as(hr).get(CELL_EDITOR, {"person": hired.pk, "field": "private_phone"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == EDITOR_KEYS
    assert body["kind"] == "text"
    assert body["name"] == "private_phone"
    assert body["value"] == "99001122"
    assert body["loaded"] != ""
    assert response["Cache-Control"] == "no-store"


def test_cell_editor_unknown_field_is_404(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CELL_EDITOR, {"person": hired.pk, "field": "salary"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY


def test_cell_editor_salary_field_without_the_salary_right_is_403(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CELL_EDITOR, {"person": hired.pk, "field": "account_no"})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_BODY


def test_cell_editor_unseen_person_is_404(hr: User) -> None:
    response = _as(hr).get(CELL_EDITOR, {"person": 999_999, "field": "private_phone"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY


def test_cell_editor_hidden_person_is_404(scoped: tuple[Employee, Employee, User]) -> None:  # noqa: F811
    _inside, outside, limited = scoped
    response = _as(limited).get(CELL_EDITOR, {"person": outside.pk, "field": "private_phone"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY


def test_cell_post_saves_and_answers_the_value(hr: User, hired: Employee) -> None:
    loaded = _as(hr).get(CELL_EDITOR, {"person": hired.pk, "field": "private_phone"}).json()["loaded"]
    response = _post(
        _as(hr), CELL, {"person": hired.pk, "field": "private_phone", "value": "99887766", "loaded": loaded}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "text": "99887766", "error": "", "editor": None}
    assert response["Cache-Control"] == "no-store"
    hired.refresh_from_db()
    assert hired.private_phone == "99887766"


def test_cell_post_clash_shows_the_stored_value_and_a_retry_succeeds(hr: User, hired: Employee) -> None:
    client = _as(hr)
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")
    loaded = client.get(CELL_EDITOR, {"person": hired.pk, "field": "private_phone"}).json()["loaded"]
    Employee.objects.filter(pk=hired.pk).update(private_phone="99002233")  # another user changed it meanwhile
    response = _post(
        client, CELL, {"person": hired.pk, "field": "private_phone", "value": "99887766", "loaded": loaded}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False
    assert body["error"] == CLASH
    assert body["editor"]["value"] == "99002233"
    assert body["editor"]["loaded"] != loaded
    retry = _post(
        client,
        CELL,
        {"person": hired.pk, "field": "private_phone", "value": "99887766", "loaded": body["editor"]["loaded"]},
    )
    assert retry.json()["ok"] is True
    hired.refresh_from_db()
    assert hired.private_phone == "99887766"


def test_cell_post_forged_field_is_404_and_writes_nothing(hr: User, hired: Employee) -> None:
    before = hired.work_phone
    response = _post(_as(hr), CELL, {"person": hired.pk, "field": "salary", "value": "1", "loaded": ""})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY
    hired.refresh_from_db()
    assert hired.work_phone == before


def test_cell_post_salary_field_without_the_right_is_403_and_writes_nothing(hr: User, hired: Employee) -> None:
    response = _post(_as(hr), CELL, {"person": hired.pk, "field": "account_no", "value": "999", "loaded": ""})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_BODY
    hired.refresh_from_db()
    assert hired.account_no != "999"


def test_cell_post_salary_field_with_the_right_saves(accountant: User, hired: Employee) -> None:
    client = _as(accountant)
    loaded = client.get(CELL_EDITOR, {"person": hired.pk, "field": "account_no"}).json()["loaded"]
    response = _post(client, CELL, {"person": hired.pk, "field": "account_no", "value": "5012345678", "loaded": loaded})
    assert response.json()["ok"] is True
    hired.refresh_from_db()
    assert hired.account_no == "5012345678"


# --- GET row-cell/editor and POST row-cell ---------------------------------------------------------------------------


def test_row_editor_returns_the_field_and_the_row_values_as_hidden(hr: User, hired: Employee) -> None:
    child = _child(hired)
    response = _as(hr).get(ROW_EDITOR, {"person": hired.pk, "kind": "family", "key": child.pk, "field": "given_name"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == EDITOR_KEYS
    assert body["name"] == "given_name"
    assert body["value"] == "Бат"
    assert body["hidden"]["birth_date"] == "2015-01-02"
    assert any(name.startswith("loaded_") for name in body["hidden"])
    assert "given_name" not in body["hidden"]
    assert response["Cache-Control"] == "no-store"


def test_row_editor_requires_login(hired: Employee) -> None:
    child = _child(hired)
    response = _as(None).get(ROW_EDITOR, {"person": hired.pk, "kind": "family", "key": child.pk, "field": "given_name"})
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_row_post_saves_the_visible_field_with_the_hidden_values(hr: User, hired: Employee) -> None:
    client = _as(hr)
    child = _child(hired)
    hidden = client.get(ROW_EDITOR, {"person": hired.pk, "kind": "family", "key": child.pk, "field": "given_name"})
    values = {**hidden.json()["hidden"], "given_name": "Болд"}
    response = _post(
        client, ROW, {"person": hired.pk, "kind": "family", "key": child.pk, "field": "given_name", "values": values}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "text": "Болд", "error": "", "editor": None}
    assert response["Cache-Control"] == "no-store"
    child.refresh_from_db()
    assert child.given_name == "Болд"


def test_row_post_changed_meanwhile_is_a_fresh_editor(hr: User, hired: Employee) -> None:
    client = _as(hr)
    child = _child(hired)
    hidden = client.get(ROW_EDITOR, {"person": hired.pk, "kind": "family", "key": child.pk, "field": "given_name"})
    FamilyRow.objects.filter(pk=child.pk).update(given_name="Өөр")  # changed after the editor opened
    values = {**hidden.json()["hidden"], "given_name": "Болд"}
    response = _post(
        client, ROW, {"person": hired.pk, "kind": "family", "key": child.pk, "field": "given_name", "values": values}
    )
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == personal_writes.STALE  # the PersonalConflict text the row service returns
    assert body["editor"]["value"] == "Өөр"
    assert body["editor"]["error"] == personal_writes.STALE
    child.refresh_from_db()
    assert child.given_name == "Өөр"


def test_row_of_another_employee_is_404_and_writes_nothing(
    hr: User,
    hired: Employee,
    actor: User,  # noqa: F811 (the imported fixture)
    job_values: dict[str, Any],  # noqa: F811 (the imported fixture)
) -> None:
    other = history.hire(
        hire_values(register_no="УБ99112244"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
        order_number="2",
        order_date=date(2026, 1, 5),
    )
    foreign_child = _child(other, given="Сарнай")
    client = _as(hr)
    response = client.get(
        ROW_EDITOR, {"person": hired.pk, "kind": "family", "key": foreign_child.pk, "field": "given_name"}
    )
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY
    values = {"birth_date": "2015-01-02", "given_name": "x"}
    response = _post(
        client,
        ROW,
        {"person": hired.pk, "kind": "family", "key": foreign_child.pk, "field": "given_name", "values": values},
    )
    assert response.status_code == 404
    foreign_child.refresh_from_db()
    assert foreign_child.given_name == "Сарнай"


def test_row_unknown_kind_or_field_is_404(hr: User, hired: Employee) -> None:
    child = _child(hired)
    client = _as(hr)
    unknown_field = client.get(ROW_EDITOR, {"person": hired.pk, "kind": "family", "key": child.pk, "field": "surname"})
    assert unknown_field.status_code == 404
    unknown_kind = client.get(ROW_EDITOR, {"person": hired.pk, "kind": "unknown", "key": child.pk, "field": "value"})
    assert unknown_kind.status_code == 404
    assert unknown_kind.json() == NOT_FOUND_BODY


def test_contact_row_value_is_saved(hr: User, hired: Employee) -> None:
    client = _as(hr)
    contact = _contact(hired)
    hidden = client.get(ROW_EDITOR, {"person": hired.pk, "kind": "contact", "key": contact.pk, "field": "value"})
    values = {**hidden.json()["hidden"], "value": "99887766"}
    response = _post(
        client, ROW, {"person": hired.pk, "kind": "contact", "key": contact.pk, "field": "value", "values": values}
    )
    assert response.json() == {"ok": True, "text": "99887766", "error": "", "editor": None}


# --- GET correct/editor and POST correct -----------------------------------------------------------------------------


def test_correct_editor_for_a_job_field(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CORRECT_EDITOR, {"person": hired.pk, "key": "department", "record": _job(hired).pk})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == EDITOR_KEYS
    assert body["kind"] == "choice"
    assert body["reason"] is True
    assert body["note"] == NOTE
    assert body["old"] == "Санхүү"
    assert response["Cache-Control"] == "no-store"


def test_correct_editor_for_the_salary_needs_no_record(accountant: User, hired: Employee) -> None:
    response = _as(accountant).get(CORRECT_EDITOR, {"person": hired.pk, "key": "salary"})
    assert response.status_code == 200
    assert response.json()["kind"] == "number"


def test_correct_editor_requires_login(hired: Employee) -> None:
    response = _as(None).get(CORRECT_EDITOR, {"person": hired.pk, "key": "salary"})
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_correct_editor_setting_off_is_403(hr: User, hired: Employee) -> None:
    settings = CompanySettings.get()
    settings.report_corrections = False
    settings.save()
    response = _as(hr).get(CORRECT_EDITOR, {"person": hired.pk, "key": "department", "record": _job(hired).pk})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_BODY


def test_correct_editor_job_key_without_a_record_is_404(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CORRECT_EDITOR, {"person": hired.pk, "key": "department"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY


def test_correct_editor_unknown_key_is_404(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CORRECT_EDITOR, {"person": hired.pk, "key": "register_no", "record": _job(hired).pk})
    assert response.status_code == 404


def test_correct_editor_blocked_record_has_no_inputs(
    hr: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _job(hired)
    monkeypatch.setattr(history, "job_on", lambda employee, day: SimpleNamespace(pk=record.pk + 1))
    response = _as(hr).get(CORRECT_EDITOR, {"person": hired.pk, "key": "department", "record": record.pk})
    body = response.json()
    assert body["blocked"] == report_corrections.NOT_CURRENT
    assert body["choices"] == []
    assert body["reason"] is False


def test_correct_post_saves_the_correction(hr: User, hired: Employee) -> None:
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    response = _post(
        _as(hr),
        CORRECT,
        {
            "person": hired.pk,
            "key": "department",
            "record": record.pk,
            "value": str(dept.pk),
            "old": "Санхүү",
            "reason": "Бичлэгийн алдаа",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "text": "Үйлдвэрлэл", "error": "", "editor": None}
    assert response["Cache-Control"] == "no-store"
    assert JobRecord.objects.get(pk=record.pk).department_id == dept.pk


def test_correct_post_clash_gives_the_current_text(hr: User, hired: Employee) -> None:
    dept = macs_writes.save_department("Худалдаа")
    record = _job(hired)
    response = _post(
        _as(hr),
        CORRECT,
        {
            "person": hired.pk,
            "key": "department",
            "record": record.pk,
            "value": str(dept.pk),
            "old": "Хуучин хэлтэс",
            "reason": "Шалтгаан",
        },
    )
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == CLASH
    assert body["editor"]["old"] == "Санхүү"


def test_correct_post_blocked_writes_nothing(hr: User, hired: Employee, monkeypatch: pytest.MonkeyPatch) -> None:
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    before = record.department_id
    monkeypatch.setattr(history, "job_on", lambda employee, day: SimpleNamespace(pk=record.pk + 1))
    response = _post(
        _as(hr),
        CORRECT,
        {
            "person": hired.pk,
            "key": "department",
            "record": record.pk,
            "value": str(dept.pk),
            "old": "Санхүү",
            "reason": "Шалтгаан",
        },
    )
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == report_corrections.NOT_CURRENT
    assert body["editor"]["blocked"] == report_corrections.NOT_CURRENT
    monkeypatch.undo()
    assert JobRecord.objects.get(pk=record.pk).department_id == before


def test_correct_post_without_the_right_is_403_and_writes_nothing(accountant: User, hired: Employee) -> None:
    dept = macs_writes.save_department("Үйлдвэрлэл")
    record = _job(hired)
    before = record.department_id
    response = _post(
        _as(accountant),
        CORRECT,
        {
            "person": hired.pk,
            "key": "department",
            "record": record.pk,
            "value": str(dept.pk),
            "old": "Санхүү",
            "reason": "Шалтгаан",
        },
    )
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_BODY
    assert JobRecord.objects.get(pk=record.pk).department_id == before


# --- fix round 1: 401 on the POSTs, a choice field, a non-ASCII digit, the route order ---


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (CELL, {"person": 1, "field": "private_phone", "value": "1", "loaded": ""}),
        (ROW, {"person": 1, "kind": "family", "key": 1, "field": "given_name", "values": {}}),
        (CORRECT, {"person": 1, "key": "salary", "record": None, "value": "1", "old": "", "reason": "x"}),
    ],
)
def test_posts_require_login(path: str, body: dict[str, Any]) -> None:
    response = _post(_as(None), path, body)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_choice_field_saves_a_valid_option_and_refuses_a_forged_one(hr: User, hired: Employee) -> None:
    client = _as(hr)
    editor = client.get(CELL_EDITOR, {"person": hired.pk, "field": "gender"}).json()
    assert editor["kind"] == "choice"
    valid = next(c["value"] for c in editor["choices"] if c["value"] not in ("", hired.gender))

    forged = _post(
        client, CELL, {"person": hired.pk, "field": "gender", "value": "ZZ-NOT-AN-OPTION", "loaded": editor["loaded"]}
    ).json()
    assert forged["ok"] is False
    assert forged["error"] != ""
    assert forged["error"] != CLASH
    assert forged["editor"]["kind"] == "choice"
    hired.refresh_from_db()
    assert hired.gender == "F"  # nothing written

    saved = _post(client, CELL, {"person": hired.pk, "field": "gender", "value": valid, "loaded": editor["loaded"]})
    assert saved.json()["ok"] is True
    hired.refresh_from_db()
    assert hired.gender == valid


def test_record_with_a_non_ascii_digit_is_404_not_500(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CORRECT_EDITOR, {"person": hired.pk, "key": "department", "record": "²"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY


@pytest.mark.parametrize("editor_path", [CELL_EDITOR, ROW_EDITOR, CORRECT_EDITOR])
def test_editor_get_without_parameters_is_the_edit_router(hr: User, editor_path: str) -> None:
    # Were the edit router registered after /reports/{key}, this GET would be read as a report key (404 report message).
    # The edit router answers the missing parameters itself: 400 with field errors.
    response = _as(hr).get(editor_path)
    assert response.status_code == 400
    assert response.json()["field_errors"] != {}


@pytest.mark.parametrize("post_path", [CELL, ROW, CORRECT])
def test_post_without_a_body_is_the_edit_router(hr: User, post_path: str) -> None:
    # The report router has no POST on /reports/{key}, so a bare POST would be 405. The edit router validates the body.
    response = _post(_as(hr), post_path, {})
    assert response.status_code == 400
    assert response.json()["field_errors"] != {}


# --- every answer of an editor route is no-store, the errors too (the stale token and the values are in the body) ----


def test_cell_editor_404_is_no_store(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CELL_EDITOR, {"person": hired.pk, "field": "salary"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY
    assert response["Cache-Control"] == "no-store"


def test_cell_editor_403_is_no_store(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CELL_EDITOR, {"person": hired.pk, "field": "account_no"})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_BODY
    assert response["Cache-Control"] == "no-store"


def test_cell_post_404_is_no_store(hr: User, hired: Employee) -> None:
    response = _post(_as(hr), CELL, {"person": hired.pk, "field": "salary", "value": "1", "loaded": ""})
    assert response.status_code == 404
    assert response["Cache-Control"] == "no-store"


def test_cell_post_403_is_no_store(hr: User, hired: Employee) -> None:
    response = _post(_as(hr), CELL, {"person": hired.pk, "field": "account_no", "value": "999", "loaded": ""})
    assert response.status_code == 403
    assert response["Cache-Control"] == "no-store"


def test_row_editor_404_is_no_store(hr: User, hired: Employee) -> None:
    response = _as(hr).get(ROW_EDITOR, {"person": hired.pk, "kind": "nope", "key": 1, "field": "x"})
    assert response.status_code == 404
    assert response["Cache-Control"] == "no-store"


def test_correct_editor_403_is_no_store(hr: User, hired: Employee) -> None:
    response = _as(hr).get(CORRECT_EDITOR, {"person": hired.pk, "key": "salary"})
    assert response.status_code == 403
    assert response["Cache-Control"] == "no-store"


def test_bulk_400_is_no_store(hr: User) -> None:
    response = _post(_as(hr), f"{BASE}/cells", {"apply": "yes", "cells": []})
    assert response.status_code == 400
    assert response["Cache-Control"] == "no-store"
