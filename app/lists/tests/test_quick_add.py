import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from employees.forms import EmployeeForm, HireJobForm
from employees.models import DepartmentExt, PositionExt
from macs.models import City, ClothesSize, Country, Department, District, MaritalStatus, Position


def _post(client: Client, slug: str, data: dict[str, str]):  # type: ignore[no-untyped-def]
    return client.post(f"/lists/{slug}/quick/", data)


@pytest.mark.django_db
def test_name_only_list_is_created_and_returned(admin_client: Client) -> None:
    response = _post(admin_client, "marital_status", {"name": "  Шинээр гэрлэсэн  "})
    assert response.status_code == 200
    entry = MaritalStatus.objects.get(name="Шинээр гэрлэсэн")
    assert json.loads(response.content) == {"id": entry.pk, "name": "Шинээр гэрлэсэн", "existed": False}


@pytest.mark.django_db
def test_duplicate_name_returns_existing_entry_and_creates_nothing(admin_client: Client) -> None:
    existing = MaritalStatus.objects.create(name="Гэрлэсэн")
    response = _post(admin_client, "marital_status", {"name": " гэрлэсэн "})
    assert response.status_code == 200
    assert json.loads(response.content) == {"id": existing.pk, "name": "Гэрлэсэн", "existed": True}
    assert MaritalStatus.objects.filter(name__iexact="гэрлэсэн").count() == 1


@pytest.mark.django_db
def test_too_long_name_is_a_field_error(admin_client: Client) -> None:
    response = _post(admin_client, "marital_status", {"name": "А" * 31})
    assert response.status_code == 400
    assert "error" in json.loads(response.content)
    assert not MaritalStatus.objects.filter(name__startswith="АААА").exists()


@pytest.mark.django_db
def test_user_without_permission_is_refused(client: Client) -> None:
    user = get_user_model().objects.create_user(username="plain")
    client.force_login(user)
    assert _post(client, "marital_status", {"name": "Тест"}).status_code == 403
    assert client.get("/lists/country/quick/?name=Тест").status_code == 403
    assert not MaritalStatus.objects.filter(name="Тест").exists()


@pytest.mark.django_db
def test_name_only_list_has_no_modal(admin_client: Client) -> None:
    assert admin_client.get("/lists/marital_status/quick/").status_code == 404


@pytest.mark.django_db
def test_modal_list_get_prefills_name(admin_client: Client) -> None:
    response = admin_client.get("/lists/country/quick/?name=Япон")
    assert response.status_code == 200
    assert 'value="Япон"'.encode() in response.content
    assert b"data-quick-form" in response.content


@pytest.mark.django_db
def test_modal_list_saves_with_extra_field(admin_client: Client) -> None:
    response = _post(admin_client, "country", {"name": "Япон", "code": "JP"})
    assert response.status_code == 200
    assert Country.objects.filter(name="Япон", code="JP").exists()


@pytest.mark.django_db
def test_modal_list_errors_come_back_as_modal(admin_client: Client) -> None:
    response = _post(admin_client, "sizes", {"name": "XL"})  # size_type is required
    assert response.status_code == 400
    assert b"data-quick-form" in response.content
    assert not ClothesSize.objects.filter(name="XL").exists()


@pytest.mark.django_db
def test_district_without_city_is_refused(admin_client: Client) -> None:
    response = _post(admin_client, "district", {"name": "Хан-Уул"})
    assert response.status_code == 400
    assert not District.objects.filter(name="Хан-Уул").exists()


@pytest.mark.django_db
def test_district_with_city_is_created(admin_client: Client) -> None:
    city = City.objects.create(name="Улаанбаатар")
    response = _post(admin_client, "district", {"name": "Хан-Уул", "city": str(city.pk)})
    assert response.status_code == 200
    assert District.objects.filter(name="Хан-Уул", city=city).exists()


@pytest.mark.django_db
def test_department_and_position_go_through_their_writers(admin_client: Client) -> None:
    response = _post(admin_client, "department", {"name": "Санхүү"})
    dep = Department.objects.get(name="Санхүү")
    assert json.loads(response.content)["id"] == dep.pk
    assert DepartmentExt.objects.filter(pk=dep.pk, active=True).exists()
    response = _post(admin_client, "position", {"name": "Нягтлан"})
    pos = Position.objects.get(name="Нягтлан")
    assert json.loads(response.content)["id"] == pos.pk
    assert PositionExt.objects.filter(pk=pos.pk, active=True).exists()
    again = _post(admin_client, "position", {"name": "нягтлан"})
    assert json.loads(again.content) == {"id": pos.pk, "name": "Нягтлан", "existed": True}


@pytest.mark.django_db
def test_addable_selects_carry_add_url_and_fixed_choices_do_not() -> None:
    form = HireJobForm()
    assert form["department"].field.widget.attrs["data-add-url"] == "/lists/department/quick/"
    assert form["position"].field.widget.attrs["data-add-url"] == "/lists/position/quick/"
    employee = EmployeeForm()
    assert employee["marital_status"].field.widget.attrs["data-add-url"] == "/lists/marital_status/quick/"
    assert "data-add-modal" in employee["clothing_size"].field.widget.attrs
    assert "data-add-url" not in employee["gender"].field.widget.attrs
    assert "data-add-url" not in employee["work_conditions"].field.widget.attrs


@pytest.mark.django_db
def test_district_same_name_in_same_city_is_existing(admin_client: Client) -> None:
    city = City.objects.create(name="Улаанбаатар")
    kept = District.objects.create(name="Хан-Уул", city=city)
    response = _post(admin_client, "district", {"name": "хан-уул", "city": str(city.pk)})
    assert json.loads(response.content) == {"id": kept.pk, "name": "Хан-Уул", "existed": True}
    assert District.objects.filter(city=city).count() == 1


@pytest.mark.django_db
def test_district_same_name_in_other_city_is_a_new_entry(admin_client: Client) -> None:
    ub = City.objects.create(name="Улаанбаатар")
    other = City.objects.create(name="Дархан")
    District.objects.create(name="Хан-Уул", city=ub)
    response = _post(admin_client, "district", {"name": "Хан-Уул", "city": str(other.pk)})
    assert response.status_code == 200
    assert json.loads(response.content)["existed"] is False
    assert District.objects.filter(name="Хан-Уул", city=other).exists()


@pytest.mark.django_db
def test_inactive_department_is_reactivated_and_returned(admin_client: Client) -> None:
    dep = Department.objects.create(name="Хуучин хэлтэс")
    DepartmentExt.objects.create(department=dep, active=False)
    response = _post(admin_client, "department", {"name": "хуучин хэлтэс"})
    assert json.loads(response.content) == {"id": dep.pk, "name": "Хуучин хэлтэс", "existed": True}
    assert DepartmentExt.objects.get(pk=dep.pk).active is True
    assert Department.objects.filter(name__iexact="хуучин хэлтэс").count() == 1


@pytest.mark.django_db
def test_inactive_position_is_reactivated_and_returned(admin_client: Client) -> None:
    pos = Position.objects.create(name="Хуучин тушаал")
    PositionExt.objects.create(position=pos, active=False)
    response = _post(admin_client, "position", {"name": "Хуучин тушаал"})
    assert json.loads(response.content)["existed"] is True
    assert PositionExt.objects.get(pk=pos.pk).active is True
