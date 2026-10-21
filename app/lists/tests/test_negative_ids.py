"""MACS lookup tables can hold negative ids (banks -1..-4 in the test copy). The Lists screen must still
open, edit, delete and use them (QC 2b)."""

import json

import pytest
from django.test import Client
from macs.models import Bank, City, Country, District

from lists.models import MONGOLIA, MeaningfulEntry


@pytest.fixture
def negative_bank() -> Bank:
    return Bank.objects.create(id=-1, name="Хаан банк (MACS)")


@pytest.mark.django_db
def test_list_page_links_to_negative_bank(admin_client: Client, negative_bank: Bank) -> None:
    response = admin_client.get("/lists/bank/")
    assert response.status_code == 200
    assert "/lists/bank/-1/" in response.content.decode()


@pytest.mark.django_db
def test_edit_page_opens_for_negative_bank(admin_client: Client, negative_bank: Bank) -> None:
    response = admin_client.get("/lists/bank/-1/")
    assert response.status_code == 200
    assert "Хаан банк (MACS)" in response.content.decode()


@pytest.mark.django_db
def test_edit_saves_negative_bank(admin_client: Client, negative_bank: Bank) -> None:
    response = admin_client.post("/lists/bank/-1/", {"name": "Хаан банк"})
    assert response.status_code == 204
    negative_bank.refresh_from_db()
    assert negative_bank.name == "Хаан банк"


@pytest.mark.django_db
def test_delete_removes_negative_bank(admin_client: Client, negative_bank: Bank) -> None:
    response = admin_client.post("/lists/bank/-1/delete/")
    assert response.status_code == 204
    assert not Bank.objects.filter(pk=-1).exists()


@pytest.mark.django_db
def test_negative_id_still_refuses_non_numeric_path(admin_client: Client) -> None:
    response = admin_client.get("/lists/bank/-x/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_district_quick_add_finds_duplicate_under_negative_city(admin_client: Client) -> None:
    city = City.objects.create(id=-2, name="Тест аймаг")
    district = District.objects.create(name="Сүхбаатар", city=city)
    response = admin_client.post("/lists/district/quick/", {"name": "сүхбаатар", "city": "-2"})
    assert response.status_code == 200
    assert json.loads(response.content) == {"id": district.pk, "name": "Сүхбаатар", "existed": True}
    assert District.objects.filter(name__iexact="сүхбаатар").count() == 1


@pytest.mark.django_db
def test_meaning_accepts_negative_country_id(admin_client: Client) -> None:
    Country.objects.create(id=-1, name="Монгол")
    admin_client.post("/lists/meaning/", {MONGOLIA: "-1"})
    assert MeaningfulEntry.get(MONGOLIA) == -1


@pytest.mark.django_db
@pytest.mark.parametrize("pk", ["99999999999", "2147483648", "-2147483649"])
def test_out_of_range_id_is_not_found(admin_client: Client, pk: str) -> None:
    assert admin_client.get(f"/lists/bank/{pk}/").status_code == 404
