"""A6 «Хүүхдийн судалгаа»: the children of the staff, from the family table (sons and daughters), with their age on
the chosen day. Each child is listed once under the parent's row."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from accounts.models import User
from employees.services.order_register import age_on
from macs.models import FamilyRow

from reports import survey_common
from reports.filters import Filters
from reports.survey_common import NEEDS_PERSONAL, PERSON_COLUMNS, Person, on_person
from reports.types import Column, Report

CHILD_TYPES = ("son", "daughter")  # the FamilyRelation.fm_type values that count as a child


@dataclass(frozen=True)
class Child:
    person: Person  # the parent
    item: FamilyRow  # the family row of the child
    age: int | None  # full years on the parent's as-of day; None without a birth date


def _person(c: Child) -> Person:
    return c.person


def in_age_range(age: int | None, f: Filters) -> bool:
    """Without an age filter every child passes; with one, a child needs a birth date inside the range."""
    if f.age_from is None and f.age_to is None:
        return True
    return age is not None and (f.age_from is None or age >= f.age_from) and (f.age_to is None or age <= f.age_to)


def _rows(user: User, f: Filters) -> list[Child]:
    """The children of the people the filters pass, in the parents' name order, then by birth date."""
    persons = survey_common.people(user, f)
    by_pk = {p.row.employee.pk: p for p in persons}
    order = {pk: i for i, pk in enumerate(by_pk)}
    items = FamilyRow.objects.select_related("relation").filter(
        employee_id__in=list(by_pk), relation__fm_type__in=CHILD_TYPES
    )
    found: list[Child] = []
    for item in items:
        parent = by_pk[item.employee_id]
        age = age_on(item.birth_date, parent.as_of)
        if age is not None and age < 0:
            age = None  # born after the day the parent is counted on: no age yet
        if in_age_range(age, f):
            found.append(Child(person=parent, item=item, age=age))
    found.sort(key=lambda c: (order[c.person.row.employee.pk], c.item.birth_date or date.max))
    return found


def _relation(c: Child) -> str | None:
    relation: Any = c.item.relation
    name: str | None = relation.name
    return name


COLUMNS: tuple[Column, ...] = (
    *(on_person(c, _person) for c in PERSON_COLUMNS),
    Column(key="child", label="Хүүхдийн нэр", value=lambda c: c.item.given_name),
    Column(key="relation", label="Хамаарал", value=_relation),
    Column(key="birth_date", label="Төрсөн огноо", value=lambda c: c.item.birth_date),
    Column(key="age", label="Нас", value=lambda c: c.age, numeric=True),
)


def _note(f: Filters) -> str:
    """The grey line: which family members count as children."""
    return "Хүү, охин хамаарлаар бүртгэсэн гэр бүлийн гишүүдийг хүүхэд гэж үзнэ."


REPORT = Report(
    key="children",
    title="Хүүхдийн судалгаа",
    filters=("state", "as_of", "branch", "department", "age_range"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=NEEDS_PERSONAL,
    source=FamilyRow,
    group_options=("department", "relation"),
    note=_note,
)
