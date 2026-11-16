"""Tests for known_values: the category values added to the catalogue text."""

import pytest
from django.core.cache import cache
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result

from assistant.knownvalues import MAX_VALUES, known_values

LEAVE = View(name="GOV_LEAVE", description="Leave", columns=(Column("EMP_ID", "id"), Column("LEAVE_TYPE_NAME", "t")))
CATALOGUE = Catalogue(views=(LEAVE,))


class FakeHost:
    def __init__(self, values: tuple[object, ...]) -> None:
        self.values = values
        self.sql: list[str] = []

    def catalogue_for(self, user: object) -> Catalogue:
        return CATALOGUE

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.sql.append(query.sql)
        return Result(columns=("V",), rows=tuple((v,) for v in self.values), truncated=False)

    def cancel(self, user: object) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear() -> None:
    cache.clear()


def test_lists_the_values_of_a_view_the_asker_has() -> None:
    text = known_values(FakeHost(("Ээлжийн амралт  ", "Өвчний чөлөө", None)), object(), CATALOGUE)

    assert "GOV_LEAVE.LEAVE_TYPE_NAME: 'Ээлжийн амралт'; 'Өвчний чөлөө'" in text
    assert "GOV_EMPLOYEES" not in text  # not in the asker's catalogue


def test_a_quote_in_a_value_is_doubled() -> None:
    assert "'O''Neil'" in known_values(FakeHost(("O'Neil",)), object(), CATALOGUE)


def test_too_many_values_are_left_out() -> None:
    values = tuple(f"v{i}" for i in range(MAX_VALUES + 5))

    assert known_values(FakeHost(values), object(), CATALOGUE) == ""


def test_no_views_gives_no_text() -> None:
    assert known_values(FakeHost(("x",)), object(), Catalogue(views=())) == ""


def test_asker_line_without_a_record_says_so() -> None:
    from django.contrib.auth.models import AnonymousUser

    from assistant.knownvalues import asker_line

    assert "no employee record" in asker_line(AnonymousUser())


@pytest.mark.django_db
def test_asker_line_gives_the_own_emp_id(role_user) -> None:
    from employees.access import own_employee

    from assistant.knownvalues import asker_line

    user = role_user("staff")
    employee = own_employee(user)

    assert asker_line(user).endswith(f"EMP_ID = {employee.pk}.")
