"""POST /api/v1/slots, POST /api/v1/slots/{pk} and POST /api/v1/slots/{pk}/delete: the position-slot screen's writes.

The form rules come from employees.views_slots.SlotForm and the writes from employees.services.slots; these tests pin
the API's answer (ok, field_errors, form_errors, id), the refusals that answer 200 with ok false, the log lines and the
right (only holders of employees.manage_position_slots)."""

import json
from typing import Any

import pytest
from accounts import roles
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.services import macs_writes, slots
from employees.services.slot_page import exists_message
from macs.models import Branch, NazgRow, Position

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/slots"
YEAR = timezone.localdate().year
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _post(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, data=json.dumps(body), content_type="application/json")


def _body(position: Position, branch: Branch, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"position": position.pk, "branch": branch.pk, "kind": "Main", "year": YEAR, "qty": 3}
    body.update(changes)
    return body


def _logged(action: str) -> list[SystemLogEntry]:
    return list(SystemLogEntry.objects.filter(action=action, category="hr"))


@pytest.fixture
def hr() -> User:
    return _user("slots_write_hr", roles.HR)


@pytest.fixture
def position() -> Position:
    return macs_writes.save_position("Нягтлан")


@pytest.fixture
def branch() -> Branch:
    return Branch.objects.create(name="Төв салбар")


@pytest.fixture
def other_branch() -> Branch:
    return Branch.objects.create(name="Баруун салбар")


def _row(position: Position, branch: Branch, qty: int, *, kind: str = "Main", year: int = YEAR) -> NazgRow:
    return NazgRow.objects.create(kind=kind, qty=qty, year=year, position=position, branch=branch)


def test_create_saves_row_and_logs(hr: User, position: Position, branch: Branch) -> None:
    response = _post(_client(hr), URL, _body(position, branch))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["field_errors"] == {} and body["form_errors"] == []
    row = NazgRow.objects.get(pk=body["id"])
    assert (row.position_id, row.branch_id, row.kind, row.year, row.qty) == (position.pk, branch.pk, "Main", YEAR, 3)
    entry = _logged("position_slot_added")
    assert len(entry) == 1
    assert entry[0].target_label == slots._describe(position, branch, "Main", YEAR)


def test_create_duplicate_key_refused_with_exists_message(hr: User, position: Position, branch: Branch) -> None:
    holder = _row(position, branch, 2)
    response = _post(_client(hr), URL, _body(position, branch, qty=5))
    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "id": None,
        "field_errors": {},
        "form_errors": [exists_message(holder)],
    }
    assert NazgRow.objects.filter(position=position, branch=branch).count() == 1
    assert not _logged("position_slot_added")


def test_create_invalid_values_report_fields(hr: User, position: Position, branch: Branch) -> None:
    response = _post(_client(hr), URL, _body(position, branch, qty=-1, year=1999))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and body["id"] is None
    assert set(body["field_errors"]) == {"qty", "year"}
    assert NazgRow.objects.count() == 0
    assert not _logged("position_slot_added")


def test_create_with_empty_boxes_returns_required_errors_from_the_form(hr: User) -> None:
    response = _post(_client(hr), URL, {"position": None, "branch": None, "kind": "", "year": None, "qty": None})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and body["id"] is None
    assert set(body["field_errors"]) == {"position", "branch", "kind", "year", "qty"}
    assert NazgRow.objects.count() == 0


def test_edit_changes_qty_and_keeps_key_unique(
    hr: User, position: Position, branch: Branch, other_branch: Branch
) -> None:
    client = _client(hr)
    first = _row(position, branch, 2)
    second = _row(position, other_branch, 1)

    moved_onto_first = _post(client, f"{URL}/{second.pk}", _body(position, branch, qty=1))
    assert moved_onto_first.json()["ok"] is False
    assert moved_onto_first.json()["form_errors"] == [exists_message(first)]
    second.refresh_from_db()
    assert second.branch_id == other_branch.pk

    changed = _post(client, f"{URL}/{second.pk}", _body(position, other_branch, qty=7))
    assert changed.status_code == 200
    assert changed.json() == {"ok": True, "id": second.pk, "field_errors": {}, "form_errors": []}
    second.refresh_from_db()
    assert second.qty == 7
    entry = _logged("position_slot_changed")
    assert len(entry) == 1
    assert "1 → 7" in entry[0].message


