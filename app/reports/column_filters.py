"""Column filters of the staff table: one filter per staff-table column that can be narrowed (A code list, a choice,
a date range or a number range). Each filter is gated by the permission of its column (`ColumnFilter.column`).

Kept apart from reports/filters.py so that filters.py can import it without a cycle."""

import re
from dataclasses import dataclass
from typing import Any

from config.params import date_param, id_param
from django.db import models
from django.http import QueryDict
from macs.models import (
    AcademicDegree,
    Bank,
    CarOwnership,
    ClothesSize,
    Country,
    EducationLevel,
    ElectedPosition,
    HousingCondition,
    InsuredCategory,
    MaritalStatus,
    Nationality,
    SocialOrigin,
)

_DIGITS = re.compile(r"[0-9]{1,12}")  # a number range bound: digits only, at most 12


@dataclass(frozen=True)
class ColumnFilter:
    name: str  # the query parameter (a range adds "_from" and "_to")
    label: str  # the Mongolian label shown in the filter line
    kind: str  # "code" | "choice" | "date" | "number"
    column: str  # the staff-table column key whose `needs` gates this filter
    model: type[models.Model] | None = None  # the code list a "code" filter reads
    choices: tuple[tuple[int, str], ...] = ()  # the values a "choice" filter accepts


COLUMN_FILTERS: dict[str, ColumnFilter] = {
    cf.name: cf
    for cf in (
        ColumnFilter("nationality", "Үндэс угсаа", "code", "nationality", model=Nationality),
        ColumnFilter("citizenship", "Иргэншил", "code", "citizenship", model=Country),
        ColumnFilter("social_origin", "Нийгмийн гарал", "code", "social_origin", model=SocialOrigin),
        ColumnFilter("elected_position", "Сонгуульт ажил", "code", "elected_position", model=ElectedPosition),
        ColumnFilter("education_level", "Боловсрол", "code", "education_level", model=EducationLevel),
        ColumnFilter("academic_degree", "Эрдмийн зэрэг", "code", "academic_degree", model=AcademicDegree),
        ColumnFilter("marital_status", "Гэрлэлтийн байдал", "code", "marital_status", model=MaritalStatus),
        ColumnFilter("housing_condition", "Орон байрны нөхцөл", "code", "housing_condition", model=HousingCondition),
        ColumnFilter("car_ownership", "Автомашин эзэмшил", "code", "car_ownership", model=CarOwnership),
        ColumnFilter("clothing_size", "Хувцасны хэмжээ", "code", "clothing_size", model=ClothesSize),
        ColumnFilter("shoe_size", "Гутлын хэмжээ", "code", "shoe_size", model=ClothesSize),
        ColumnFilter("bank", "Банк", "code", "bank", model=Bank),
        ColumnFilter("insured_category", "Даатгуулагчийн төрөл", "code", "insured_category", model=InsuredCategory),
        ColumnFilter(
            "work_conditions",
            "Ажлын нөхцөл",
            "choice",
            "work_conditions",
            choices=((1, "Хэвийн"), (2, "Хүнд"), (3, "Бусад")),
        ),
        ColumnFilter("hired", "Ажилд орсон", "date", "first_hire_date"),
        ColumnFilter("contract_end", "Гэрээ дуусах", "date", "contract_end"),
        ColumnFilter("salary", "Үндсэн цалин", "number", "salary"),
    )
}


def params_of(cf: ColumnFilter) -> tuple[str, ...]:
    """The query parameters of a filter: one value, or the "_from" and "_to" bounds of a range."""
    if cf.kind in ("date", "number"):
        return (f"{cf.name}_from", f"{cf.name}_to")
    return (cf.name,)


def _value(cf: ColumnFilter, param: str, get: QueryDict) -> str | None:
    """The clean value of one parameter as text, or None when it is missing or not valid. Never raises."""
    raw = get.get(param)
    if cf.kind == "code":
        number = id_param(raw)
        return None if number is None else str(number)
    if cf.kind == "choice":
        number = id_param(raw)
        return str(number) if number in dict(cf.choices) else None
    if cf.kind == "date":
        parsed = date_param(raw)
        return None if parsed is None else parsed.isoformat()
    if raw is not None and _DIGITS.fullmatch(raw):
        return raw
    return None


def parse_extra(get: QueryDict) -> tuple[tuple[str, str], ...]:
    """The column filters set in the address, as (parameter, value) pairs in registry order.
    Bad values are left out; this never raises."""
    pairs: list[tuple[str, str]] = []
    for cf in COLUMN_FILTERS.values():
        for param in params_of(cf):
            value = _value(cf, param, get)
            if value is not None:
                pairs.append((param, value))
    return tuple(pairs)


def name_of(objects: models.Manager[Any], pk: int) -> str | None:
    """The name of the code-list row with this id, None when there is no such row. Shared with reports/filters.py."""
    name: str | None = objects.filter(pk=pk).values_list("name", flat=True).first()
    return name


def _code_name(model: type[models.Model] | None, value: str) -> str:
    """The name of a code-list row, «—» when there is none."""
    if model is None:
        return "—"
    return name_of(model._default_manager, int(value)) or "—"


def describe_extra(extra: tuple[tuple[str, str], ...]) -> list[str]:
    """Filter lines for print and Excel, one per column filter that is set, in registry order."""
    given: dict[str, str] = dict(extra)
    lines: list[str] = []
    for cf in COLUMN_FILTERS.values():
        if cf.kind == "code" and cf.name in given:
            lines.append(f"{cf.label}: {_code_name(cf.model, given[cf.name])}")
        elif cf.kind == "choice" and cf.name in given:
            lines.append(f"{cf.label}: {dict(cf.choices)[int(given[cf.name])]}")
        elif cf.kind in ("date", "number"):
            low = given.get(f"{cf.name}_from")
            high = given.get(f"{cf.name}_to")
            if low is not None or high is not None:
                lines.append(f"{cf.label}: {low or ''} – {high or ''}")
    return lines
