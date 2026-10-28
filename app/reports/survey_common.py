"""Shared pieces of the survey reports (the «судалгаа» group): the people they count, age brackets and the
person columns. The people are the staff list's selection, so both reports agree on who is on staff."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from accounts.models import User
from django.urls import reverse
from employees import listing
from employees.services.order_register import age_on

from reports import staff_list
from reports.filters import Filters
from reports.types import Column

UNKNOWN = "Заагаагүй"  # the label of an empty attribute value
AGE_BRACKETS: tuple[tuple[int, int, str], ...] = (
    (0, 24, "24 хүртэл"),
    (25, 34, "25–34"),
    (35, 44, "35–44"),
    (45, 54, "45–54"),
    (55, 59, "55–59"),
    (60, 200, "60 ба түүнээс дээш"),
)
NEEDS_PERSONAL = ("macs.view_employees", "macs.view_personal")  # birth date and age are personal-tab facts


def bracket(age: int | None) -> str | None:
    """The age bracket label of an age; None when there is no age."""
    if age is None:
        return None
    for low, high, label in AGE_BRACKETS:
        if low <= age <= high:
            return label
    return None


@dataclass(frozen=True)
class Person:
    row: listing.Row  # the job and state on the day (listing.row_for)
    as_of: date  # the day the person is counted on
    age: int | None  # full years on `as_of`; None without a birth date


def _age(birth: date | None, day: date) -> int | None:
    """Full years on `day`; None without a birth date or before it (no age yet)."""
    age = age_on(birth, day)
    return None if age is None or age < 0 else age


def people(user: User, f: Filters) -> list[Person]:
    """The people the survey counts: the staff list's selection for these filters, sorted by name."""
    rows, day = staff_list.kept_rows(user, f)
    staff_list.load_job_names([r.job for r in rows if r.job is not None])  # department and position, one query each
    found = [Person(row=r, as_of=day, age=_age(r.employee.birth_date, day)) for r in rows]
    return sorted(found, key=lambda p: (p.row.employee.family_name or "", p.row.employee.given_name or ""))


def department(p: Person) -> str | None:
    job: Any = p.row.job
    return job.department.name if job is not None and job.department_id is not None else None


def position(p: Person) -> str | None:
    job: Any = p.row.job
    return job.position.name if job is not None and job.position_id is not None else None


def detail_url(p: Person) -> str:
    return reverse("employees:detail", args=[p.row.employee.pk])


def on_person(col: Column, person_of: Callable[[Any], Person]) -> Column:
    """A person column (PERSON_COLUMNS) read from a row that holds its person, such as a contact."""
    href = col.href
    return replace(
        col,
        value=lambda row: col.value(person_of(row)),
        href=(lambda row: href(person_of(row))) if href is not None else None,
    )


PERSON_COLUMNS: tuple[Column, ...] = (
    Column(key="code", label="Код", value=lambda p: p.row.employee.code, group=staff_list.GROUP_NAME),
    Column(
        key="name",
        label="Ажилтан",
        value=lambda p: p.row.employee.full_name,
        group=staff_list.GROUP_NAME,
        href=detail_url,
    ),
    Column(key="department", label="Хэлтэс", value=department, group=staff_list.GROUP_JOB),
    Column(key="position", label="Албан тушаал", value=position, group=staff_list.GROUP_JOB),
)
