"""The selection helper: which people a bulk action may act on (selection.pick and selection.subset)."""

from dataclasses import replace
from typing import Any

import pytest
from accounts.models import AccessScope, User
from django.http import HttpRequest, QueryDict
from django.test import RequestFactory
from employees.models import Employee
from employees.services import macs_writes
from employees.tests.conftest import named
from macs.models import Nationality

from reports import selection
from reports.filters import Filters, parse_filters, to_query
from reports.selection import SelectionError, pick, subset
from reports.staff_list import REPORT
from reports.table import build_table

from .conftest import _make_user, legacy

pytestmark = pytest.mark.django_db

ALL = to_query(Filters(state="all"))  # every person, no other filter


def _person_of(row: Any) -> int:
    assert REPORT.person is not None
    return REPORT.person(row)


def _request(**data: Any) -> HttpRequest:
    return RequestFactory().post("/reports/selection/", data)


def _report_order(user: User, query: str = ALL) -> list[int]:
    """The people the staff list shows this user for this query, in report order."""
    table = build_table(REPORT, user, parse_filters(QueryDict(query)))
    return [_person_of(row) for row in table.rows]


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


@pytest.fixture
def scoped(people: dict[str, Employee]) -> User:
    """An HR user who may only see Санхүү: D (Маркетинг) is outside the scope."""
    user = _make_user("HR", "scoped-hr")
    AccessScope.objects.create(user=user, limited=True, department_ids=[people["A"].department_id])
    return user


def test_ticked_ids_are_kept_in_report_order(hr_user: User, people: dict[str, Employee]) -> None:
    order = _report_order(hr_user)
    posted = [str(people[k].pk) for k in ("D", "A", "B", "C", "A")]
    picked = pick(_request(query=ALL, ids=posted), hr_user, REPORT)
    assert list(picked.ids) == order
    assert picked.dropped == 0


def test_all_matching_returns_every_visible_person(hr_user: User, people: dict[str, Employee]) -> None:
    picked = pick(_request(query=ALL, all="1"), hr_user, REPORT)
    assert list(picked.ids) == _report_order(hr_user)
    assert set(picked.ids) == {e.pk for e in people.values()}


def test_forged_id_outside_scope_is_dropped_and_counted(scoped: User, people: dict[str, Employee]) -> None:
    picked = pick(_request(query=ALL, ids=[str(people["A"].pk), str(people["D"].pk)]), scoped, REPORT)
    assert picked.ids == (people["A"].pk,)
    assert picked.dropped == 1
    assert people["D"].pk not in picked.ids


def test_all_matching_for_scoped_user_leaves_out_people_outside_scope(
    scoped: User, people: dict[str, Employee]
) -> None:
    picked = pick(_request(query=ALL, all="1"), scoped, REPORT)
    assert set(picked.ids) == {people["A"].pk, people["B"].pk, people["C"].pk}


def test_id_hidden_by_column_filter_is_dropped(hr_user: User, people: dict[str, Employee]) -> None:
    mongol = people["A"].nationality_id
    query = f"state=all&nationality={mongol}"  # C has another nationality, so the filter hides C
    picked = pick(_request(query=query, ids=[str(people[k].pk) for k in "ABCD"]), hr_user, REPORT)
    assert people["C"].pk not in picked.ids
    assert set(picked.ids) == {people["A"].pk, people["B"].pk, people["D"].pk}
    assert picked.dropped == 1


def test_garbage_ids_are_ignored(hr_user: User, people: dict[str, Employee]) -> None:
    a = str(people["A"].pk)
    posted = ["abc", "-5", "", "1.5", "\u0663", a, a]  # the last is an Arabic-Indic digit: not a plain decimal
    picked = pick(_request(query=ALL, ids=posted), hr_user, REPORT)
    assert picked.ids == (people["A"].pk,)
    assert picked.dropped == 0


def test_empty_selection_raises(hr_user: User) -> None:
    with pytest.raises(SelectionError) as nothing:
        pick(_request(query=ALL), hr_user, REPORT)
    assert nothing.value.message
    with pytest.raises(SelectionError):
        pick(_request(query=ALL, ids=["abc", ""]), hr_user, REPORT)


