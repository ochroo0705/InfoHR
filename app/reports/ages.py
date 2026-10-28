"""A4 «Ажилтнуудын насны судалгаа»: the staff's ages, each with its age bracket, on the chosen day."""

from typing import Any

from accounts.models import User
from employees.models import Employee

from reports import survey_common
from reports.filters import Filters
from reports.survey_common import NEEDS_PERSONAL, Person, bracket
from reports.types import Column, Report


def _rows(user: User, f: Filters) -> list[Person]:
    """The people for these filters, oldest first; people with no birth date last. Ties keep the name order."""
    people = survey_common.people(user, f)
    return sorted(people, key=lambda p: (p.age is None, -(p.age or 0)))


def _name(obj: Any) -> str | None:
    """The name of a code-list value; None when the employee has none."""
    return obj.name if obj is not None else None


COLUMNS: tuple[Column, ...] = (
    *survey_common.PERSON_COLUMNS,
    Column(key="birth_date", label="Төрсөн огноо", value=lambda p: p.row.employee.birth_date),
    Column(key="age", label="Нас", value=lambda p: p.age, numeric=True),
    Column(key="bracket", label="Насны бүлэг", value=lambda p: bracket(p.age)),
    Column(key="gender", label="Хүйс", value=lambda p: p.row.employee.get_gender_display()),
    Column(key="education_level", label="Боловсрол", value=lambda p: _name(p.row.employee.education_level)),
)


def _note(f: Filters) -> str:
    """The grey line: the age is counted to the chosen day."""
    return "Нас нь сонгосон өдрөөр бүтэн жилээр бодогдсон."


REPORT = Report(
    key="ages",
    title="Ажилтнуудын насны судалгаа",
    filters=("state", "as_of", "branch", "department"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=NEEDS_PERSONAL,
    source=Employee,
    group_options=("bracket", "department"),
    note=_note,
)
