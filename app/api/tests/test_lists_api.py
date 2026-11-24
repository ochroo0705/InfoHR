"""GET /api/v1/lists, GET /api/v1/lists/meaning, GET /api/v1/lists/{slug} and GET /api/v1/lists/{slug}/form: the Lists
screen's read side as the React page reads it. The rules come from lists.service; these tests pin the shapes, the
search, the rights (lists.manage_lists) and the 404s."""

from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from lists.models import DEATH, MONGOLIA, MeaningfulEntry
from lists.registry import LISTS, MEANINGS
from macs.models import Bank, City, ClothesSize, Country, District

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
INDEX = "/api/v1/lists"
MEANING = "/api/v1/lists/meaning"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
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


@pytest.fixture
def hr() -> User:
    return _user("lists_api_hr", roles.HR)


@pytest.fixture
def plain() -> Client:
    """A logged-in user with no lists right."""
    return _client(_user("lists_api_employee", roles.EMPLOYEE))


def _items(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["slug"]: item for item in body["items"]}


def test_every_route_requires_login_and_the_right(hr: User, plain: Client) -> None:
    urls = [INDEX, MEANING, "/api/v1/lists/bank", "/api/v1/lists/bank/form"]
    for url in urls:
        anonymous = Client().get(url)
        assert anonymous.status_code == 401, url
        assert anonymous.json() == NOT_LOGGED_IN, url

        refused = plain.get(url)
        assert refused.status_code == 403, url
        assert refused.json() == FORBIDDEN, url

        assert _client(hr).get(url).status_code == 200, url


def test_index_shape_and_counts(hr: User) -> None:
    Bank.objects.create(name="Зэс банк")
    body = _client(hr).get(INDEX).json()

    assert body["q"] == ""
    assert body["show_meanings"] is True
    assert body["meanings_count"] == len(MEANINGS)
    assert len(body["items"]) == len(LISTS)
    assert _items(body)["bank"] == {"slug": "bank", "label": "Банк", "count": 1, "hits": 0}


def test_empty_search_lists_every_list(hr: User) -> None:
    body = _client(hr).get(INDEX, {"q": "   "}).json()

    assert body["q"] == ""
    assert {item["hits"] for item in body["items"]} == {0}
    assert len(body["items"]) == len(LISTS)


def test_word_matching_an_entry_name_gives_hits(hr: User) -> None:
    Bank.objects.create(name="Зэс банк")
    Bank.objects.create(name="Хаан банк")
    body = _client(hr).get(INDEX, {"q": "  ЗЭС "}).json()

    assert body["q"] == "ЗЭС"
    assert _items(body)["bank"]["hits"] == 1
    assert _items(body)["bank"]["count"] == 2
    assert body["show_meanings"] is False


def test_word_matching_a_list_label_gives_no_hits(hr: User) -> None:
    Bank.objects.create(name="Зэс банк")
    body = _client(hr).get(INDEX, {"q": "банк"}).json()

    assert _items(body)["bank"]["hits"] == 0
    assert _items(body)["bank"]["count"] == 1


def test_show_meanings_follows_the_search(hr: User) -> None:
    client = _client(hr)
    assert client.get(INDEX, {"q": "утгын"}).json()["show_meanings"] is True
    assert client.get(INDEX, {"q": "банк"}).json()["show_meanings"] is False


def test_meaning_rows_shape(hr: User) -> None:
    Country.objects.create(id=-1, name="")
    mongolia = Country.objects.create(id=5, name="Монгол")
    MeaningfulEntry.objects.create(key=MONGOLIA, value=mongolia.pk)
    body = _client(hr).get(MEANING).json()

    rows = {row["key"]: row for row in body["rows"]}
    assert set(rows) == set(MEANINGS)
    assert rows[MONGOLIA]["label"] == "Монгол улс"
    assert rows[MONGOLIA]["current"] == 5
    assert {"value": 5, "label": "Монгол"} in rows[MONGOLIA]["options"]
    assert {"value": -1, "label": "-1"} in rows[MONGOLIA]["options"]  # an empty name shows its pk
    assert rows[DEATH]["current"] is None
    assert rows[DEATH]["hint"] == MEANINGS[DEATH].hint