def test_edit_unknown_pk_404(hr: User, position: Position, branch: Branch) -> None:
    response = _post(_client(hr), f"{URL}/999999", _body(position, branch))
    assert response.status_code == 404
    assert NazgRow.objects.count() == 0


def test_delete_removes_row(hr: User, position: Position, branch: Branch) -> None:
    row = _row(position, branch, 2)
    response = _post(_client(hr), f"{URL}/{row.pk}/delete", {})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "id": None, "field_errors": {}, "form_errors": []}
    assert not NazgRow.objects.filter(pk=row.pk).exists()
    assert len(_logged("position_slot_deleted")) == 1


def test_delete_unknown_pk_404(hr: User) -> None:
    assert _post(_client(hr), f"{URL}/999999/delete", {}).status_code == 404


def test_write_denied_returns_message_not_500(
    hr: User, position: Position, branch: Branch, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row(position, branch, 2)
    client = _client(hr)

    def denied(*args: Any, **kwargs: Any) -> None:
        raise slots.SlotWriteDenied("Өгөгдлийн сангийн эрх дутуу")

    monkeypatch.setattr(slots, "save_row", denied)
    monkeypatch.setattr(slots, "delete_row", denied)

    created = _post(client, URL, _body(position, branch, year=YEAR + 1))
    assert created.status_code == 200
    assert created.json() == {
        "ok": False,
        "id": None,
        "field_errors": {},
        "form_errors": ["Өгөгдлийн сангийн эрх дутуу"],
    }
    edited = _post(client, f"{URL}/{row.pk}", _body(position, branch, qty=9))
    assert edited.json()["form_errors"] == ["Өгөгдлийн сангийн эрх дутуу"]
    deleted = _post(client, f"{URL}/{row.pk}/delete", {})
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is False
    assert NazgRow.objects.filter(pk=row.pk).exists()


def test_race_exists_between_check_and_write(
    hr: User, position: Position, branch: Branch, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder = _row(position, branch, 4)

    def taken(*args: Any, **kwargs: Any) -> None:
        raise slots.SlotRowExists(holder)

    monkeypatch.setattr(slots, "save_row", taken)
    response = _post(_client(hr), URL, _body(position, branch, year=YEAR + 1))
    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "id": None,
        "field_errors": {},
        "form_errors": [exists_message(holder)],
    }


def test_all_writes_need_permission(position: Position, branch: Branch) -> None:
    row = _row(position, branch, 2)
    employee = _client(_user("slots_write_employee", roles.EMPLOYEE))
    body = _body(position, branch)
    assert _post(employee, URL, body).json() == FORBIDDEN
    assert _post(employee, f"{URL}/{row.pk}", body).status_code == 403
    assert _post(employee, f"{URL}/{row.pk}/delete", {}).status_code == 403
    assert _post(employee, f"{URL}/999999", body).status_code == 403  # the right is checked before the lookup
    assert _post(employee, f"{URL}/999999/delete", {}).status_code == 403
    assert NazgRow.objects.filter(pk=row.pk).exists()


def test_writes_need_login(position: Position, branch: Branch) -> None:
    anonymous = Client()
    body = _body(position, branch)
    assert _post(anonymous, URL, body).json() == NOT_LOGGED_IN
    assert _post(anonymous, f"{URL}/1", body).status_code == 401
    assert _post(anonymous, f"{URL}/1/delete", {}).status_code == 401
