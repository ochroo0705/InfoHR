"""macs.triggers on PostgreSQL: every check is a no-op and never touches the database (plan 3, Task 4).

The settings fixture sets DB_ENGINE per test, so these tests do not depend on the environment they run in.
No django_db mark is used: any database access would fail here.
"""

import pytest
from pytest_django.fixtures import SettingsWrapper

from macs import triggers
from macs.triggers import EXPECTED, MacsTriggerMissing, database_has_triggers, missing, require


@pytest.fixture
def postgres(settings: SettingsWrapper) -> SettingsWrapper:
    settings.DB_ENGINE = "postgres"
    return settings


def test_database_has_triggers_only_on_firebird(postgres: SettingsWrapper) -> None:
    assert database_has_triggers() is False
    postgres.DB_ENGINE = "firebird"
    assert database_has_triggers() is True


def test_missing_is_empty_on_postgres(postgres: SettingsWrapper) -> None:
    assert missing(*sorted(EXPECTED)) == []
    assert missing("MOVEMENT") == []


def test_require_is_a_no_op_on_postgres(postgres: SettingsWrapper) -> None:
    require(*sorted(EXPECTED))
    require()
    assert triggers._verified == set()  # nothing cached on PostgreSQL


def test_expected_table_map_has_the_agreed_triggers() -> None:
    assert EXPECTED["EMPLOYEE"] == {"TR_EMPLOYEEID", "EMPLOYEE_BU0", "TR_EMPCUST"}
    assert EXPECTED["MOVEMENT"] == {"MOVEMENT_AI0"}
    assert EXPECTED["EMPLOYEE_HISTORY"] == {"EMPLOYEE_HISTORY_BD0"}
    assert EXPECTED["CONTACTING"] == {"CONTACTING_AI0", "CONTACTING_AU0"}
    assert EXPECTED["ADDRESS"] == {"ADDRESS_BI"}
    assert EXPECTED["CUSTOMER"] == {"TR_CUSTID", "TR_UPDCUSTOMER"}


def test_missing_rejects_a_table_without_a_known_trigger_list(postgres: SettingsWrapper) -> None:
    with pytest.raises(ValueError, match="NOSUCHTABLE"):
        missing("NOSUCHTABLE")


def test_macs_trigger_missing_is_an_exception() -> None:
    assert issubclass(MacsTriggerMissing, Exception)


def test_e011_is_silent_on_postgres(postgres: SettingsWrapper) -> None:
    from infohr_firebird.checks import check_macs_triggers

    assert check_macs_triggers(None, databases=["default"]) == []
    assert check_macs_triggers(None, databases=None) == []
