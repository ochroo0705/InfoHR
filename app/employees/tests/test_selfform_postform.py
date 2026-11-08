"""Post-form conversion (answers_from_post / initial_from_answers) and the per-IP throttle."""

from urllib.parse import urlencode

import pytest
from django.core.cache import cache
from django.http import QueryDict

from employees.selfform import throttle
from employees.selfform.answers import (
    CONTACT_FIELDS,
    EDUCATION_FIELDS,
    MAX_EDUCATION,
    MAX_FAMILY,
    PERSON_FIELDS,
)
from employees.selfform.postform import answers_from_post, initial_from_answers


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


def _person() -> dict[str, str]:
    return {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "УБ99112233",
        "birth_date": "1999-11-22",
        "gender": "F",
        "work_phone": "99112233",
        "clan_name": "Бат",
        "email": "saraa@example.mn",
    }


def _stored() -> dict[str, object]:
    return {
        "person": _person(),
        "education": [
            {"org_name": "Сургууль", "start_year": "2010", "end_year": "2014", "edu_level": "3", "profession_type": ""},
            {"org_name": "Коллеж", "start_year": "2005", "end_year": "2008", "edu_level": "", "profession_type": "7"},
        ],
        "family": [
            {"relation": "2", "given_name": "Бат", "surname": "", "birth_date": "1970-01-01", "job": "", "phone": ""}
        ],
        "contact": {"contact_type": "1", "name": "Ээж", "relative": "Ээж", "value": "99001122"},
    }


def test_round_trip_stored_answers_through_the_form_names() -> None:
    stored = _stored()
    initial = initial_from_answers(stored)
    post = QueryDict(urlencode(initial))

    assert answers_from_post(post) == stored


def test_initial_uses_the_form_field_names() -> None:
    initial = initial_from_answers(_stored())

    assert initial["person-register_no"] == "УБ99112233"
    assert initial["edu-1-org_name"] == "Коллеж"
    assert initial["fam-0-relation"] == "2"
    assert initial["contact-value"] == "99001122"


def test_empty_answers_give_empty_shape() -> None:
    assert answers_from_post(QueryDict("")) == {
        "person": {name: "" for name in PERSON_FIELDS},
        "education": [],
        "family": [],
        "contact": {name: "" for name in CONTACT_FIELDS},
    }
    assert initial_from_answers({}) == {}


def test_blank_rows_are_skipped() -> None:
    post = QueryDict("edu-0-org_name=&edu-0-start_year=  &edu-1-org_name=Сургууль")

    rows = answers_from_post(post)["education"]

    assert [row["org_name"] for row in rows] == ["Сургууль"]


def test_rows_come_back_in_numeric_order() -> None:
    post = QueryDict("fam-10-given_name=Гурав&fam-2-given_name=Хоёр&fam-0-given_name=Нэг")

    names = [row["given_name"] for row in answers_from_post(post)["family"]]

    assert names == ["Нэг", "Хоёр", "Гурав"]


def test_gap_in_row_numbers_gives_only_the_filled_rows_in_index_order() -> None:
    """Index 1 is absent in one case and fully blank in the other: both leave exactly the rows at 0 and 2."""
    absent = QueryDict("edu-0-org_name=Нэг&edu-2-org_name=Хоёр&fam-0-given_name=Нэг&fam-2-given_name=Хоёр")
    blank = QueryDict(
        "edu-0-org_name=Нэг&edu-1-org_name=&edu-1-start_year=&edu-2-org_name=Хоёр"
        "&fam-0-given_name=Нэг&fam-1-given_name=&fam-2-given_name=Хоёр"
    )

    for post in (absent, blank):
        answers = answers_from_post(post)
        assert [row["org_name"] for row in answers["education"]] == ["Нэг", "Хоёр"]
        assert [row["given_name"] for row in answers["family"]] == ["Нэг", "Хоёр"]


def test_non_integer_and_oversized_indices_are_ignored() -> None:
    post = QueryDict("fam-x-given_name=Бат&fam-99999999-given_name=Бат&fam-1-given_name=Нэг&fam--given_name=Бат")

    rows = answers_from_post(post)["family"]

    assert [row["given_name"] for row in rows] == ["Нэг"]


def test_unknown_suffixes_are_ignored() -> None:
    post = QueryDict("edu-0-secret=1&edu-0-org_name=Сургууль")

    rows = answers_from_post(post)["education"]

    assert rows == [{name: ("Сургууль" if name == "org_name" else "") for name in EDUCATION_FIELDS}]


def test_reading_stops_one_past_the_cap() -> None:
    post = QueryDict("&".join(f"fam-{index}-given_name=Бат" for index in range(500)))

    assert len(answers_from_post(post)["family"]) == MAX_FAMILY + 1


def test_education_is_capped_the_same_way() -> None:
    post = QueryDict("&".join(f"edu-{index}-org_name=Сургууль" for index in range(50)))

    assert len(answers_from_post(post)["education"]) == MAX_EDUCATION + 1


def test_throttle_allows_up_to_the_limit_then_refuses() -> None:
    results = [throttle.allow("10.0.0.1", "apply-unknown", limit=3, window_seconds=60) for _ in range(4)]

    assert results == [True, True, True, False]


def test_throttle_counts_each_ip_and_bucket_apart() -> None:
    for _ in range(3):
        throttle.allow("10.0.0.1", "apply-unknown", limit=3, window_seconds=60)

    assert throttle.allow("10.0.0.2", "apply-unknown", limit=3, window_seconds=60)
    assert throttle.allow("10.0.0.1", "other", limit=3, window_seconds=60)


def test_throttle_treats_unknown_ip_as_one_caller() -> None:
    results = [throttle.allow(None, "apply-unknown", limit=2, window_seconds=60) for _ in range(3)]

    assert results == [True, True, False]
