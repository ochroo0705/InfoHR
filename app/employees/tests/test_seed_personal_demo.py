"""seed_personal_demo: one demo employee with a full personal tab (every section, several rows per list)."""

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from employees.models import Employee
from employees.services import personal_rows
from employees.services import personal_writes as pw


@override_settings(DEBUG=True)
def test_fills_every_section_and_list(hired: Employee) -> None:
    call_command("seed_personal_demo", hired.code)
    for kind in pw.KINDS:
        assert len(personal_rows.rows(kind, hired)) >= 2, kind
    hired.refresh_from_db()
    assert hired.private_phone and hired.phone2 and hired.clan_name
    assert hired.education_level_id and hired.academic_degree_id and hired.citizenship_id


def test_refuses_outside_debug(hired: Employee) -> None:
    with pytest.raises(CommandError):
        call_command("seed_personal_demo", hired.code)


@override_settings(DEBUG=True)
def test_unknown_code_is_a_clear_error(db: None) -> None:
    with pytest.raises(CommandError, match="E9999"):
        call_command("seed_personal_demo", "E9999")
