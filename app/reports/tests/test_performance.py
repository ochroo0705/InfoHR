from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import Employee
from employees.services import macs_writes
from macs.models import AddedValBudgetRow, AddedValStat, EmployeeGradeRow

from reports.filters import Filters, this_quarter
from reports.performance import REPORT, SUMMARY, kpi_for, month_percent, quarter_of
from reports.types import Column

from .conftest import count_queries, legacy

pytestmark = pytest.mark.django_db

YEAR = 2026
Q1 = Filters(year=YEAR, quarter=1)


@pytest.fixture(autouse=True)
def no_production_rows() -> None:
    """The test database may hold production budget and indicator rows; each test starts with none."""
    AddedValBudgetRow.objects.all().delete()
    AddedValStat.objects.all().delete()


def _stat(description: str = "Үзүүлэлт", weight: str = "40") -> AddedValStat:
    return AddedValStat.objects.create(description=description, percentm=Decimal(weight))


def _budget(employee: Employee, stat: int, year: int = YEAR, **months: Decimal) -> AddedValBudgetRow:
    """A budget row as the production table holds one: a composite key, twelve norm and twelve execution columns."""
    return AddedValBudgetRow.objects.create(stat=stat, year=year, employee=employee, dep_id=1, **months)


def _column(key: str) -> Column:
    return next(c for c in REPORT.columns if c.key == key)


def _three_people(actor: User, job_values: dict[str, Any], hired: Employee) -> list[Employee]:
    """Three different people, legacy first (the one-person baseline is legacy too)."""
    return [legacy(actor, job_values), hired, legacy(actor, job_values)]


def test_quarter_two_reads_months_four_to_six(hr_user: User, hired: Employee) -> None:
    stat = _stat()
    _budget(hired, stat.pk, budget1=Decimal("1"), exec1=Decimal("1"), budget4=Decimal("10"), exec4=Decimal("9"))
    (line,) = REPORT.rows(hr_user, Filters(year=YEAR, quarter=2))
    assert line.months[0].budget == Decimal("10")
    assert line.months[0].executed == Decimal("9")
    assert line.months[0].percent == Decimal("90")


