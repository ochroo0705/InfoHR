"""THROWAWAY SPIKE for the report-builder idea. Not production code; delete or rewrite.

One report over the same data (staff, their children, their leave). The «mode» filter flips it:
summary: one row per employee, children and leave as single cells;
children: one row per child, the employee columns repeated on each row.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.db.models import Q
from employees.services.order_register import age_on
from macs.models import Employee, FamilyRow, LeaveAssign

from reports import survey_common
from reports.children import CHILD_TYPES
from reports.filters import Filters
from reports.survey_common import NEEDS_PERSONAL, PERSON_COLUMNS, Person, on_person
from reports.types import Column, Report

GROUP = "Холбоотой мэдээлэл"


def _children_of(persons: list[Person]) -> list[tuple[Person, FamilyRow, int | None]]:
    """One query for all children of these people, in the parents' order, then by birth date. Age on the parent's day."""
    by_pk = {p.row.employee.pk: p for p in persons}
    order = {pk: i for i, pk in enumerate(by_pk)}
    items = FamilyRow.objects.select_related("relation").filter(
        employee_id__in=list(by_pk), relation__fm_type__in=CHILD_TYPES
    )
    found: list[tuple[Person, FamilyRow, int | None]] = []
    for item in items:
        parent = by_pk[item.employee_id]
        age = age_on(item.birth_date, parent.as_of)
        if age is not None and age < 0:
            age = None  # born after the day the parent is counted on: no age yet
        found.append((parent, item, age))
    found.sort(key=lambda t: (order[t[0].row.employee.pk], t[1].birth_date or date.max))
    return found


def _leave_days(persons: list[Person]) -> dict[int, int]:
    """Per employee pk: leave days of the rows that start in the person's as-of year. One query.
    A row with a day count uses it; otherwise its dates are counted, both ends included (an end before the start
    counts as one day). Cancelled and rejected rows do not count."""
    by_pk = {p.row.employee.pk: p for p in persons}
    days: dict[int, int] = dict.fromkeys(by_pk, 0)
    if not by_pk:
        return days
    years = [p.as_of.year for p in persons]
    rows = LeaveAssign.objects.filter(
        employee_id__in=list(by_pk),
        date1__gte=date(min(years), 1, 1),
        date1__lte=date(max(years), 12, 31),
    ).filter(Q(status__isnull=True) | Q(status=LeaveAssign.APPROVED))
    for a in rows:
        if a.date1.year != by_pk[a.employee_id].as_of.year:
            continue  # starts in another year than the one counted
        if a.adays is not None:
            count = a.adays
        else:
            count = 1 if a.date2 < a.date1 else (a.date2 - a.date1).days + 1
        days[a.employee_id] += count
    return days


@dataclass(frozen=True)
class BuilderRow:
    person: Person
    children: list[tuple[str, int | None]]  # every child of the person: (given name, age or None)
    child: FamilyRow | None  # this row's child; None in summary mode
    child_age: int | None  # this row's child's full years; None in summary mode or with no age
    leave_days: int


def _rows(user: User, f: Filters) -> list[BuilderRow]:
    persons = survey_common.people(user, f)
    days = _leave_days(persons)
    found = _children_of(persons)
    kids: dict[int, list[tuple[str, int | None]]] = {p.row.employee.pk: [] for p in persons}
    for parent, item, age in found:
        kids[parent.row.employee.pk].append((item.given_name, age))
    if f.mode == "children":
        return [
            BuilderRow(
                person=parent,
                children=kids[parent.row.employee.pk],
                child=item,
                child_age=age,
                leave_days=days[parent.row.employee.pk],
            )
            for parent, item, age in found
        ]
    return [
        BuilderRow(
            person=p,
            children=kids[p.row.employee.pk],
            child=None,
            child_age=None,
            leave_days=days[p.row.employee.pk],
        )
        for p in persons
    ]


def _name_age(given: str, age: int | None) -> str:
    return given if age is None else f"{given} ({age})"


def _youngest(r: BuilderRow) -> int | None:
    ages = [age for _, age in r.children if age is not None]
    return min(ages) if ages else None


def _names(r: BuilderRow) -> str:
    return "; ".join(_name_age(given, age) for given, age in r.children)


def _child_name(r: BuilderRow) -> str | None:
    return r.child.given_name if r.child is not None else None


def _relation(r: BuilderRow) -> str | None:
    return r.child.relation.name if r.child is not None else None


def _birth_date(r: BuilderRow) -> date | None:
    return r.child.birth_date if r.child is not None else None


COLUMNS: tuple[Column, ...] = (
    *(on_person(c, lambda r: r.person) for c in PERSON_COLUMNS),
    Column(
        key="children_count",
        label="Хүүхдийн тоо",
        value=lambda r: len(r.children),
        kind="number",
        numeric=True,
        group=GROUP,
    ),
    Column(
        key="youngest_child_age",
        label="Бага хүүхдийн нас",
        value=_youngest,
        kind="number",
        numeric=True,
        group=GROUP,
    ),
    Column(key="children_names", label="Хүүхдүүд", value=_names, kind="text", group=GROUP),
    Column(
        key="leave_days",
        label="Амарсан хоног (энэ жил, ээлжийн амралт)",
        value=lambda r: r.leave_days,
        kind="number",
        numeric=True,
        group=GROUP,
    ),
    # the child columns are blank in summary mode
    Column(key="child", label="Хүүхдийн нэр", value=_child_name, kind="text", group=GROUP),
    Column(key="relation", label="Хамаарал", value=_relation, kind="text", group=GROUP),
    Column(key="birth_date", label="Төрсөн огноо", value=_birth_date, kind="date", group=GROUP),
    Column(key="age", label="Нас", value=lambda r: r.child_age, kind="number", numeric=True, group=GROUP),
)

PERSON_KEYS = tuple(c.key for c in PERSON_COLUMNS)
SUMMARY_KEYS = (*PERSON_KEYS, "children_count", "youngest_child_age", "children_names", "leave_days")
CHILDREN_KEYS = (*PERSON_KEYS, "child", "relation", "birth_date", "age", "leave_days")


def _default_columns(f: Filters) -> tuple[str, ...]:
    return CHILDREN_KEYS if f.mode == "children" else SUMMARY_KEYS


def _note(f: Filters) -> str:
    return (
        "Нэгтгэсэн горим: нэг мөрөнд нэг ажилтан, хүүхдүүд нэг нүдэнд нэгтгэгдэнэ. "
        "Хүүхэд бүрээр горим: нэг мөрөнд нэг хүүхэд, ажилтны мэдээлэл мөр бүрт давтагдана."
    )


REPORT = Report(
    key="spike-builder",
    title="Ажилтан + хүүхэд, амралт (горимтой)",
    filters=("state", "as_of", "branch", "department", "mode"),
    columns=COLUMNS,
    default_columns=SUMMARY_KEYS,
    default_columns_for=_default_columns,
    rows=_rows,
    needs=NEEDS_PERSONAL,
    source=Employee,
    picks_columns=True,
    note=_note,
)
