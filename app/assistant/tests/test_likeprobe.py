"""Tests for likeprobe: finding a LIKE that matches no row, with a fake host."""

from typing import Any

from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result

from assistant.likeprobe import Like, likes_in, missing_like

LEAVE = View(
    name="GOV_LEAVE",
    description="Leave",
    columns=(Column("EMP_ID", "id"), Column("LEAVE_TYPE_NAME", "type"), Column("DAYS", "days")),
)
EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees",
    columns=(Column("EMP_ID", "id"), Column("FIRST_NAME", "name"), Column("WORKING", "working")),
)
CATALOGUE = Catalogue(views=(LEAVE, EMPLOYEES))
SQL = (
    "SELECT E.EMP_ID FROM GOV_EMPLOYEES AS E WHERE NOT EXISTS (SELECT 1 FROM GOV_LEAVE AS L "
    "WHERE L.EMP_ID = E.EMP_ID AND UPPER(L.LEAVE_TYPE_NAME) LIKE UPPER('%аралт%'))"
)


class FakeHost:
    """Answers a probe (FIRST 1 ... LIKE) with `hit` rows and a DISTINCT query with the values."""

    def __init__(self, hit: bool, values: tuple[str, ...] = ("Ээлжийн амралт", "Өвчний чөлөө")) -> None:
        self.hit = hit
        self.values = values
        self.sql: list[str] = []

    def catalogue_for(self, user: object) -> Catalogue:
        return CATALOGUE

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.sql.append(query.sql)
        if "DISTINCT" in query.sql:
            return Result(columns=("V",), rows=tuple((v,) for v in self.values), truncated=False)
        return Result(columns=("X",), rows=((1,),) if self.hit else (), truncated=False)

    def cancel(self, user: object) -> None:
        pass


def test_likes_in_resolves_the_alias_to_its_view() -> None:
    assert likes_in(SQL) == [Like("GOV_LEAVE", "LEAVE_TYPE_NAME", "'%аралт%'")]


def test_likes_in_skips_a_pattern_that_is_not_a_literal() -> None:
    assert likes_in("SELECT EMP_ID FROM GOV_LEAVE WHERE LEAVE_TYPE_NAME LIKE LEAVE_TYPE_NAME") == []


def test_a_miss_names_the_column_and_lists_its_values() -> None:
    text = missing_like(FakeHost(hit=False), object(), SQL)

    assert "LEAVE_TYPE_NAME LIKE '%аралт%' matches no row of GOV_LEAVE" in text
    assert "«Ээлжийн амралт»" in text


def test_a_hit_gives_no_text() -> None:
    assert missing_like(FakeHost(hit=True), object(), SQL) == ""


def test_personal_values_are_never_listed() -> None:
    host = FakeHost(hit=False, values=("Bat",))
    sql = "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE FIRST_NAME LIKE '%xyz%'"

    text = missing_like(host, object(), sql)

    assert "matches no row" in text
    assert "Bat" not in text
    assert not any("DISTINCT" in s for s in host.sql)


def test_a_probe_that_is_refused_gives_no_text() -> None:
    host: Any = FakeHost(hit=False)
    host.catalogue_for = lambda user: Catalogue(views=(EMPLOYEES,))  # GOV_LEAVE not allowed: the probe is refused

    assert missing_like(host, object(), SQL) == ""