def test_percent_and_weighted_percent(hr_user: User, hired: Employee) -> None:
    stat = _stat(weight="40")
    _budget(hired, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    (line,) = REPORT.rows(hr_user, Q1)
    assert line.months[0].percent == Decimal("90")
    assert line.months[0].weighted == Decimal("36")


def test_percent_column_shows_one_decimal(hr_user: User, hired: Employee) -> None:
    stat = _stat(weight="40")
    _budget(hired, stat.pk, budget1=Decimal("3"), exec1=Decimal("1"))
    (line,) = REPORT.rows(hr_user, Q1)
    assert _column("p_first").value(line) == Decimal("33.3")
    assert _column("w_first").value(line) == Decimal("13.3")


def test_zero_norm_rule(hr_user: User, hired: Employee) -> None:
    stat = _stat()
    _budget(hired, stat.pk, budget1=Decimal("0"), exec1=Decimal("0"), budget2=Decimal("0"), exec2=Decimal("3"))
    (line,) = REPORT.rows(hr_user, Q1)
    assert line.months[0].percent == 100
    assert line.months[1].percent == 0
    assert month_percent(Decimal("0"), Decimal("0")) == 100
    assert month_percent(Decimal("0"), Decimal("3")) == 0
    assert month_percent(Decimal("10"), Decimal("9")) == Decimal("90")


def test_quarter_of_maps_months_to_quarters() -> None:
    assert [quarter_of(date(2026, m, 1)) for m in (1, 3, 4, 6, 7, 9, 10, 12)] == [1, 1, 2, 2, 3, 3, 4, 4]


def test_missing_stat_counts_zero_weight(hr_user: User, hired: Employee) -> None:
    _budget(hired, 999999, budget1=Decimal("10"), exec1=Decimal("9"))  # no such indicator
    (line,) = REPORT.rows(hr_user, Q1)
    assert line.stat is None
    assert line.months[0].weighted == 0
    assert _column("weight").value(line) is None
    assert _column("indicator").value(line) is None


def test_default_year_and_quarter_are_the_current_ones(hr_user: User, hired: Employee) -> None:
    stat = _stat()
    first = 3 * (this_quarter() - 1) + 1
    _budget(hired, stat.pk, year=timezone.localdate().year, **{f"budget{first}": Decimal("10")})
    _budget(hired, stat.pk, year=YEAR - 1, budget1=Decimal("99"))  # another year, not this one
    (line,) = REPORT.rows(hr_user, Filters())
    assert line.months[0].budget == Decimal("10")


def test_employee_filter(hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee) -> None:
    other = legacy(actor, job_values)
    stat = _stat()
    _budget(hired, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    _budget(other, stat.pk, budget1=Decimal("10"), exec1=Decimal("5"))
    assert {x.person.row.employee.pk for x in REPORT.rows(hr_user, Q1)} == {hired.pk, other.pk}
    only = Filters(year=YEAR, quarter=1, employee=other.pk)
    assert [x.person.row.employee.pk for x in REPORT.rows(hr_user, only)] == [other.pk]


def test_other_year_rows_are_left_out(hr_user: User, hired: Employee) -> None:
    _budget(hired, _stat().pk, year=YEAR - 1, budget1=Decimal("10"))
    assert REPORT.rows(hr_user, Q1) == []


def test_accountant_and_employee_role_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/performance/").status_code == 403
    login_as(client, "Employee", "emp")
    assert client.get("/reports/performance/").status_code == 403


def test_hr_may_open_and_title_shows(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr")
    response = client.get("/reports/performance/")
    assert response.status_code == 200
    assert "Нэмэгдэх гүйцэтгэлийн үнэлгээний тайлан" in response.content.decode()


def test_bad_year_and_quarter_values_do_not_crash(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr")
    assert client.get("/reports/performance/?year=--5&quarter=9").status_code == 200


def test_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    first, *others = _three_people(actor, job_values, hired)
    stat = _stat()
    _budget(first, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    one = count_queries(REPORT, hr_user, Q1)
    for person in others:
        _budget(person, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    assert len(REPORT.rows(hr_user, Q1)) == 3
    three = count_queries(REPORT, hr_user, Q1)
    assert three[1] - three[0] == one[1] - one[0]  # rendering adds the same queries for 1 and 3 people


def test_lines_of_different_people_cost_no_query_per_line(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    people = [legacy(actor, job_values) for _ in range(3)]  # three different people, all legacy
    stat = _stat()
    for person in people:
        _budget(person, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    only_first = Filters(year=YEAR, quarter=1, employee=people[0].pk)
    three = count_queries(REPORT, hr_user, Q1)
    one = count_queries(REPORT, hr_user, only_first)
    assert len(REPORT.rows(hr_user, Q1)) == 3
    assert len(REPORT.rows(hr_user, only_first)) == 1
    assert three[0] == one[0]
    assert three[1] - three[0] == one[1] - one[0]


# ---- page level: sort, columns and the employee filter go through GET --------------------------------------------

PAGE = "/reports/performance/"


def _query(**extra: Any) -> dict[str, Any]:
    """The address parameters of the page for the test year and quarter, plus the given ones."""
    return {"year": YEAR, "quarter": 1, **extra}


def test_page_sorts_by_a_month_column(
    client: Client, login_as: Callable[..., User], actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    login_as(client, "HR", "hr-sort")
    high = legacy(actor, job_values)
    stat = _stat()
    _budget(hired, stat.pk, budget1=Decimal("10"), exec1=Decimal("3"))  # 30 %
    _budget(high, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))  # 90 %
    for sort, expected in (
        ("p_first", [Decimal("30.0"), Decimal("90.0")]),
        ("-p_first", [Decimal("90.0"), Decimal("30.0")]),
    ):
        response = client.get(PAGE, _query(sort=sort))
        assert response.status_code == 200
        table = response.context["table"]
        idx = [c.key for c in table.columns].index("p_first")
        assert [row[idx].value for row in table.groups[0][1]] == expected


def test_page_picks_one_month_column_with_cols(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR", "hr-cols")
    _budget(hired, _stat().pk, budget2=Decimal("10"), exec2=Decimal("5"))
    response = client.get(PAGE, _query(cols="p_second"))
    assert [c.key for c in response.context["table"].columns] == ["p_second"]
    assert response.context["table"].groups[0][1][0][0].value == Decimal("50.0")


def test_page_employee_filter_shows_only_that_person(
    client: Client, login_as: Callable[..., User], actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    login_as(client, "HR", "hr-emp")
    other = legacy(actor, job_values)
    stat = _stat()
    _budget(hired, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    _budget(other, stat.pk, budget1=Decimal("10"), exec1=Decimal("5"))
    response = client.get(PAGE, _query(employee=other.pk))
    assert response.context["table"].count == 1
    assert response.context["table"].groups[0][1][0][0].value == other.code  # the code column of that person


def test_page_employee_id_that_does_not_exist_is_dropped(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    """An id the user may not see (no such employee here) is reset by the page, not shown as a leak: the page
    answers 200 with the unfiltered lines, and no employee filter is kept."""
    login_as(client, "HR", "hr-noemp")
    _budget(hired, _stat().pk, budget1=Decimal("10"), exec1=Decimal("9"))
    response = client.get(PAGE, _query(employee=999999))
    assert response.status_code == 200
    assert response.context["filters"].employee is None


# ---- D5: the summary per person ------------------------------------------------------------------------------

SUMMARY_URL = "/reports/performance-summary/"


def _summary_of(user: User, pk: int, f: Filters = Q1) -> Any:
    (found,) = [s for s in SUMMARY.rows(user, f) if s.person.row.employee.pk == pk]
    return found


@pytest.mark.parametrize(
    "avg, kpi",
    [
        ("79.99", "-2"),
        ("80", "-1.5"),
        ("84.99", "-1.5"),
        ("85", "-1"),
        ("90", "-0.5"),
        ("95", "0"),
        ("100", "0"),
        ("100.01", "0.5"),
        ("105", "0.5"),
        ("105.01", "1"),
        ("110", "1"),
        ("115", "1.5"),
        ("115.01", "2"),
    ],
)
def test_kpi_steps_at_every_boundary(avg: str, kpi: str) -> None:
    assert kpi_for(Decimal(avg)) == Decimal(kpi)


def test_person_without_budget_rows_is_listed_with_zero(hr_user: User, hired: Employee) -> None:
    found = _summary_of(hr_user, hired.pk)
    assert found.perc == (Decimal(0), Decimal(0), Decimal(0))
    assert found.avg == 0
    assert found.kpi == Decimal(-2)


def test_quarter_four_uses_months_ten_to_twelve(hr_user: User, hired: Employee) -> None:
    stat = _stat(weight="40")
    _budget(
        hired,
        stat.pk,
        budget1=Decimal("10"),
        exec1=Decimal("10"),  # month 1: must not count in quarter 4
        budget10=Decimal("10"),
        exec10=Decimal("5"),  # 50 % × 40 ÷ 100 = 20
        budget11=Decimal("10"),
        exec11=Decimal("10"),  # 40
        budget12=Decimal("10"),
        exec12=Decimal("10"),  # 40
    )
    found = _summary_of(hr_user, hired.pk, Filters(year=YEAR, quarter=4))
    assert found.perc == (Decimal("20"), Decimal("40"), Decimal("40"))


def test_average_and_weights_sum_over_indicators(hr_user: User, hired: Employee) -> None:
    a = _stat("A", weight="40")
    b = _stat("B", weight="60")
    _budget(
        hired,
        a.pk,
        budget1=Decimal("10"),
        exec1=Decimal("9"),
        budget2=Decimal("10"),
        exec2=Decimal("10"),
        budget3=Decimal("10"),
    )
    _budget(
        hired,
        b.pk,
        budget1=Decimal("10"),
        exec1=Decimal("5"),
        budget2=Decimal("10"),
        exec2=Decimal("10"),
        budget3=Decimal("10"),
    )
    found = _summary_of(hr_user, hired.pk)
    # month 1: 90×40 + 50×60 = 66; month 2: 100×40 + 100×60 = 100; month 3: 0 executed of norm 10 each = 0
    assert found.perc == (Decimal("66"), Decimal("100"), Decimal("0"))
    assert found.avg == Decimal(166) / 3
    assert found.kpi == Decimal(-2)


def test_grade_column_hidden_without_salary_right(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr-grade")
    response = client.get(SUMMARY_URL, _query())
    assert response.status_code == 200
    assert "Зэргийн хувь" not in response.content.decode()
    assert "grade" not in [c.key for c in response.context["table"].columns]


def _admin() -> User:
    user = User.objects.create_user("admin-perf", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name="Admin"))
    return user


def test_grade_is_shown_per_person_with_salary_right(hr_user: User, hired: Employee) -> None:
    EmployeeGradeRow.objects.filter(pk=hired.pk).update(grade_perc=Decimal("12.50"))
    assert _summary_of(_admin(), hired.pk).grade == Decimal("12.50")
    assert _summary_of(hr_user, hired.pk).grade is None


def test_left_people_are_not_listed(hr_user: User, left_employee: Employee, hired: Employee) -> None:
    _budget(left_employee, _stat().pk, budget1=Decimal("10"), exec1=Decimal("9"))
    pks = {s.person.row.employee.pk for s in SUMMARY.rows(hr_user, Q1)}
    assert hired.pk in pks
    assert left_employee.pk not in pks


def test_accountant_and_employee_role_refused_summary(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc-sum")
    assert client.get(SUMMARY_URL).status_code == 403
    login_as(client, "Employee", "emp-sum")
    assert client.get(SUMMARY_URL).status_code == 403


def test_summary_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    first, *others = _three_people(actor, job_values, hired)
    stat = _stat()
    _budget(first, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    one = count_queries(SUMMARY, hr_user, Q1)
    for person in others:
        _budget(person, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    assert len(SUMMARY.rows(hr_user, Q1)) == 3
    three = count_queries(SUMMARY, hr_user, Q1)
    assert three[1] - three[0] == one[1] - one[0]


def _split_department_counts(
    user: User, actor: User, job_values: dict[str, Any]
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Query counts of the summary for three different people in one department, then for one of them: the other
    two are moved to another department, so the same filter sees one person. Each side is (R, T)."""
    home = macs_writes.save_department("Нэг хэлтэс")
    away = macs_writes.save_department("Хоёр хэлтэс")
    people = [legacy(actor, job_values, department=home) for _ in range(3)]
    stat = _stat()
    for person in people:
        _budget(person, stat.pk, budget1=Decimal("10"), exec1=Decimal("9"))
    scope = Filters(year=YEAR, quarter=1, department=home.pk)
    three = count_queries(SUMMARY, user, scope)
    assert len(SUMMARY.rows(user, scope)) == 3
    Employee.objects.filter(pk__in=[people[1].pk, people[2].pk]).update(department=away)
    one = count_queries(SUMMARY, user, scope)
    assert len(SUMMARY.rows(user, scope)) == 1
    return three, one


def test_summary_queries_do_not_grow_per_person(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    three, one = _split_department_counts(hr_user, actor, job_values)
    assert three[0] == one[0]  # the rows alone: the same queries for 3 people and for 1
    assert three[1] - three[0] == one[1] - one[0]


def test_summary_queries_do_not_grow_per_person_with_salary_right(actor: User, job_values: dict[str, Any]) -> None:
    three, one = _split_department_counts(_admin(), actor, job_values)
    assert three[0] == one[0]
    assert three[1] - three[0] == one[1] - one[0]
