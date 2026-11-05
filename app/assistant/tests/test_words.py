from collections.abc import Callable

import pytest
from accounts.models import User
from reports.column_filters import COLUMN_FILTERS, params_of
from reports.filters import EMPTYPES, GENDERS, STATES
from reports.staff_list import REPORT
from reports.table import offered_column_filters, offered_filters

from assistant.words import WORDS, offered_words

pytestmark = pytest.mark.django_db


def _expected_params(user: User) -> set[str]:
    params: set[str] = set()
    for name in offered_filters(REPORT, user):
        if name == "as_of":
            continue
        params.update({"age_from", "age_to"} if name == "age_range" else {name})
    for name in offered_column_filters(REPORT, user):
        params.update(params_of(COLUMN_FILTERS[name]))
    return params


def test_every_offered_filter_has_words(admin_user: User) -> None:
    assert _expected_params(admin_user) <= set(WORDS)
    assert {w.param for w in offered_words(admin_user)} == _expected_params(admin_user)


def test_fixed_values_match_the_filter_tables() -> None:
    assert {v.value for v in WORDS["emptype"].values} == {str(k) for k in EMPTYPES}
    assert {v.value for v in WORDS["state"].values} == set(STATES)
    assert {v.value for v in WORDS["gender"].values} == set(GENDERS)
    assert {v.value for v in WORDS["work_conditions"].values} == {
        str(k) for k, _ in COLUMN_FILTERS["work_conditions"].choices
    }


def test_value_labels_come_from_the_filter_tables() -> None:
    assert {v.value: v.label for v in WORDS["state"].values} == STATES
    assert {v.value: v.label for v in WORDS["gender"].values} == GENDERS
    assert {v.value: v.label for v in WORDS["emptype"].values} == {str(k): v for k, v in EMPTYPES.items()}
    assert {v.value: v.label for v in WORDS["work_conditions"].values} == {
        str(k): v for k, v in COLUMN_FILTERS["work_conditions"].choices
    }


def test_direction_words_belong_to_hire_dates_only() -> None:
    # «хойш» and «өмнө» name hire dates; a bare word must not point at two filters.
    assert "хойш" not in WORDS["contract_end_from"].synonyms
    assert "өмнө" not in WORDS["contract_end_to"].synonyms
    assert "хойш" in WORDS["hired_from"].synonyms
    assert "өмнө" in WORDS["hired_to"].synonyms


def test_emptype_rules() -> None:
    by_value = {v.value: v for v in WORDS["emptype"].values}
    contract = next(v for v in WORDS["emptype"].values if v.label == "Гэрээт ажилтан")
    assert contract.value == "5"
    assert "гэрээт" in contract.synonyms
    foreign = next(v for v in WORDS["emptype"].values if v.label == "Гадаад нөөц")
    assert foreign.value == "2"
    assert by_value["8"].confirmed is False
    assert by_value["9"].confirmed is False
    assert all(v.confirmed for v in WORDS["emptype"].values if v.value not in ("8", "9"))


def test_offered_words_respects_permission(role_user: Callable[[str], User]) -> None:
    # The auditor kind holds no employee permission. The accountant kind holds view_salary by default, so it is not
    # the right kind for a "no salary" check.
    params = {w.param for w in offered_words(role_user("auditor"))}
    assert not params & {"salary_from", "salary_to", "bank", "gender", "age_from", "age_to"}
    assert {"branch", "department", "position", "emptype", "state"} <= params


def test_offered_words_for_hr_has_personal_filters(role_user: Callable[[str], User]) -> None:
    params = {w.param for w in offered_words(role_user("hr"))}
    assert {"gender", "age_from", "age_to"} <= params
    assert not params & {"salary_from", "salary_to"}


def test_every_word_is_mongolian_or_english_text() -> None:
    for word in WORDS.values():
        assert word.label.strip()
        assert word.description.strip()
        assert all(s.strip() for s in word.synonyms)
        assert len(set(word.synonyms)) == len(word.synonyms), word.param
        for value in word.values:
            assert value.label.strip()
            assert all(s.strip() for s in value.synonyms)
            assert len(set(value.synonyms)) == len(value.synonyms), (word.param, value.value)
