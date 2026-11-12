"""Which reports offer row selection (`Report.person`): the audit behind Reports Part 3, Task 7.

A report opts in only when each of its rows is exactly one person, so a bulk action can count people from the
rows and a person is never listed twice. Reports whose rows are events (a child, a penalty, an absence, an order,
a loan, a change), or several lines per person (leave balance, budget indicators, gifts due), or statistic lines
(counts, not people) do not opt in.

Opted in (`person` set; the rows are one person each):
- staff-list: one row per visible employee (the original opt-in).
- ages: one row per staff member counted on the day (the survey people, one per employee).
- elders: one row per staff member at the elder age, wrapping that same person.
- household-income: one income line per staff member.
- annual-leave: one row per staff member not left on the as-of date (the annual balance row).
- absence-totals: one row per person with counted leave or old-log absence days in the period.
- performance-summary: one row per working person (zeros when there are no budget rows).
- staff-compare: one row per person who differs between the two days.
- data-gaps: one row per employee with a missing field.

Left out (`person` stays None):
- children: one row per child, a parent can have several.
- contacts: one row per emergency contact.
- engineers: budget lines per kind and position, not people.
- sizes: counts per kind, gender and size, not people.
- statistics: counts per category, not people.
- leave-balance: the annual row plus one row per other leave type, so a person can repeat.
- leave-requests: one row per leave.
- absences: one row per absence record.
- away-on-date: one row per absence that covers the day.
- movements, history: one row per change event.
- leavers: one row per leaving change event.
- orders: one row per order.
- discipline: one row per penalty.
- awards: one row per award.
- training, health-checks, skill-tasks, complaints: one row per record.
- gifts-given: one row per gift given.
- gifts-due: one row per child with no gift for the age.
- loans: one row per loan.
- performance: one row per budget indicator of each person.
- accidents, poisoning: statistic lines (shows_count off), not people.
- headcount-trend: one row per month, not people.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.utils import timezone
from employees.models import Employee
from employees.services import macs_writes
from macs.models import Absence, AbsenceType, AddedValBudgetRow, AddedValStat

from reports.filters import Filters
from reports.registry import REPORTS

from .conftest import legacy

pytestmark = pytest.mark.django_db

OPTED_IN: tuple[str, ...] = (
    "staff-list",
    "household-income",
    "annual-leave",
    "absence-totals",
    "performance-summary",
    "staff-compare",
    "data-gaps",
)
LEFT_OUT: tuple[str, ...] = (
    "children",
    "contacts",
    "engineers",
    "leave-balance",
    "leave-requests",
    "absences",
    "away-on-date",
    "movements",
    "history",
    "leavers",
    "orders",
    "discipline",
    "awards",
    "training",
    "health-checks",
    "skill-tasks",
    "complaints",
    "gifts-given",
    "gifts-due",
    "loans",
    "performance",
    "accidents",
    "poisoning",
    "headcount-trend",
)


@pytest.fixture(autouse=True)
def no_production_rows() -> None:
    """The test database may hold production budget rows; each test sets its own (as test_performance does)."""
    AddedValBudgetRow.objects.all().delete()
    AddedValStat.objects.all().delete()


@pytest.fixture
def staff(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """Four visible working people, named by the expectations below:
    A (30, Санхүү): two absences today and two budget rows this year, so each report must still list A once.
    B (40, Санхүү): one absence today.
    E (65, Санхүү): the elder, no absences, no budget rows.
    C (50, Маркетинг): no absences and no budget rows; outside the Санхүү department filter.
    Filters() reads the calendar year, which holds today."""
    year = timezone.localdate().year
    today = timezone.localdate()
    marketing = macs_writes.save_department("Маркетинг")
    people = {
        "A": legacy(actor, job_values, birth_date=date(year - 30, 1, 1)),
        "B": legacy(actor, job_values, birth_date=date(year - 40, 1, 1)),
        "E": legacy(actor, job_values, birth_date=date(year - 65, 1, 1)),
        "C": legacy(actor, job_values, birth_date=date(year - 50, 1, 1), department=marketing),
    }
    kind = AbsenceType.objects.create(name="Цалинтай чөлөө")
    for emp in (people["A"], people["A"], people["B"]):
        Absence.objects.create(employee_id=emp.pk, absence_type=kind, from_date=today, to_date=today, note="")
    for n in (1, 2):
        stat = AddedValStat.objects.create(description=f"Үзүүлэлт {n}", percentm=Decimal("40"))
        AddedValBudgetRow.objects.create(
            stat=stat.pk, year=year, employee=people["A"], dep_id=1, budget1=Decimal("100")
        )
    return people


def _cases(staff: dict[str, Employee], sanhuu: int, year: int) -> dict[str, list[tuple[Filters, set[str]]]]:
    """Per opted-in report: each filter set with the exact people (by fixture name) it must list."""
    everyone = {"A", "B", "C", "E"}
    sanhuu_only = {"A", "B", "E"}
    staff_cases = [(Filters(), everyone), (Filters(department=sanhuu), sanhuu_only)]
    return {
        "staff-list": staff_cases,
        "data-gaps": staff_cases,  # every fixture person has blank fields (no email, no contract number…)
        "household-income": staff_cases,
        "annual-leave": staff_cases,
        "absence-totals": [
            (Filters(), {"A", "B"}),
            (Filters(department=sanhuu), {"A", "B"}),
            (Filters(date_from=date(2000, 1, 1), date_to=date(2000, 12, 31)), set()),
        ],
        "performance-summary": [
            (Filters(), everyone),
            (Filters(department=sanhuu), sanhuu_only),
            (Filters(year=year - 1), everyone),  # no budget rows that year: everyone still listed, with zeros
        ],
        # the fixture hires are all on 5 January 2026 (conftest hire_values): 1 January has none of them on staff,
        # 31 January has all of them, so every fixture person is «Орсон» and the rows are real
        "staff-compare": [
            (Filters(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)), everyone),
            (Filters(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31), department=sanhuu), sanhuu_only),
        ],
    }


def test_opted_in_reports_list_exactly_the_expected_people(
    hr_user: User, staff: dict[str, Employee], job_values: dict[str, Any]
) -> None:
    sanhuu = job_values["department"].pk
    year = timezone.localdate().year
    cases = _cases(staff, sanhuu, year)
    assert set(cases) == {key for key, report in REPORTS.items() if report.person is not None}
    for key, runs in cases.items():
        report = REPORTS[key]
        assert report.person is not None, key
        for f, expected in runs:
            ids = [report.person(row) for row in report.rows(hr_user, f)]
            assert len(ids) == len(set(ids)), f"{key} {f}: a person is listed more than once"
            assert sorted(ids) == sorted(staff[name].pk for name in expected), f"{key} {f}: wrong people"


def test_person_with_two_budget_rows_is_one_summary_row(hr_user: User, staff: dict[str, Employee]) -> None:
    rows = REPORTS["performance-summary"].rows(hr_user, Filters())
    mine = [r for r in rows if r.person.row.employee.pk == staff["A"].pk]
    assert len(mine) == 1


def test_person_with_two_absences_is_one_totals_row(hr_user: User, staff: dict[str, Employee]) -> None:
    rows = REPORTS["absence-totals"].rows(hr_user, Filters())
    mine = [r for r in rows if r.person.employee.pk == staff["A"].pk]
    assert len(mine) == 1
    assert mine[0].log_entries == 2  # both absences are counted, on one row


def test_reports_not_opted_in_have_no_person() -> None:
    for key in LEFT_OUT:
        assert REPORTS[key].person is None, key
    opted = {key for key, report in REPORTS.items() if report.person is not None}
    assert opted == set(OPTED_IN)
    assert not set(OPTED_IN) & set(LEFT_OUT)
    assert set(OPTED_IN) | set(LEFT_OUT) == set(REPORTS), "a new report needs a decision here"
