"""macs.dialect on PostgreSQL (plan 3, Task 9). The Firebird side is in infohr_firebird/tests/test_write_dialect.py."""

import pytest
from django.db.models import Q
from pytest_django.fixtures import SettingsWrapper

from macs import dialect


@pytest.fixture
def postgres(settings: SettingsWrapper) -> SettingsWrapper:
    settings.DB_ENGINE = "postgres"
    return settings


@pytest.fixture
def firebird(settings: SettingsWrapper) -> SettingsWrapper:
    settings.DB_ENGINE = "firebird"
    return settings


def test_lock_suffix_postgres(postgres: SettingsWrapper) -> None:
    assert dialect.lock_suffix() == " FOR UPDATE"


def test_lock_suffix_firebird(firebird: SettingsWrapper) -> None:
    assert dialect.lock_suffix() == " WITH LOCK"


def test_physical_order_is_ctid(postgres: SettingsWrapper) -> None:
    assert dialect.physical_order() == "ctid"


def test_physical_order_is_db_key_on_firebird(firebird: SettingsWrapper) -> None:
    assert dialect.physical_order() == "RDB$DB_KEY"


def test_next_value_refuses_a_name_outside_the_allow_list() -> None:
    # No database access: the name is refused before any cursor is opened.
    with pytest.raises(ValueError, match="unknown generator"):
        dialect.next_value("pg_sleep(1); --")


def test_firebird_generator_names_are_uppercase_and_mapped() -> None:
    assert dialect.GENERATORS == {"gen_employee_history_id": "GEN_EMPLOYEE_HISTORY_ID"}


@pytest.mark.pg_only(
    "PostgreSQL's nextval(); the Firebird generator is checked in infohr_firebird/tests/test_write_dialect.py"
)
@pytest.mark.django_db
def test_next_value_postgres_advances_by_one(postgres: SettingsWrapper) -> None:
    first = dialect.next_value("gen_employee_history_id")
    second = dialect.next_value("gen_employee_history_id")
    assert isinstance(first, int)
    assert second == first + 1


LONG_WORD = "ж" * 5000  # longer than dialect.MAX_SEARCH_CHARS: no column can hold it


def test_search_match_normal_word_is_a_contains_lookup(postgres: SettingsWrapper) -> None:
    assert dialect.search_match("abc", "f_name", icase=True) == Q(f_name__icontains="abc")
    assert dialect.search_match("abc", "f_name") == Q(f_name__contains="abc")


def test_search_prefix_normal_word_is_a_startswith_lookup(postgres: SettingsWrapper) -> None:
    assert dialect.search_prefix("abc", "f_name") == Q(f_name__startswith="abc")


def test_search_match_long_word_matches_nothing(postgres: SettingsWrapper) -> None:
    assert dialect.search_match(LONG_WORD, "f_name", icase=True) == Q(pk__in=[])


def test_search_prefix_long_word_matches_nothing(postgres: SettingsWrapper) -> None:
    assert dialect.search_prefix(LONG_WORD, "f_name") == Q(pk__in=[])


@pytest.mark.pg_only("PostgreSQL run of a 5000-character word; the Firebird run is in infohr_firebird/tests")
@pytest.mark.django_db
def test_long_word_search_runs_and_finds_nothing_postgres(postgres: SettingsWrapper) -> None:
    from macs.models import Position

    assert not Position.objects.filter(dialect.search_match(LONG_WORD, "name", icase=True)).exists()
