"""The SQL answer on real Firebird (Task 12c): the setting on, the real HrHost, the real roles. Firebird only.

The governed fixtures (installed views, the world of logins and employees) come from hr_sql/tests/conftest.py and
are imported here, not copied. The provider is a fake that returns one fixed SQL per call.
"""

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.db import connections
from employees.access import visible_employees
from employees.models import CompanySettings
from hr_sql.tests.conftest import World, governed_objects, world
from macs.models import FamilyRelation, FamilyRow
from pytest_django.plugin import DjangoDbBlocker
from sqlcore.explain import Warning

from assistant.providers import ProviderError
from assistant.sqlanswer import SqlAnswer, sql_answer

# The fixtures above are used by name as test parameters, which pytest wires; ruff cannot see that.
# ruff: noqa: F401, F811

TODAY = date(2026, 11, 11)
QUESTION = "Ажилчдын хүүхдийн тоо?"
CHILDREN_COUNT = (
    "SELECT e.FIRST_NAME, COUNT(*) AS CHILDREN FROM GOV_EMPLOYEES e "
    "JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID GROUP BY e.FIRST_NAME"
)
SALARY_SQL = "SELECT EMP_ID, BASE_SALARY FROM GOV_SALARY"


class FixedProvider:
    """Returns the same SQL on every call and counts the calls."""

    name = "fake"
    model = "fake-model"

    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.calls = 0

    def complete_json(self, system: str, user: str, schema: Any = None) -> Any:
        self.calls += 1
        return {"sql": self.sql}


@pytest.fixture
def governed_on(governed_objects: None, django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    """Installs the governed views, then switches the governed SQL setting on for the test and puts the old value back
    afterwards."""
    if connections["default"].vendor != "firebird":
        pytest.skip("the governed views are Firebird objects")
    with django_db_blocker.unblock():
        settings_row = CompanySettings.get()
        before = settings_row.governed_sql_enabled
        settings_row.governed_sql_enabled = True
        settings_row.save(update_fields=["governed_sql_enabled"])
        try:
            yield
        finally:
            settings_row.governed_sql_enabled = before
            settings_row.save(update_fields=["governed_sql_enabled"])


def _ask(django_db_blocker: DjangoDbBlocker, user: User, provider: FixedProvider) -> SqlAnswer:
    # The setting is read on the default connection, so the blocker is lifted for the call.
    with django_db_blocker.unblock():
        return sql_answer(user, QUESTION, TODAY, provider)  # type: ignore[arg-type]


def _son_relation() -> tuple[int, bool]:
    """A relation with fm_type 'son' (reused when the database has one). Returns (pk, made here)."""
    found = FamilyRelation.objects.filter(fm_type="son").first()
    if found is not None:
        return int(found.pk), False
    made = FamilyRelation.objects.create(name="Хүү", fm_type="son")
    return int(made.pk), True


def test_children_question_as_hr_counts_rows_and_warns_about_the_join(
    governed_on: None, world: World, django_db_blocker: DjangoDbBlocker
) -> None:
    made_rows: list[int] = []
    created_relation = False
    with django_db_blocker.unblock():
        relation, created_relation = _son_relation()
        for given in ("Child one", "Child two"):
            made_rows.append(
                int(FamilyRow.objects.create(employee=world.emp_a, relation_id=relation, given_name=given).pk)
            )
    try:
        provider = FixedProvider(CHILDREN_COUNT)

        answer = _ask(django_db_blocker, world.hr, provider)

        assert answer.status == "ok", answer.reason
        assert provider.calls == 1
        assert answer.explanation is not None
        assert Warning.JOIN_COUNTS_ROWS in answer.explanation.warnings
        assert answer.columns == ("FIRST_NAME", "CHILDREN")
        counted = sum(int(str(row[1])) for row in answer.rows)
        with django_db_blocker.unblock():
            expected = FamilyRow.objects.filter(
                employee__in=visible_employees(world.hr), relation__fm_type__in=("son", "daughter")
            ).count()
        assert counted == expected
        assert expected >= 2
    finally:
        with django_db_blocker.unblock():
            FamilyRow.objects.filter(pk__in=made_rows).delete()
            if created_relation:
                FamilyRelation.objects.filter(fm_type="son").delete()


def test_accountant_gets_salary_and_hr_is_refused_it(
    governed_on: None, world: World, django_db_blocker: DjangoDbBlocker
) -> None:
    accountant_provider = FixedProvider(SALARY_SQL)

    accountant_answer = _ask(django_db_blocker, world.accountant, accountant_provider)

    assert accountant_answer.status == "ok", accountant_answer.reason
    assert accountant_answer.salary is True

    hr_provider = FixedProvider(SALARY_SQL)

    hr_answer = _ask(django_db_blocker, world.hr, hr_provider)

    assert hr_answer.status == "refused"
    assert hr_answer.reason == "Table GOV_SALARY is not a governed view you may use."
    assert hr_provider.calls == 2  # one retry, then refused; never more
    assert hr_answer.rows == ()


def test_provider_failure_stays_a_refusal_on_firebird(
    governed_on: None, world: World, django_db_blocker: DjangoDbBlocker
) -> None:
    class BrokenProvider(FixedProvider):
        def complete_json(self, system: str, user: str, schema: Any = None) -> Any:
            self.calls += 1
            raise ProviderError("internal detail")

    provider = BrokenProvider(CHILDREN_COUNT)

    answer = _ask(django_db_blocker, world.hr, provider)

    assert answer.status == "refused"
    assert "ProviderError" in answer.reason
    assert "internal detail" not in answer.reason
    assert provider.calls == 1
