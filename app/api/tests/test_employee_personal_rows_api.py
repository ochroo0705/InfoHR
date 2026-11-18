"""The personal-list row routes: GET .../personal/{kind}/form (the row pop-up), POST .../personal/{kind} (add),
POST .../personal/{kind}/{key} (edit) and POST .../personal/{kind}/{key}/delete. Three kinds cover the shapes: a plain
list (relative), the address whose districts follow its city, and a list with a typed choice (training)."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees.models import ActivityEntry, Employee
from employees.services import history, macs_writes, personal_rows
from employees.services import personal_writes as pw
from employees.tests.conftest import hire_values, named
from macs.models import AddressRow, City, District, PresentRow, PresentType, RelativeRow, TrainingRow

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
KINDS = ("relative", "address", "training")
ALL_KINDS = (*KINDS, "gift")
MODELS = {"relative": RelativeRow, "address": AddressRow, "training": TrainingRow, "gift": PresentRow}
# One field a test changes, the value MACS is made to hold meanwhile (the clash), and a required field to blank.
CHANGE = {
    "relative": ("given_name", "Болд"),
    "address": ("street", "Шинэ гудамж"),
    "training": ("description", "Шинэ курс"),
}
CLASH = {
    "relative": ("given_name", "Өөр"),
    "address": ("street", "Өөр гудамж"),
    "training": ("description", "Өөр курс"),
}
REQUIRED = {"relative": "given_name", "address": "city", "training": "tr_type"}
SHOWN = {
    "relative": ("given_name", "father_name", "phone", "description", "branch", "department", "position"),
    "address": ("city", "district", "street"),
    "training": ("tr_type", "description", "start_year", "start_date", "days", "amount", "pay_type", "training_center"),
}


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("employee_personal_rows_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    return user


def _hire(hr_user: User, register_no: str, order_number: str = "1") -> Employee:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    return history.hire(
        hire_values(register_no),
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number=order_number,
        order_date=date(2026, 1, 5),
    )


@pytest.fixture
def hired(hr_user: User) -> Employee:
    return _hire(hr_user, "УБ99112233")


@pytest.fixture
def other(hr_user: User, hired: Employee) -> Employee:
    return _hire(hr_user, "УБ99112234", order_number="2")


@pytest.fixture
def places(db: None) -> dict[str, Any]:
    city = named(City, "Улаанбаатар")
    other = named(City, "Дархан")
    return {
        "city": city,
        "district": District.objects.get_or_create(name="Баянзүрх", city=city)[0],
        "other_city": other,
        "other_district": District.objects.get_or_create(name="Дархан уул", city=other)[0],
        "present": named(PresentType, "Шинэ жил"),
    }


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _add_values(kind: str, places: dict[str, Any]) -> dict[str, str]:
    if kind == "address":
        return {"city": str(places["city"].pk), "district": str(places["district"].pk), "street": "БЗД 3-р хороо"}
    if kind == "training":
        return {
            "tr_type": "1",
            "description": "Python курс",
            "start_year": "2024",
            "start_date": "2024-03-01",
            "days": "5",
            "amount": "250,000",
            "pay_type": "3",
            "training_center": "Мэдээллийн төв",
        }
    if kind == "gift":
        return {
            "present_type": str(places["present"].pk),
            "pdate": "2026-01-01",
            "given_year": "2026",
            "childqty": "2",
            "child_age": "5",
            "price": "50,000",
            "given": "on",
            "note": "Бэлэг",
        }
    return {"given_name": "Дорж", "father_name": "Бат", "phone": "99112233", "description": "Эхнэр"}


def _base(employee: Employee, kind: str) -> str:
    return f"/api/v1/employees/{employee.pk}/personal/{kind}"


def _form(client: Client, employee: Employee, kind: str, key: int | None = None, **query: str) -> Any:
    params: dict[str, Any] = dict(query)
    if key is not None:
        params["key"] = key
    return client.get(f"{_base(employee, kind)}/form", params)


def _form_values(client: Client, employee: Employee, kind: str, key: int | None = None) -> dict[str, str]:
    """What the browser would post from the pop-up: each field's value, then the hidden loaded_* values."""
    response = _form(client, employee, kind, key)
    assert response.status_code == 200, response.content
    body = response.json()
    fields = {
        f["name"]: ("on" if f["checked"] else "") if f["kind"] == "checkbox" else f["value"] for f in body["fields"]
    }
    return {**fields, **body["hidden"]}


