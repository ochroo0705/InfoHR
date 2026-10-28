"""F2 «Хүүхдэд бэлэг олгосон жагсаалт» and F3 «Хүүхдэд бэлэг олгох»: the yearly gifts for the staff's children.

F2 lists the gift rows of a year (old frmGivenPresent). F3 lists the children that have no gift row yet for their age
and year (old frmChildPresent, query qryCheck). Both come from the production `given_present` and `family` tables. F2
pairs each row with its person's listing row (personal_lists.with_rows); F3 uses the staff list's people
(survey_common.people), so both reports count the same people.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.utils import timezone
from employees.services.order_register import age_on
from macs.models import FamilyRow, PresentRow

from reports import personal_lists, survey_common
from reports.children import CHILD_TYPES, in_age_range
from reports.filters import Filters
from reports.personal_lists import ListRow, full_name, people, with_rows
from reports.survey_common import Person, on_person
from reports.types import Column, Report

CONTRACT = "yes"  # Employee.contract_flag value of contract staff


def _given_rows(user: User, f: Filters) -> list[ListRow]:
    """F2: the gifts given in the year, of the people the user may see, sorted by name then child age."""
    year = f.year or timezone.localdate().year
    items = PresentRow.objects.select_related("present_type").filter(employee__in=people(user), given_year=year)
    if f.present_type is not None:
        items = items.filter(present_type_id=f.present_type)
    found = with_rows(list(items), timezone.localdate())
    return sorted(found, key=lambda r: (full_name(r), r.item.child_age))


def _present_name(r: ListRow) -> str | None:
    return r.item.present_type.name if r.item.present_type_id is not None else None


def _total(r: ListRow) -> int:
    """The gift's total: the price for each child."""
    total: int = r.item.price * r.item.childqty
    return total


GIVEN_COLUMNS: tuple[Column, ...] = (
    Column(key="year", label="Он", value=lambda r: r.item.given_year),
    *personal_lists.PERSON_COLUMNS,
    Column(key="present", label="Баярын нэр", value=_present_name),
    Column(key="child_age", label="Нас", value=lambda r: r.item.child_age, numeric=True),
    Column(key="childqty", label="Хүүхдийн тоо", value=lambda r: r.item.childqty, numeric=True),
    Column(key="price", label="Бэлгийн үнэ", value=lambda r: r.item.price, numeric=True, money=True),
    Column(key="total", label="Нийт үнэ", value=_total, numeric=True, money=True),
    Column(key="given", label="Өгсөн", value=lambda r: "Тийм" if r.item.given else "Үгүй"),
    Column(key="date", label="Огноо", value=lambda r: r.item.pdate),
)


GIVEN = Report(
    key="gifts-given",
    title="Хүүхдэд бэлэг олгосон жагсаалт",
    filters=("year", "present_type"),
    columns=GIVEN_COLUMNS,
    default_columns=tuple(c.key for c in GIVEN_COLUMNS),
    rows=_given_rows,
    needs=personal_lists.NEEDS,
    source=PresentRow,
    group_options=("present", "department"),
)


@dataclass(frozen=True)
class Due:
    """One line of F3: a parent and the children of one age who have no gift row for the year."""

    person: Person  # the parent
    age: int  # the children's age on the year's counting day
    children: int  # how many children of that age


def _person(d: Due) -> Person:
    return d.person


def _due_rows(user: User, f: Filters) -> list[Due]:
    """F3: the children of the working, non-contract staff with a birth date, by age, that have no gift row for
    their age in the year (of the filtered gift type, when one is set). Sorted by parent name, then age."""
    today = timezone.localdate()
    year = f.year or today.year
    day = today if year == today.year else date(year, 12, 31)  # this year counts to today, a past year to 31 December
    persons = [p for p in survey_common.people(user, Filters()) if p.row.employee.contract_flag != CONTRACT]
    by_pk = {p.row.employee.pk: p for p in persons}
    order = {pk: i for i, pk in enumerate(by_pk)}

    counts: dict[tuple[int, int], int] = {}
    children = FamilyRow.objects.select_related("relation").filter(
        employee_id__in=list(by_pk), relation__fm_type__in=CHILD_TYPES
    )
    for child in children:
        if child.birth_date is None:
            continue  # no birth date, no age to match a gift against
        age = age_on(child.birth_date, day)
        if age is None or age < 0 or not in_age_range(age, f):
            continue  # born after the counting day: no age yet
        key = (child.employee_id, age)
        counts[key] = counts.get(key, 0) + 1

    given = PresentRow.objects.filter(employee_id__in=list(by_pk), given_year=year)
    if f.present_type is not None:
        given = given.filter(present_type_id=f.present_type)
    given_keys = {(g.employee_id, g.child_age) for g in given}

    lines = [
        Due(person=by_pk[pk], age=age, children=n) for (pk, age), n in counts.items() if (pk, age) not in given_keys
    ]
    return sorted(lines, key=lambda d: (order[d.person.row.employee.pk], d.age))


DUE_COLUMNS: tuple[Column, ...] = (
    *(on_person(c, _person) for c in survey_common.PERSON_COLUMNS),
    Column(key="age", label="Хүүхдийн нас", value=lambda d: d.age, numeric=True),
    Column(key="children", label="Хүүхдийн тоо", value=lambda d: d.children, numeric=True),
)


def _due_note(f: Filters) -> str:
    """The grey line: which children are listed and who is left out."""
    return (
        "Хүү, охин хамаарлаар бүртгэсэн, энэ жил бэлэг олгоогүй хүүхдүүд. Гэрээт ажилтан орохгүй. "
        "Бусад жилийн хувьд насыг тухайн жилийн 12 дугаар сарын 31-ний байдлаар тооцно."
    )


DUE = Report(
    key="gifts-due",
    title="Хүүхдэд бэлэг олгох",
    filters=("year", "age_range", "present_type"),
    columns=DUE_COLUMNS,
    default_columns=tuple(c.key for c in DUE_COLUMNS),
    rows=_due_rows,
    needs=personal_lists.NEEDS,
    source=FamilyRow,
    group_options=("department",),
    note=_due_note,
)
