"""POST /api/v1/lists/{slug}/quick: the quick-add of a list entry from a form dropdown.

The rules come from lists.service.quick_add (the same as the Django quick-add view). The reply is the shape
web/src/widgets/Select.tsx reads: {value, label, existed} on success, and 400 {error, field_errors} on a form error.
Both body shapes are accepted: {"values": {...}} and the plain {"name": "..."} that Select posts for a plain list."""

import json
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from employees.models import DepartmentExt, PositionExt
from macs.models import City, Country, Department, District, MaritalStatus, Position

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"]}


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _quick(client: Client, slug: str, body: dict[str, Any]) -> Any:
    return client.post(f"/api/v1/lists/{slug}/quick", data=json.dumps(body), content_type="application/json")


@pytest.fixture
def hr() -> Client:
    return _client(_user("lists_quick_hr", roles.HR))


@pytest.fixture
def plain() -> Client:
    return _client(_user("lists_quick_employee", roles.EMPLOYEE))


def test_new_name_is_created_and_returned(hr: Client) -> None:
    response = _quick(hr, "marital_status", {"values": {"name": "  Шинээр гэрлэсэн  "}})
    assert response.status_code == 200
    entry = MaritalStatus.objects.get(name="Шинээр гэрлэсэн")
    assert response.json() == {"value": entry.pk, "label": "Шинээр гэрлэсэн", "existed": False}


def test_plain_name_body_works(hr: Client) -> None:
    response = _quick(hr, "marital_status", {"name": "Салсан"})
    assert response.status_code == 200
    entry = MaritalStatus.objects.get(name="Салсан")
    assert response.json() == {"value": entry.pk, "label": "Салсан", "existed": False}


def test_duplicate_name_picks_the_old_entry_and_creates_nothing(hr: Client) -> None:
    existing = MaritalStatus.objects.create(name="Гэрлэсэн")
    response = _quick(hr, "marital_status", {"name": " гэрлэсэн "})
    assert response.status_code == 200
    assert response.json() == {"value": existing.pk, "label": "Гэрлэсэн", "existed": True}
    assert MaritalStatus.objects.filter(name__iexact="гэрлэсэн").count() == 1


def test_district_same_name_in_same_city_is_existing(hr: Client) -> None:
    city = City.objects.create(name="Улаанбаатар")
    kept = District.objects.create(name="Хан-Уул", city=city)
    response = _quick(hr, "district", {"values": {"name": "хан-уул", "city": str(city.pk)}})
    assert response.json() == {"value": kept.pk, "label": "Хан-Уул", "existed": True}
    assert District.objects.filter(city=city).count() == 1


def test_district_same_name_in_other_city_is_a_new_entry(hr: Client) -> None:
    ub = City.objects.create(name="Улаанбаатар")
    other = City.objects.create(name="Дархан")
    District.objects.create(name="Хан-Уул", city=ub)
    response = _quick(hr, "district", {"values": {"name": "Хан-Уул", "city": str(other.pk)}})
    assert response.status_code == 200
    assert response.json()["existed"] is False
    assert District.objects.filter(name="Хан-Уул", city=other).exists()


def test_district_without_city_is_a_field_error(hr: Client) -> None:
    response = _quick(hr, "district", {"values": {"name": "Хан-Уул"}})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]
    assert "city" in body["field_errors"]
    assert not District.objects.filter(name="Хан-Уул").exists()


def test_modal_list_saves_with_its_extra_field(hr: Client) -> None:
    response = _quick(hr, "country", {"values": {"name": "Япон", "code": "JP"}})
    assert response.status_code == 200
    country = Country.objects.get(name="Япон", code="JP")
    assert response.json() == {"value": country.pk, "label": "Япон", "existed": False}


def test_too_long_name_is_400_with_field_errors_and_nothing_created(hr: Client) -> None:
    response = _quick(hr, "marital_status", {"name": "А" * 31})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]
    assert set(body["field_errors"]) == {"name"}
    assert not MaritalStatus.objects.filter(name__startswith="АААА").exists()


def test_department_is_created_through_its_writer(hr: Client) -> None:
    response = _quick(hr, "department", {"name": "Санхүү"})
    dep = Department.objects.get(name="Санхүү")
    assert response.json() == {"value": dep.pk, "label": "Санхүү", "existed": False}
    assert DepartmentExt.objects.filter(pk=dep.pk, active=True).exists()


def test_inactive_department_is_reactivated_and_returned(hr: Client) -> None:
    dep = Department.objects.create(name="Хуучин хэлтэс")
    DepartmentExt.objects.create(department=dep, active=False)
    response = _quick(hr, "department", {"name": "хуучин хэлтэс"})
    assert response.json() == {"value": dep.pk, "label": "Хуучин хэлтэс", "existed": True}
    assert DepartmentExt.objects.get(pk=dep.pk).active is True


def test_inactive_position_is_reactivated_and_returned(hr: Client) -> None:
    pos = Position.objects.create(name="Хуучин тушаал")
    PositionExt.objects.create(position=pos, active=False)
    response = _quick(hr, "position", {"name": "Хуучин тушаал"})
    assert response.json() == {"value": pos.pk, "label": "Хуучин тушаал", "existed": True}
    assert PositionExt.objects.get(pk=pos.pk).active is True


def test_no_right_is_403_and_nothing_created(plain: Client) -> None:
    response = _quick(plain, "marital_status", {"name": "Тест"})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert not MaritalStatus.objects.filter(name="Тест").exists()


def test_unknown_slug_is_404(hr: Client) -> None:
    response = _quick(hr, "no_such_list", {"name": "Тест"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