def _post(client: Client, url: str, values: dict[str, str]) -> Any:
    return client.post(url, data=json.dumps({"values": values}), content_type="application/json")


def _only_key(employee: Employee, kind: str) -> int:
    rows = personal_rows.rows(kind, employee)
    assert len(rows) == 1
    return int(rows[0].key)  # type: ignore[arg-type]


def _activity(employee: Employee, kind: str) -> int:
    return ActivityEntry.objects.filter(employee=employee, personal=True, message__startswith=pw.TITLES[kind]).count()


@pytest.mark.parametrize("kind", KINDS)
def test_add_form_gives_the_fields_and_the_hidden_loaded_values(hr_user: User, hired: Employee, kind: str) -> None:
    body = _form(_client(hr_user), hired, kind).json()
    assert body["title"] == f"{pw.TITLES[kind]}: нэмэх"
    assert body["can_delete"] is False
    names = {field["name"] for field in body["fields"]}
    assert set(SHOWN[kind]) <= names
    assert body["hidden"] and all(name.startswith("loaded_") for name in body["hidden"])
    assert "loaded_employee_id" in body["hidden"]


@pytest.mark.parametrize("kind", KINDS)
def test_edit_form_gives_the_stored_values_and_can_delete(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    assert _post(client, _base(hired, kind), _add_values(kind, places)).status_code == 200
    key = _only_key(hired, kind)
    body = _form(client, hired, kind, key).json()
    assert body["title"] == f"{pw.TITLES[kind]}: засах"
    assert body["can_delete"] is True
    assert "loaded_employee_id" in body["hidden"]
    shown = {field["name"]: field["value"] for field in body["fields"]}
    for name, value in _add_values(kind, places).items():
        if name != "amount":
            assert shown[name] == value, name


def test_training_type_is_a_choice_box(hr_user: User, hired: Employee) -> None:
    body = _form(_client(hr_user), hired, "training").json()
    tr_type = next(field for field in body["fields"] if field["name"] == "tr_type")
    assert tr_type["kind"] == "select"
    assert {choice["value"] for choice in tr_type["choices"]} >= {"1", "2"}


@pytest.mark.parametrize("kind", KINDS)
def test_add_with_a_missing_required_field_gives_field_errors(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    values = {**_add_values(kind, places), REQUIRED[kind]: ""}
    response = _post(_client(hr_user), _base(hired, kind), values)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert REQUIRED[kind] in body["field_errors"]
    assert MODELS[kind].objects.filter(employee=hired).count() == 0


@pytest.mark.parametrize("kind", KINDS)
def test_add_edit_delete_round_trip_changes_the_rows_and_logs_each_write(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    name, new = CHANGE[kind]

    assert _post(client, _base(hired, kind), _add_values(kind, places)).json()["ok"] is True
    assert len(personal_rows.rows(kind, hired)) == 1
    key = _only_key(hired, kind)
    assert _activity(hired, kind) == 1

    values = {**_form_values(client, hired, kind, key), name: new}
    edit = _post(client, f"{_base(hired, kind)}/{key}", values)
    assert edit.status_code == 200, edit.content
    assert edit.json()["ok"] is True
    assert getattr(MODELS[kind].objects.get(pk=key), name) == new
    assert _activity(hired, kind) == 2

    delete = _post(client, f"{_base(hired, kind)}/{key}/delete", _form_values(client, hired, kind, key))
    assert delete.status_code == 200, delete.content
    assert delete.json() == {
        "ok": True,
        "field_errors": {},
        "form_errors": [],
        "conflicts": {},
        "loaded": "",
        "si_loaded": "",
        "tab": "",
    }
    assert personal_rows.rows(kind, hired) == []
    assert _activity(hired, kind) == 3


@pytest.mark.parametrize("kind", KINDS)
def test_edit_after_the_stored_value_changed_is_a_form_error_and_writes_nothing(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    name, new = CHANGE[kind]
    clash_name, clash = CLASH[kind]
    _post(client, _base(hired, kind), _add_values(kind, places))
    key = _only_key(hired, kind)
    values = {**_form_values(client, hired, kind, key), name: new}
    MODELS[kind].objects.filter(pk=key).update(**{clash_name: clash})  # MACS changed the row meanwhile
    logged = _activity(hired, kind)

    response = _post(client, f"{_base(hired, kind)}/{key}", values)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["form_errors"] == [pw.STALE]
    assert body["field_errors"] == {}
    assert getattr(MODELS[kind].objects.get(pk=key), clash_name) == clash
    assert _activity(hired, kind) == logged


@pytest.mark.parametrize("kind", KINDS)
def test_delete_after_the_stored_value_changed_is_a_form_error(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    clash_name, clash = CLASH[kind]
    _post(client, _base(hired, kind), _add_values(kind, places))
    key = _only_key(hired, kind)
    values = _form_values(client, hired, kind, key)
    MODELS[kind].objects.filter(pk=key).update(**{clash_name: clash})

    body = _post(client, f"{_base(hired, kind)}/{key}/delete", values).json()
    assert body["ok"] is False
    assert body["form_errors"] == [pw.STALE]
    assert len(personal_rows.rows(kind, hired)) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_edit_and_delete_without_the_loaded_values_are_400_and_write_nothing(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    name, new = CHANGE[kind]
    _post(client, _base(hired, kind), _add_values(kind, places))
    key = _only_key(hired, kind)
    stored = _form_values(client, hired, kind, key)
    without_loaded = {k: v for k, v in stored.items() if not k.startswith("loaded_")}

    edit = _post(client, f"{_base(hired, kind)}/{key}", {**without_loaded, name: new})
    assert edit.status_code == 400
    assert edit.json()["form_errors"]
    delete = _post(client, f"{_base(hired, kind)}/{key}/delete", without_loaded)
    assert delete.status_code == 400
    assert delete.json()["form_errors"]
    assert len(personal_rows.rows(kind, hired)) == 1
    assert getattr(MODELS[kind].objects.get(pk=key), name) != new


def test_address_districts_follow_the_city_in_the_pop_up(
    hr_user: User, hired: Employee, places: dict[str, Any]
) -> None:
    client = _client(hr_user)

    def district_choices(response: Any) -> set[str]:
        field = next(f for f in response.json()["fields"] if f["name"] == "district")
        return {choice["value"] for choice in field["choices"] if choice["value"]}

    assert district_choices(_form(client, hired, "address")) == set()  # no city yet: no districts offered
    assert district_choices(_form(client, hired, "address", city=str(places["city"].pk))) == {
        str(places["district"].pk)
    }
    assert district_choices(_form(client, hired, "address", city=str(places["other_city"].pk))) == {
        str(places["other_district"].pk)
    }


def test_address_edit_pop_up_keeps_the_presets_the_user_typed(
    hr_user: User, hired: Employee, places: dict[str, Any]
) -> None:
    client = _client(hr_user)
    _post(client, _base(hired, "address"), _add_values("address", places))
    key = _only_key(hired, "address")
    body = _form(client, hired, "address", key, street="Өөр гудамж").json()
    street = next(f for f in body["fields"] if f["name"] == "street")
    assert street["value"] == "Өөр гудамж"


@pytest.mark.parametrize("kind", KINDS)
def test_user_without_the_personal_right_is_403(hired: Employee, places: dict[str, Any], kind: str) -> None:
    manager = User.objects.create_user("employee_personal_rows_manage_only", password=PASSWORD)
    manager.user_permissions.add(
        Permission.objects.get(content_type__app_label="macs", codename="manage_employees"),
        Permission.objects.get(content_type__app_label="macs", codename="view_employees"),
    )
    client = _client(manager)
    assert _form(client, hired, kind).status_code == 403
    add = _post(client, _base(hired, kind), _add_values(kind, places))
    assert add.status_code == 403
    assert add.json()["code"] == "forbidden"
    assert _post(client, f"{_base(hired, kind)}/1", {}).status_code == 403
    assert _post(client, f"{_base(hired, kind)}/1/delete", {}).status_code == 403
    assert MODELS[kind].objects.filter(employee=hired).count() == 0


def test_unknown_kind_or_form_row_is_404(hr_user: User, hired: Employee, places: dict[str, Any]) -> None:
    client = _client(hr_user)
    assert _form(client, hired, "nope").status_code == 404
    assert _post(client, _base(hired, "nope"), {}).status_code == 404
    assert _post(client, f"{_base(hired, 'nope')}/1", {}).status_code == 404
    assert _post(client, f"{_base(hired, 'nope')}/1/delete", {}).status_code == 404
    assert _form(client, hired, "relative", key=999999).status_code == 404


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_edit_and_delete_of_a_row_removed_meanwhile_are_stale_refusals(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    _post(client, _base(hired, kind), _add_values(kind, places))
    key = _only_key(hired, kind)
    values = _form_values(client, hired, kind, key)
    MODELS[kind].objects.filter(pk=key).delete()  # another user removed the row after the form opened

    for response in (
        _post(client, f"{_base(hired, kind)}/{key}", values),
        _post(client, f"{_base(hired, kind)}/{key}/delete", values),
    ):
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["form_errors"] == [pw.STALE]
    assert personal_rows.rows(kind, hired) == []


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_another_employees_row_key_is_a_stale_refusal_and_writes_nothing(
    hr_user: User, hired: Employee, other: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    _post(client, _base(other, kind), _add_values(kind, places))
    key = _only_key(other, kind)
    values = _form_values(client, other, kind, key)  # a valid snapshot of the other employee's row
    logged = _activity(other, kind)

    for response in (
        _post(client, f"{_base(hired, kind)}/{key}", values),
        _post(client, f"{_base(hired, kind)}/{key}/delete", values),
    ):
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["form_errors"] == [pw.STALE]
    assert len(personal_rows.rows(kind, other)) == 1
    assert personal_rows.rows(kind, hired) == []
    assert _activity(other, kind) == logged


def test_gift_given_checkbox_posts_on_then_empty_and_stores_1_then_0(
    hr_user: User, hired: Employee, places: dict[str, Any]
) -> None:
    client = _client(hr_user)
    assert _post(client, _base(hired, "gift"), _add_values("gift", places)).json()["ok"] is True
    key = _only_key(hired, "gift")
    assert PresentRow.objects.get(pk=key).given == 1

    values = {**_form_values(client, hired, "gift", key), "given": ""}
    assert _post(client, f"{_base(hired, 'gift')}/{key}", values).json()["ok"] is True
    assert PresentRow.objects.get(pk=key).given == 0

    values = {**_form_values(client, hired, "gift", key), "given": "on"}  # a fresh snapshot after the last write
    assert _post(client, f"{_base(hired, 'gift')}/{key}", values).json()["ok"] is True
    assert PresentRow.objects.get(pk=key).given == 1


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_a_partial_loaded_set_is_400_and_writes_nothing(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    _post(client, _base(hired, kind), _add_values(kind, places))
    key = _only_key(hired, kind)
    values = _form_values(client, hired, kind, key)
    loaded = next(name for name in values if name.startswith("loaded_"))
    partial = {name: value for name, value in values.items() if name != loaded}  # one loaded value missing
    before = list(MODELS[kind].objects.filter(pk=key).values_list("pk", flat=True))

    assert _post(client, f"{_base(hired, kind)}/{key}", partial).status_code == 400
    assert _post(client, f"{_base(hired, kind)}/{key}/delete", partial).status_code == 400
    assert list(MODELS[kind].objects.filter(pk=key).values_list("pk", flat=True)) == before
    assert len(personal_rows.rows(kind, hired)) == 1


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_a_malformed_loaded_value_is_400_and_writes_nothing(
    hr_user: User, hired: Employee, places: dict[str, Any], kind: str
) -> None:
    client = _client(hr_user)
    _post(client, _base(hired, kind), _add_values(kind, places))
    key = _only_key(hired, kind)
    values = _form_values(client, hired, kind, key)
    loaded = next(name for name in values if name.startswith("loaded_"))
    malformed = {**values, loaded: "{not json"}

    assert _post(client, f"{_base(hired, kind)}/{key}", malformed).status_code == 400
    assert _post(client, f"{_base(hired, kind)}/{key}/delete", malformed).status_code == 400
    assert len(personal_rows.rows(kind, hired)) == 1


def test_a_non_string_value_is_a_clean_400(hr_user: User, hired: Employee) -> None:
    response = _post(_client(hr_user), _base(hired, "relative"), {"given_name": 5})  # type: ignore[dict-item]
    assert response.status_code == 400
    assert RelativeRow.objects.filter(employee=hired).count() == 0