def test_over_500_raises(hr_user: User, people: dict[str, Employee], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selection, "MAX_PEOPLE", 2)
    posted = [str(people[k].pk) for k in "ABD"]
    with pytest.raises(SelectionError):
        pick(_request(query=ALL, ids=posted), hr_user, REPORT)


def test_all_matching_over_cap_raises(
    hr_user: User, people: dict[str, Employee], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "MAX_PEOPLE", 2)
    with pytest.raises(SelectionError):
        pick(_request(query=ALL, all="1"), hr_user, REPORT)


def test_report_without_person_raises(hr_user: User, people: dict[str, Employee]) -> None:
    plain = replace(REPORT, person=None)
    with pytest.raises(SelectionError):
        pick(_request(query=ALL, ids=[str(people["A"].pk)]), hr_user, plain)


def test_layout_parameter_is_ignored(hr_user: User, people: dict[str, Employee]) -> None:
    picked = pick(_request(query="state=all&layout=calendar&lby=first_hire_date", all="1"), hr_user, REPORT)
    assert picked.table.spec.layout == "table"
    assert set(picked.ids) == {e.pk for e in people.values()}


def test_selection_on_grouped_query_uses_the_same_people(hr_user: User, people: dict[str, Employee]) -> None:
    grouped = f"{ALL}&group=department"
    picked = pick(_request(query=grouped, ids=[str(people["D"].pk), str(people["A"].pk)]), hr_user, REPORT)
    assert set(picked.ids) == {people["A"].pk, people["D"].pk}


def test_subset_keeps_only_chosen_people_and_drops_footer(hr_user: User, people: dict[str, Employee]) -> None:
    table = build_table(REPORT, hr_user, parse_filters(QueryDict(ALL)))
    table = replace(table, footer=[])  # a footer that a subset must not keep
    chosen = {people["A"].pk, people["C"].pk}
    part = subset(table, REPORT, chosen)
    assert [row[0].person for _, group in part.groups for row in group] == [
        p for p in _report_order(hr_user) if p in chosen
    ]
    assert part.count == 2
    assert part.rows and {_person_of(r) for r in part.rows} == chosen
    assert part.footer is None


def test_subset_of_grouped_table_keeps_group_order_and_drops_empty_groups(
    hr_user: User, people: dict[str, Employee]
) -> None:
    table = build_table(REPORT, hr_user, parse_filters(QueryDict(f"{ALL}&group=department")))
    assert len(table.groups) == 2
    part = subset(replace(table, footer=[]), REPORT, {people["D"].pk})
    assert len(part.groups) == 1
    label, group = part.groups[0]
    assert [row[0].person for row in group] == [people["D"].pk]
    assert part.count == 1
    assert part.footer is None


def test_five_thousand_digit_id_is_ignored(hr_user: User, people: dict[str, Employee]) -> None:
    posted = ["9" * 5000, str(people["A"].pk)]
    picked = pick(_request(query=ALL, ids=posted), hr_user, REPORT)
    assert picked.ids == (people["A"].pk,)
    assert picked.dropped == 0


def test_more_posted_ids_than_cap_raises_even_if_few_are_visible(
    scoped: User, people: dict[str, Employee], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "MAX_PEOPLE", 2)
    posted = [str(people["A"].pk), str(people["D"].pk), "98765", "98766"]  # only A is visible to this user
    with pytest.raises(SelectionError) as too_many:
        pick(_request(query=ALL, ids=posted), scoped, REPORT)
    assert "2" in too_many.value.message


def test_all_posted_ids_forged_says_how_many_were_not_allowed(scoped: User, people: dict[str, Employee]) -> None:
    with pytest.raises(SelectionError) as forged:
        pick(_request(query=ALL, ids=[str(people["D"].pk), "98765"]), scoped, REPORT)
    assert "2" in forged.value.message
    assert forged.value.message != selection.NOTHING_PICKED


def test_junk_query_does_not_raise(hr_user: User, people: dict[str, Employee]) -> None:
    junk = f"state=all&{'k' * 5000}=1&note={'v' * 4000}&department={'9' * 4000}"
    picked = pick(_request(query=junk, all="1"), hr_user, REPORT)
    assert set(picked.ids) == {e.pk for e in people.values()}
