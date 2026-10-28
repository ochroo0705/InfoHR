"""A7 «Гутал, хувцасны хэмжээний судалгаа»: the working staff counted by clothing and shoe size, gender and size.
Each person is counted once per kind (clothing, shoes)."""

from collections import Counter
from dataclasses import dataclass
from typing import Any

from accounts.models import User
from employees.models import Employee

from reports import survey_common
from reports.filters import Filters
from reports.survey_common import NEEDS_PERSONAL, UNKNOWN
from reports.types import Column, Report

CLOTHING = "Хувцас"
SHOES = "Гутал"
KIND_ORDER: dict[str, int] = {CLOTHING: 0, SHOES: 1}
GENDERS: dict[str, str] = {"M": "Эрэгтэй", "F": "Эмэгтэй"}
OTHER_GENDER = "Тодорхойгүй"  # a gender that is neither M nor F, or none


@dataclass(frozen=True)
class SizeLine:
    kind: str  # CLOTHING or SHOES
    gender: str  # a GENDERS label or OTHER_GENDER
    size: str  # the size name, or UNKNOWN
    qty: int


def _size(obj: Any) -> str:
    """The size name; UNKNOWN when the person has no size or the size has no name."""
    if obj is None or not obj.name:
        return UNKNOWN
    name: str = obj.name
    return name


def _rows(user: User, f: Filters) -> list[SizeLine]:
    """The working people for the branch and department filters, counted by kind, gender and size."""
    people = survey_common.people(user, Filters(state="working", branch=f.branch, department=f.department))
    counts: Counter[tuple[str, str, str]] = Counter()
    for p in people:
        employee = p.row.employee
        gender = GENDERS.get(employee.gender or "", OTHER_GENDER)
        counts[(CLOTHING, gender, _size(employee.clothing_size))] += 1
        counts[(SHOES, gender, _size(employee.shoe_size))] += 1
    lines = [SizeLine(kind=k, gender=g, size=s, qty=n) for (k, g, s), n in counts.items()]
    lines.sort(key=lambda line: (KIND_ORDER[line.kind], line.gender, line.size))
    return lines


COLUMNS: tuple[Column, ...] = (
    Column(key="kind", label="Төрөл", value=lambda s: s.kind),
    Column(key="gender", label="Хүйс", value=lambda s: s.gender),
    Column(key="size", label="Хэмжээ", value=lambda s: s.size),
    Column(key="qty", label="Тоо", value=lambda s: s.qty, numeric=True),
)


def _note(f: Filters) -> str:
    """The grey line: which staff are counted."""
    return "Ажиллаж байгаа ажилтнууд."


REPORT = Report(
    key="sizes",
    title="Гутал, хувцасны хэмжээний судалгаа",
    filters=("branch", "department"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=NEEDS_PERSONAL,
    source=Employee,
    group_options=("kind", "gender"),
    note=_note,
)
