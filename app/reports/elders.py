"""A5 «Өндөр настнуудын судалгаа»: the staff who have reached the elder age on the chosen day, with their emergency
contacts and home address. The age is counted as in A4. The pension flag is not read (OQ-055)."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from accounts.models import User
from employees.models import Employee
from employees.services.order_register import age_on
from macs.models import AddressRow, ContactRow

from reports import staff_list, survey_common
from reports.filters import Filters
from reports.survey_common import NEEDS_PERSONAL, PERSON_COLUMNS, Person, on_person
from reports.types import Column, Report

ELDER_AGE = 60


@dataclass(frozen=True)
class Elder:
    person: Person
    contacts: str  # the emergency contacts, one text per row, joined with "; "
    address: str  # the first home address; "" when none


def _person(e: Elder) -> Person:
    return e.person


def _contact_text(c: ContactRow) -> str:
    """One emergency contact as «<type>: <value> (<name>, <relative>)». Empty parts are left out."""
    kind: Any = c.contact_type
    head = ": ".join(part for part in (kind.name, c.value) if part)
    who = ", ".join(part for part in (c.name, c.relative) if part)
    return " ".join(part for part in (head, f"({who})" if who else "") if part)


def _rows(user: User, f: Filters) -> list[Elder]:
    """The people at least `age_from` (default ELDER_AGE) and at most `age_to` years old, oldest first."""
    youngest = f.age_from if f.age_from is not None else ELDER_AGE
    people = [
        p
        for p in survey_common.people(user, f)
        if p.age is not None and p.age >= youngest and (f.age_to is None or p.age <= f.age_to)
    ]
    people.sort(key=lambda p: -(p.age or 0))  # stable: the name order stays among equal ages
    ids = [p.row.employee.pk for p in people]
    contacts: dict[int, list[str]] = defaultdict(list)
    for c in ContactRow.objects.select_related("contact_type").filter(employee_id__in=ids).order_by("id"):
        contacts[c.employee_id].append(_contact_text(c))
    addresses = staff_list.first_per_employee(
        AddressRow.objects.select_related("city", "district").filter(employee_id__in=ids)
    )
    return [
        Elder(
            person=p,
            contacts="; ".join(contacts.get(p.row.employee.pk, [])),
            address=staff_list.address_text(addresses[p.row.employee.pk]) if p.row.employee.pk in addresses else "",
        )
        for p in people
    ]


def _years_worked(e: Elder) -> int | None:
    return age_on(e.person.row.employee.first_hire_date, e.person.as_of)


COLUMNS: tuple[Column, ...] = (
    *(on_person(c, _person) for c in PERSON_COLUMNS),
    Column(key="birth_date", label="Төрсөн огноо", value=lambda e: e.person.row.employee.birth_date),
    Column(key="age", label="Нас", value=lambda e: e.person.age, numeric=True),
    Column(key="years_worked", label="Ажилласан жил", value=_years_worked, numeric=True),
    Column(key="private_phone", label="Хувийн утас", value=lambda e: e.person.row.employee.private_phone),
    Column(key="contacts", label="Яаралтай үед холбогдох", value=lambda e: e.contacts),
    Column(key="address", label="Гэрийн хаяг", value=lambda e: e.address),
)


def _note(f: Filters) -> str:
    """The grey line: the age limit and that the pension status is not used; with only an upper age, that the
    floor stays at ELDER_AGE."""
    text = (
        f"Тэтгэврийн насны тохиргоо: хамгийн багадаа {ELDER_AGE} нас "
        "(нас хүрсэн ажилтныг харуулна, тэтгэврийн төлөвөөр биш)."
    )
    if f.age_to is not None and f.age_from is None:
        text += " Дээд насыг тохируулсан бол доод нас 60 хэвээр."
    return text


REPORT = Report(
    key="elders",
    title="Өндөр настнуудын судалгаа",
    filters=("state", "as_of", "branch", "department", "age_range"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=NEEDS_PERSONAL,
    source=Employee,
    group_options=("department",),
    note=_note,
)
