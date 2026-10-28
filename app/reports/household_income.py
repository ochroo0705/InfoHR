"""A10 «Өрхийн амьжиргааны баталгаажих түвшний тайлан»: per person, the household income divided by the household
size, and the income band it falls in (port of the old CALC_INCOME procedure). The income is the mirror's income
when set, else today's base salary (listing.current_salary), else 0. The household size is the family rows plus the
employee."""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.utils import timezone
from employees import listing
from employees.models import Employee
from macs.models import Department, EmployeeIncomeRow, FamilyRow, IncomeLevel

from reports import survey_common
from reports.filters import Filters
from reports.survey_common import PERSON_COLUMNS, Person, on_person
from reports.types import Column, Report

NO_LEVEL = "Түвшин тодорхойгүй"  # the level of a per-person income no band covers


@dataclass(frozen=True)
class IncomeLine:
    person: Person
    income: int  # the household income: the mirror's income, else today's base salary, else 0
    family_qty: int  # the family rows plus the employee
    per_person: int  # income // family_qty (integer division, as the old procedure)
    level: str  # the IncomeLevel the per-person income falls in; NO_LEVEL when no band does


def _person(line: IncomeLine) -> Person:
    return line.person


def _rows(user: User, f: Filters) -> list[IncomeLine]:
    """The people the filters pass, with their household income and band, by department then name."""
    persons = survey_common.people(user, f)
    ids = [p.row.employee.pk for p in persons]
    today = timezone.localdate()
    incomes: dict[int, int | None] = dict(EmployeeIncomeRow.objects.filter(pk__in=ids).values_list("pk", "income"))
    family: Counter[int] = Counter(FamilyRow.objects.filter(employee_id__in=ids).values_list("employee_id", flat=True))
    bands = list(IncomeLevel.objects.order_by("lower"))

    departments = _department_names(persons)
    lines: list[IncomeLine] = []
    for p in persons:
        emp = p.row.employee
        income = incomes.get(emp.pk) or _base_salary(emp, today)
        family_qty = family[emp.pk] + 1
        per_person = income // family_qty
        level = next((b.level for b in bands if b.lower < per_person <= b.upper), NO_LEVEL)
        lines.append(IncomeLine(person=p, income=income, family_qty=family_qty, per_person=per_person, level=level))
    lines.sort(key=lambda x: departments.get(x.person.row.employee.pk, ""))  # stable: name order inside a department
    return lines


def _department_names(persons: list[Person]) -> dict[int, str]:
    """The department name of each person (one query for all), keyed by employee id."""
    dept_ids = {p.row.job.department_id for p in persons if p.row.job is not None and p.row.job.department_id}
    names: dict[int, str] = {
        pk: name or "" for pk, name in Department.objects.filter(pk__in=dept_ids).values_list("pk", "name")
    }
    return {p.row.employee.pk: names.get(p.row.job.department_id, "") if p.row.job is not None else "" for p in persons}


def _base_salary(employee: Employee, today: date) -> int:
    """Today's base salary as whole tugrik; 0 when there is none."""
    salary = listing.current_salary(employee, today)
    return int(salary.base_salary) if salary is not None else 0


COLUMNS: tuple[Column, ...] = (
    *(on_person(c, _person) for c in PERSON_COLUMNS),
    Column(key="income", label="Өрхийн орлого", value=lambda x: x.income, numeric=True, money=True),
    Column(key="family_qty", label="Өрхийн хүний тоо", value=lambda x: x.family_qty, numeric=True),
    Column(key="per_person", label="1 хүнд ноогдох орлого", value=lambda x: x.per_person, numeric=True, money=True),
    Column(key="level", label="Түвшин", value=lambda x: x.level),
    Column(
        key="age",
        label="Нас",
        value=lambda x: x.person.age,
        needs="macs.view_personal",
        numeric=True,
    ),
    Column(
        key="gender",
        label="Хүйс",
        value=lambda x: x.person.row.employee.get_gender_display(),
        needs="macs.view_personal",
    ),
)


def _note(f: Filters) -> str:
    """The grey line: where the income comes from and how the household is counted."""
    return "Орлого бүртгээгүй бол үндсэн цалинг авна. Өрхийн хүний тоо = гэр бүлийн гишүүд + ажилтан."


REPORT = Report(
    key="household-income",
    title="Өрхийн амьжиргааны баталгаажих түвшний тайлан",
    filters=("state", "as_of", "branch", "department"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=("macs.view_employees", "macs.view_salary"),
    source=IncomeLevel,
    group_options=("department", "level"),
    note=_note,
)
