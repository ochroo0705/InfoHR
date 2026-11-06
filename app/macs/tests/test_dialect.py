"""macs.dialect on PostgreSQL (plan 3, Task 9). The Firebird side is in infohr_firebird/tests/test_write_dialect.py."""

import pytest
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


def test_next_value_refuses_a_name_outside_the_allow_list() -> None:
    # No database access: the name is refused before any cursor is opened.
    with pytest.raises(ValueError, match="unknown generator"):
        dialect.next_value("pg_sleep(1); --")


def test_firebird_generator_names_are_uppercase_and_mapped() -> None:
    assert dialect.GENERATORS == {"gen_employee_history_id": "GEN_EMPLOYEE_HISTORY_ID"}


@pytest.mark.django_db
def test_next_value_postgres_advances_by_one(postgres: SettingsWrapper) -> None:
    first = dialect.next_value("gen_employee_history_id")
    second = dialect.next_value("gen_employee_history_id")
    assert isinstance(first, int)
    assert second == first + 1
