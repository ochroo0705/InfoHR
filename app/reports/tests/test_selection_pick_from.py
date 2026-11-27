"""selection.pick_from: the same selection as selection.pick for the same data, from plain values."""

from dataclasses import replace
from typing import Any

import pytest
from accounts.models import User
from django.http import HttpRequest
from django.test import RequestFactory
from employees.models import Employee
from employees.services import macs_writes
from employees.tests.conftest import named
from macs.models import Nationality

from reports import selection
from reports.filters import Filters, to_query
from reports.selection import Picked, SelectionError, pick, pick_from
from reports.staff_list import REPORT

from .conftest import legacy

pytestmark = pytest.mark.django_db

ALL = to_query(Filters(state="all"))  # every person, no other filter


@pytest.fixture
def people(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """A, B and D have Монгол nationality, C has another one. A, B and C work in Санхүү, D in Маркетинг."""
    marketing = macs_writes.save_department("Маркетинг")
    mongol = named(Nationality, "Монгол")
    other = named(Nationality, "Бусад")
    return {
        "A": legacy(actor, job_values, nationality=mongol),
        "B": legacy(actor, job_values, nationality=mongol),
        "C": legacy(actor, job_values, nationality=other),
        "D": legacy(actor, job_values, nationality=mongol, department=marketing),
    }


def _post(query: str, ids: list[str], all_: bool) -> HttpRequest:
    """The POST the React-free Django view would get for these values."""
    data: dict[str, Any] = {"query": query, "ids": ids}
    if all_:
        data["all"] = "1"
    return RequestFactory().post("/reports/selection/", data)


def _outcome(call: Any) -> Any:
    """The Picked result, or the SelectionError message, so both paths compare on one value."""
    try:
        return call()
    except SelectionError as error:
        return ("error", error.message)


def _same_as_pick(user: User, report: Any, query: str, ids: list[str], all_: bool) -> tuple[Any, Any]:
    via_pick = _outcome(lambda: pick(_post(query, ids, all_), user, report))
    via_from = _outcome(lambda: pick_from(user, report, query, ids, all_))
    return via_pick, via_from


def test_ticked_ids_match_pick(hr_user: User, people: dict[str, Employee]) -> None:
    ids = [str(people[k].pk) for k in ("D", "A", "B", "C", "A")]
    via_pick, via_from = _same_as_pick(hr_user, REPORT, ALL, ids, False)
    assert isinstance(via_from, Picked)
    assert via_from.ids == via_pick.ids
    assert via_from.dropped == via_pick.dropped == 0


def test_all_matching_matches_pick(hr_user: User, people: dict[str, Employee]) -> None:
    via_pick, via_from = _same_as_pick(hr_user, REPORT, ALL, [], True)
    assert isinstance(via_from, Picked)
    assert via_from.ids == via_pick.ids
    assert set(via_from.ids) == {e.pk for e in people.values()}


def test_all_ignores_posted_ids_like_pick(hr_user: User, people: dict[str, Employee]) -> None:
    ids = [str(people["A"].pk)]
    via_pick, via_from = _same_as_pick(hr_user, REPORT, ALL, ids, True)
    assert isinstance(via_from, Picked)
    assert via_from.ids == via_pick.ids
    assert len(via_from.ids) == len(people)


@pytest.mark.parametrize("all_", [False, True])
def test_over_the_cap_matches_pick(
    hr_user: User, people: dict[str, Employee], monkeypatch: pytest.MonkeyPatch, all_: bool
) -> None:
    monkeypatch.setattr(selection, "MAX_PEOPLE", 2)
    ids = [str(people[k].pk) for k in "ABD"] + ["98765"]
    via_pick, via_from = _same_as_pick(hr_user, REPORT, ALL, ids, all_)
    assert via_from == via_pick
    assert via_from == ("error", selection.too_many())


def test_501_posted_ids_are_refused_like_pick(hr_user: User, people: dict[str, Employee]) -> None:
    ids = [str(1_000_000 + i) for i in range(selection.MAX_PEOPLE + 1)]  # none of them is a visible person
    via_pick, via_from = _same_as_pick(hr_user, REPORT, ALL, ids, False)
    assert via_from == via_pick
    assert via_from == ("error", selection.too_many())


def test_only_forged_ids_match_pick(hr_user: User, people: dict[str, Employee]) -> None:
    ids = ["98765", "98766"]
    via_pick, via_from = _same_as_pick(hr_user, REPORT, ALL, ids, False)
    assert via_from == via_pick
    assert via_from == ("error", selection.not_allowed(2))


def test_no_ids_matches_pick(hr_user: User, people: dict[str, Employee]) -> None:
    via_pick, via_from = _same_as_pick(hr_user, REPORT, ALL, [], False)
    assert via_from == via_pick
    assert via_from == ("error", selection.NOTHING_PICKED)


def test_text_ids_are_ignored_like_pick(hr_user: User, people: dict[str, Employee]) -> None:
    a = str(people["A"].pk)
    ids = ["abc", "-5", "", "1.5", "٣", a, a]
    via_pick, via_from = _same_as_pick(hr_user, REPORT, ALL, ids, False)
    assert isinstance(via_from, Picked)
    assert via_from.ids == via_pick.ids == (people["A"].pk,)
    assert via_from.dropped == via_pick.dropped == 0


def test_forged_and_hidden_ids_match_pick(hr_user: User, people: dict[str, Employee]) -> None:
    mongol = people["A"].nationality_id
    query = f"state=all&nationality={mongol}"  # C has another nationality, so the filter hides C
    ids = [str(people[k].pk) for k in "ABCD"]
    via_pick, via_from = _same_as_pick(hr_user, REPORT, query, ids, False)
    assert isinstance(via_from, Picked)
    assert via_from.ids == via_pick.ids
    assert via_from.dropped == via_pick.dropped == 1


def test_layout_keys_are_stripped_like_pick(hr_user: User, people: dict[str, Employee]) -> None:
    query = "state=all&layout=calendar&lby=first_hire_date"
    via_pick, via_from = _same_as_pick(hr_user, REPORT, query, [], True)
    assert isinstance(via_from, Picked)
    assert via_from.table.spec.layout == "table"
    assert via_from.ids == via_pick.ids


def test_report_without_person_matches_pick(hr_user: User, people: dict[str, Employee]) -> None:
    plain = replace(REPORT, person=None)
    via_pick, via_from = _same_as_pick(hr_user, plain, ALL, [str(people["A"].pk)], False)
    assert via_from == via_pick
    assert via_from == ("error", selection.NO_PERSON)


def test_junk_query_matches_pick(hr_user: User, people: dict[str, Employee]) -> None:
    junk = f"state=all&{'k' * 5000}=1&note={'v' * 4000}&department={'9' * 4000}"
    via_pick, via_from = _same_as_pick(hr_user, REPORT, junk, [], True)
    assert isinstance(via_from, Picked)
    assert via_from.ids == via_pick.ids
    assert set(via_from.ids) == {e.pk for e in people.values()}


def test_leading_question_mark_matches_pick(hr_user: User, people: dict[str, Employee]) -> None:
    via_pick, via_from = _same_as_pick(hr_user, REPORT, f"?{ALL}", [], True)
    assert isinstance(via_from, Picked)
    assert via_from.ids == via_pick.ids
    assert set(via_from.ids) == {e.pk for e in people.values()}
