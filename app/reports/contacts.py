"""A8 «Ажилчидтай холбоо барих»: the emergency contacts of the staff (the old `contacting` table), one row per contact,
under the person's row. The old table keeps no date, so the period does not apply (OQ-056)."""

from dataclasses import dataclass
from typing import Any

from accounts.models import User
from macs.models import ContactRow

from reports import survey_common
from reports.filters import Filters
from reports.survey_common import NEEDS_PERSONAL, PERSON_COLUMNS, Person, on_person
from reports.types import Column, Report


@dataclass(frozen=True)
class Contact:
    person: Person
    item: ContactRow


def _person(c: Contact) -> Person:
    return c.person


def _rows(user: User, f: Filters) -> list[Contact]:
    """The contacts of the people the filters pass, in the people's name order, then by row id."""
    persons = survey_common.people(user, f)
    by_pk = {p.row.employee.pk: p for p in persons}
    order = {pk: i for i, pk in enumerate(by_pk)}
    items = ContactRow.objects.select_related("contact_type").filter(employee_id__in=list(by_pk))
    if f.contact_type is not None:
        items = items.filter(contact_type_id=f.contact_type)
    found = [Contact(person=by_pk[c.employee_id], item=c) for c in items]
    found.sort(key=lambda c: (order[c.person.row.employee.pk], c.item.pk))
    return found


def _type(c: Contact) -> str | None:
    kind: Any = c.item.contact_type
    name: str | None = kind.name
    return name


COLUMNS: tuple[Column, ...] = (
    *(on_person(c, _person) for c in PERSON_COLUMNS),
    Column(key="type", label="Төрөл", value=_type),
    Column(key="value", label="Утас, имэйл", value=lambda c: c.item.value),
    Column(key="contact_name", label="Холбогдох хүн", value=lambda c: c.item.name),
    Column(key="relative", label="Хамаарал", value=lambda c: c.item.relative),
)


def _note(f: Filters) -> str:
    """The grey line: the old table keeps no dates, so the period filter is not offered."""
    return "Яаралтай үед холбогдох хүмүүсийн бүртгэл. Хуучин програмд огноо хадгалагддаггүй тул хугацаагаар шүүхгүй."


REPORT = Report(
    key="contacts",
    title="Ажилчидтай холбоо барих",
    filters=("state", "branch", "department", "contact_type"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=NEEDS_PERSONAL,
    source=ContactRow,
    group_options=("department", "type"),
    note=_note,
)