def test_list_page_shows_the_label_of_a_choice(hr: User) -> None:
    ClothesSize.objects.create(name="42", size_type="shoes")
    body = _client(hr).get("/api/v1/lists/sizes").json()

    assert body["slug"] == "sizes"
    assert body["label"] == "Хувцас, гутлын хэмжээ"
    assert [column["name"] for column in body["columns"]] == ["name", "size_type", "size_men", "size_women"]
    assert body["columns"][1] == {"name": "size_type", "label": "Төрөл"}
    row = body["rows"][0]
    assert row["cells"][0] == "42"
    assert row["cells"][1] == "Гутал"
    assert row["cells"][2] == ""  # a None value is an empty cell


def test_district_list_has_a_city_column(hr: User) -> None:
    city = City.objects.create(name="Улаанбаатар")
    District.objects.create(name="Баянзүрх", city=city)
    body = _client(hr).get("/api/v1/lists/district").json()

    assert [column["name"] for column in body["columns"]] == ["name", "city"]
    assert body["columns"][1]["label"] == "Аймаг, хот"
    assert body["rows"][0]["cells"] == ["Баянзүрх", "Улаанбаатар"]
    assert isinstance(body["rows"][0]["id"], int)


def test_add_form_for_bank_has_one_required_text_field(hr: User) -> None:
    body = _client(hr).get("/api/v1/lists/bank/form").json()

    assert body["title"] == "Банк"
    assert body["can_delete"] is False
    assert len(body["fields"]) == 1
    field = body["fields"][0]
    assert field["name"] == "name"
    assert field["kind"] == "text"
    assert field["required"] is True
    assert field["max_length"] == 100
    assert field["value"] == ""
    assert field["choices"] == []
    assert field["errors"] == []


def test_edit_form_is_filled_and_can_delete(hr: User) -> None:
    bank = Bank.objects.create(name="Хаан банк")
    body = _client(hr).get("/api/v1/lists/bank/form", {"pk": str(bank.pk)}).json()

    assert body["title"] == "Банк: засах"
    assert body["can_delete"] is True
    assert body["fields"][0]["value"] == "Хаан банк"


def test_choice_field_of_a_form_lists_its_options(hr: User) -> None:
    size = ClothesSize.objects.create(name="M", size_type="clothes")
    body = _client(hr).get("/api/v1/lists/sizes/form", {"pk": str(size.pk)}).json()

    size_type = next(field for field in body["fields"] if field["name"] == "size_type")
    assert size_type["kind"] == "select"
    assert size_type["value"] == "clothes"
    assert size_type["choices"][0] == {"value": "", "label": ""}
    assert {"value": "shoes", "label": "Гутал"} in size_type["choices"]


def test_unknown_slug_is_404(hr: User) -> None:
    client = _client(hr)
    response = client.get("/api/v1/lists/no_such_list")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert client.get("/api/v1/lists/no_such_list/form").status_code == 404


def test_quick_only_list_is_404(hr: User) -> None:
    # department is in QUICK but not in LISTS: the Lists screen does not serve it
    assert _client(hr).get("/api/v1/lists/department").status_code == 404


def test_unknown_pk_is_404(hr: User) -> None:
    response = _client(hr).get("/api/v1/lists/bank/form", {"pk": "999999"})
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_negative_pk_works(hr: User) -> None:
    Bank.objects.create(id=-1, name="Хаан банк (MACS)")
    client = _client(hr)

    form = client.get("/api/v1/lists/bank/form", {"pk": "-1"})
    assert form.status_code == 200
    assert form.json()["fields"][0]["value"] == "Хаан банк (MACS)"
    assert form.json()["can_delete"] is True

    page = client.get("/api/v1/lists/bank").json()
    assert {"id": -1, "cells": ["Хаан банк (MACS)"]} in page["rows"]


def test_out_of_range_or_junk_pk_is_404(hr: User) -> None:
    client = _client(hr)
    assert client.get("/api/v1/lists/bank/form", {"pk": "2147483648"}).status_code == 404
    assert client.get("/api/v1/lists/bank/form", {"pk": "-x"}).status_code == 404
