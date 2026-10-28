"""A3 «Дэлгэрэнгүй хайлт, статистик»: the working staff counted by one chosen attribute, with the count and the share of
each value. The people are the staff list's selection (survey_common.people)."""

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from accounts.models import User
from employees.models import Employee
from macs.models import AddressRow

from reports import staff_list, survey_common
from reports.filters import Filters
from reports.survey_common import NEEDS_PERSONAL, UNKNOWN, Person, bracket
from reports.types import Column, Report

ValueOf = Callable[[Person, dict[int, str]], str | None]  # a person's value; the city map is keyed by employee id


@dataclass(frozen=True)
class Count:
    label: str  # the value, or UNKNOWN
    qty: int
    share: Decimal  # the percentage of the people counted, one decimal


def _code(field: str) -> ValueOf:
    """The name of one code-list field of the person's employee; None when the field is empty."""

    def value(p: Person, _cities: dict[int, str]) -> str | None:
        obj: Any = getattr(p.row.employee, field)
        return obj.name if obj is not None else None

    return value


def _gender(p: Person, _cities: dict[int, str]) -> str | None:
    label: str | None = p.row.employee.get_gender_display()
    return label


def _age(p: Person, _cities: dict[int, str]) -> str | None:
    return bracket(p.age)


def _department(p: Person, _cities: dict[int, str]) -> str | None:
    return survey_common.department(p)


def _position(p: Person, _cities: dict[int, str]) -> str | None:
    return survey_common.position(p)


def _city(p: Person, cities: dict[int, str]) -> str | None:
    return cities.get(p.row.employee.pk)


# One value function per attribute of filters.ATTRIBUTES.
VALUES: dict[str, ValueOf] = {
    "gender": _gender,
    "age": _age,
    "department": _department,
    "position": _position,
    "branch": _code("branch"),
    "education": _code("education_level"),
    "degree": _code("academic_degree"),
    "marital": _code("marital_status"),
    "nationality": _code("nationality"),
    "citizenship": _code("citizenship"),
    "social_origin": _code("social_origin"),
    "housing": _code("housing_condition"),
    "car": _code("car_ownership"),
    "clothing": _code("clothing_size"),
    "shoe": _code("shoe_size"),
    "city": _city,
}


def _cities(employee_ids: Iterable[int]) -> dict[int, str]:
    """The city name of each person's first home address; people with none are left out."""
    first = staff_list.first_per_employee(
        AddressRow.objects.select_related("city").filter(employee_id__in=list(employee_ids))
    )
    return {pk: row.city.name for pk, row in first.items() if row.city_id is not None and row.city.name}


def _share(qty: int, total: int) -> Decimal:
    return (Decimal(qty) * 100 / Decimal(total)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _rows(user: User, f: Filters) -> list[Count]:
    """The counts of the chosen attribute (default gender), biggest first, then by label."""
    key = f.attribute or "gender"
    people = survey_common.people(user, f)
    cities = _cities(p.row.employee.pk for p in people) if key == "city" else {}
    value_of = VALUES[key]
    counts: Counter[str] = Counter(value_of(p, cities) or UNKNOWN for p in people)
    total = len(people)
    found = [Count(label=label, qty=qty, share=_share(qty, total)) for label, qty in counts.items()]
    found.sort(key=lambda c: (-c.qty, c.label))
    return found


def _note(f: Filters) -> str:
    """The grey line: what the numbers count."""
    return "Тоо нь сонгосон шинжээр ангилсан ажилтны тоо."


COLUMNS: tuple[Column, ...] = (
    Column(key="label", label="Утга", value=lambda c: c.label),
    Column(key="qty", label="Тоо", value=lambda c: c.qty, numeric=True),
    Column(key="share", label="Хувь", value=lambda c: c.share, numeric=True),
)


REPORT = Report(
    key="statistics",
    title="Дэлгэрэнгүй хайлт, статистик",
    filters=("state", "as_of", "branch", "department", "attribute"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=NEEDS_PERSONAL,
    source=Employee,
    note=_note,
)
