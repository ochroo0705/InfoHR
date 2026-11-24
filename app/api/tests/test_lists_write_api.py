"""POST /api/v1/lists/meaning, POST /api/v1/lists/{slug}, POST /api/v1/lists/{slug}/{pk} and
POST /api/v1/lists/{slug}/{pk}/delete: the Lists screen's writes.

The rules come from lists.service and the writes from employees.services.macs_writes (through the service). These tests
pin the answer (ok, form_errors, field_errors), the refusals that answer 200 with ok false and write nothing, the
404s and the right (lists.manage_lists). The Django pop-up writes no log line for a list entry (macs_writes has none),
so there is no log comparison here."""

import json
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from employees.services import macs_writes, records
from employees.tests.conftest import actor, hired, job_values  # noqa: F401  (shared employee fixtures)
from lists.models import DEATH, MONGOLIA, MeaningfulEntry
from macs.models import Bank, ClothesSize, Country, FiredReason, MaritalStatus

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
BANK = "/api/v1/lists/bank"
MEANING = "/api/v1/lists/meaning"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"]}
OK = {"ok": True, "form_errors": [], "field_errors": {}}
IN_USE = "1 ажилтан/бичлэг ашиглаж байгаа тул устгах боломжгүй."


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _post(client: Client, url: str, values: dict[str, str] | None = None) -> Any:
    body: dict[str, Any] = {"values": values} if values is not None else {}
    return client.post(url, data=json.dumps(body), content_type="application/json")


@pytest.fixture
def hr() -> Client:
    return _client(_user("lists_write_hr", roles.HR))


@pytest.fixture
def plain() -> Client:
    """A logged-in user with no lists right."""
    return _client(_user("lists_write_employee", roles.EMPLOYEE))


def test_add_saves_the_entry(hr: Client) -> None:
    response = _post(hr, BANK, {"name": "Зэс банк"})
    assert response.status_code == 200
    assert response.json() == OK
    assert Bank.objects.filter(name="Зэс банк").count() == 1


def test_invalid_add_reports_field_errors_and_writes_nothing(hr: Client) -> None:
    response = _post(hr, BANK, {"name": ""})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert set(body["field_errors"]) == {"name"}
    assert body["form_errors"] == []
    assert Bank.objects.count() == 0


def test_add_with_missing_choice_reports_the_choice_field(hr: Client) -> None:
    response = _post(hr, "/api/v1/lists/sizes", {"name": "XL"})  # size_type is required
    body = response.json()
    assert body["ok"] is False
    assert "size_type" in body["field_errors"]
    assert not ClothesSize.objects.filter(name="XL").exists()


def test_edit_renames_the_entry(hr: Client) -> None:
    bank = Bank.objects.create(name="Хаан банк")
    response = _post(hr, f"{BANK}/{bank.pk}", {"name": "Хаан банк (шинэ)"})
    assert response.status_code == 200
    assert response.json() == OK
    bank.refresh_from_db()
    assert bank.name == "Хаан банк (шинэ)"


def test_invalid_edit_keeps_the_old_name(hr: Client) -> None:
    bank = Bank.objects.create(name="Хаан банк")
    body = _post(hr, f"{BANK}/{bank.pk}", {"name": ""}).json()
    assert body["ok"] is False
    assert set(body["field_errors"]) == {"name"}
    bank.refresh_from_db()
    assert bank.name == "Хаан банк"


def test_edit_and_delete_unknown_or_junk_pk_is_404(hr: Client) -> None:
    for pk in ("999999", "abc", "99999999999"):
        assert _post(hr, f"{BANK}/{pk}", {"name": "Тест"}).status_code == 404, pk
        assert _post(hr, f"{BANK}/{pk}/delete").status_code == 404, pk
    assert Bank.objects.count() == 0


def test_negative_pk_is_edited(hr: Client) -> None:
    bank = Bank.objects.create(id=-7, name="Сөрөг банк")
    response = _post(hr, f"{BANK}/-7", {"name": "Сөрөг банк (шинэ)"})
    assert response.json() == OK
    bank.refresh_from_db()
    assert bank.name == "Сөрөг банк (шинэ)"


def test_delete_removes_an_unused_entry(hr: Client) -> None:
    bank = Bank.objects.create(name="Хэрэггүй банк")
    response = _post(hr, f"{BANK}/{bank.pk}/delete")
    assert response.status_code == 200
    assert response.json() == OK
    assert not Bank.objects.filter(pk=bank.pk).exists()


def test_delete_of_an_entry_in_use_is_refused_and_stays(hr: Client, request: pytest.FixtureRequest) -> None:
    employee = request.getfixturevalue("hired")
    by = request.getfixturevalue("actor")
    married = MaritalStatus.objects.create(name="Гэрлэсэн")
    records.update_employee(employee, {"marital_status": married}, by)
    # The employee has left: status inactive, emptype 3 (the same flags macs_writes uses for a leaver).
    macs_writes.update_employee_columns(employee, {"status": "inactive", "emptype": 3, "contract_flag": "no"})
    response = _post(hr, f"/api/v1/lists/marital_status/{married.pk}/delete")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["field_errors"] == {}
    assert body["form_errors"] == [IN_USE]
    assert MaritalStatus.objects.filter(pk=married.pk).exists()


def test_meaning_save_sets_clears_and_ignores(hr: Client) -> None:
    mongolia = Country.objects.create(id=5, name="Монгол")
    other = Country.objects.create(id=6, name="Япон")
    reason = FiredReason.objects.create(id=9, name="Нас барсан")
    MeaningfulEntry.objects.create(key=DEATH, value=reason.pk)

    response = _post(hr, MEANING, {MONGOLIA: str(mongolia.pk), DEATH: ""})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert MeaningfulEntry.get(MONGOLIA) == 5
    assert MeaningfulEntry.get(DEATH) is None  # an empty choice deletes the meaning

    _post(hr, MEANING, {MONGOLIA: "abc"})  # a junk value
    _post(hr, MEANING, {MONGOLIA: "999999"})  # a pk that is not in the list
    assert MeaningfulEntry.get(MONGOLIA) == 5
    _post(hr, MEANING, {MONGOLIA: str(other.pk)})
    assert MeaningfulEntry.get(MONGOLIA) == other.pk


def test_every_write_needs_the_lists_right(plain: Client) -> None:
    bank = Bank.objects.create(name="Хаан банк")
    assert _post(plain, BANK, {"name": "Тест"}).json() == FORBIDDEN
    assert _post(plain, f"{BANK}/{bank.pk}", {"name": "Тест"}).json() == FORBIDDEN
    assert _post(plain, f"{BANK}/{bank.pk}/delete").json() == FORBIDDEN
    assert _post(plain, MEANING, {MONGOLIA: "1"}).json() == FORBIDDEN
    assert _post(plain, f"{BANK}/999999/delete").status_code == 403  # the right is checked before the lookup
    assert Bank.objects.filter(pk=bank.pk, name="Хаан банк").exists()
    assert Bank.objects.count() == 1


def test_writes_need_login() -> None:
    anonymous = Client()
    assert _post(anonymous, BANK, {"name": "Тест"}).json() == NOT_LOGGED_IN
    assert _post(anonymous, f"{BANK}/1", {"name": "Тест"}).status_code == 401
    assert _post(anonymous, f"{BANK}/1/delete").status_code == 401
    assert _post(anonymous, MEANING, {}).status_code == 401
    assert Bank.objects.count() == 0


def test_unknown_slug_is_404(hr: Client) -> None:
    response = _post(hr, "/api/v1/lists/no_such_list", {"name": "Тест"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
