from datetime import date

import pytest
from django.db import IntegrityError, transaction

from macs.models import (
    AddressRow,
    City,
    ContactRow,
    ContactType,
    District,
    EducRow,
    EduType,
    Employee,
    FamilyRelation,
    FamilyRow,
    PresentRow,
    PresentType,
)


@pytest.fixture
def employee(db: None) -> Employee:
    return Employee.objects.create(given_name="Т", family_name="Б")


@pytest.fixture
def son() -> FamilyRelation:
    return FamilyRelation.objects.create(name="Хүү", fm_type="son")


@pytest.mark.django_db
def test_family_insert_uses_sequence(employee: Employee, son: FamilyRelation) -> None:
    row = FamilyRow.objects.create(employee=employee, relation=son, given_name="Бат")
    row.refresh_from_db()
    assert row.pk > 0
    assert row.employee_id == employee.pk
    assert row.relation_id == son.pk


@pytest.mark.django_db
def test_educ_roundtrip_start_date(employee: Employee) -> None:
    edu = EduType.objects.create(name="Бакалавр")
    row = EducRow.objects.create(employee=employee, edu_type=edu, startdate=date(2010, 9, 1), start_year=2010)
    row.refresh_from_db()
    assert row.startdate == date(2010, 9, 1)
    assert row.start_year == 2010


@pytest.mark.django_db
def test_present_unique_key_enforced(employee: Employee) -> None:
    ptype = PresentType.objects.create(name="Төрсөн өдөр")
    kwargs = {
        "employee": employee,
        "childqty": 1,
        "price": 1000,
        "given_year": 2026,
        "pdate": date(2026, 3, 1),
        "present_type": ptype,
        "child_age": 5,
        "given": 1,
    }
    PresentRow.objects.create(**kwargs)
    with pytest.raises(IntegrityError), transaction.atomic():
        PresentRow.objects.create(**kwargs)


@pytest.mark.django_db
def test_fm_type_check_enforced() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        FamilyRelation.objects.create(name="Х", fm_type="x")


@pytest.mark.django_db
def test_address_insert_roundtrip(employee: Employee) -> None:
    city = City.objects.create(name="Улаанбаатар")
    district = District.objects.create(name="Баянзүрх", city=city)
    row = AddressRow.objects.create(employee=employee, street="Уранчимэг 5", city=city, district=district)
    row.refresh_from_db()
    assert row.street == "Уранчимэг 5"
    assert row.city_id == city.pk
    assert row.district_id == district.pk


@pytest.mark.django_db
def test_contact_insert_roundtrip(employee: Employee) -> None:
    ctype = ContactType.objects.create(name="Утас")
    row = ContactRow.objects.create(employee=employee, contact_type=ctype, value="99112233", name="Дорж", relative="Ах")
    row.refresh_from_db()
    assert (row.value, row.name, row.relative) == ("99112233", "Дорж", "Ах")
