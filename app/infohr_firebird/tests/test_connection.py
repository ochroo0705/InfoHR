import pytest
from django.db import connections


def test_connects_in_dialect_1(fb_alias: str) -> None:
    cursor = connections[fb_alias].cursor()
    cursor.execute("select mon$sql_dialect from mon$database")
    assert cursor.fetchone()[0] == 1
    assert connections[fb_alias].connection.sql_dialect == 1


def test_reads_existing_table(fb_alias: str) -> None:
    cursor = connections[fb_alias].cursor()
    cursor.execute("select count(*) from employee")
    assert cursor.fetchone()[0] == 49


def test_host_less_database_string(fb_alias: str) -> None:
    wrapper = connections[fb_alias]
    assert wrapper.settings_dict["HOST"] == ""
    assert wrapper.get_connection_params()["database"] == wrapper.settings_dict["NAME"]


def test_host_and_port_string(fb_alias: str, monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = connections[fb_alias]
    monkeypatch.setitem(wrapper.settings_dict, "HOST", "db1")
    monkeypatch.setitem(wrapper.settings_dict, "PORT", "3051")
    assert wrapper.get_connection_params()["database"] == f"db1/3051:{wrapper.settings_dict['NAME']}"
