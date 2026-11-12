import json
import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.helpers import record_signed
from macs.models import FiredReason

from reports.filters import Filters
from reports.registry import REPORTS
from reports.trends import REPORT, MonthRow, month_ends, rows

from .conftest import hire_values, named

pytestmark = pytest.mark.django_db

CHART_JSON = re.compile(r'<script id="report-chart-data" type="application/json">(.*?)</script>', re.S)
JAN_MAR = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31))


def test_month_ends_is_the_last_day_of_each_month() -> None:
    got = month_ends(date(2026, 1, 15), date(2026, 3, 2), date(2026, 11, 10))
    assert got == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]


def test_month_ends_never_passes_today() -> None:
    # the current month ends today, and the months after it are left out
    got = month_ends(date(2026, 1, 15), date(2026, 3, 2), date(2026, 2, 10))
    assert got == [date(2026, 1, 31), date(2026, 2, 10)]


def test_month_ends_keeps_only_the_last_24_months() -> None:
    got = month_ends(date(2021, 1, 1), date(2025, 12, 31), date(2026, 11, 10))
    assert len(got) == 24
    assert got[0] == date(2024, 1, 31) and got[-1] == date(2025, 12, 31)


def test_month_ends_is_empty_when_the_period_starts_after_today() -> None:
    assert month_ends(date(2026, 12, 1), date(2026, 12, 31), date(2026, 11, 10)) == []


def test_month_ends_leap_february_ends_on_the_29th() -> None:
    assert date(2028, 2, 29) in month_ends(date(2028, 2, 1), date(2028, 2, 29), date(2030, 1, 1))


@pytest.fixture
def history_2026(actor: Any, job_values: dict[str, Any]) -> dict[str, Employee]:
    """Three people hired in 2025 (working before the period), one hired on 10 February 2026, and one of the three
    terminated on 15 March 2026."""
    people = {
        "P1": history.hire(
            hire_values("УБ70000011"), {}, start=date(2025, 6, 1), job=job_values, salary=None, by=actor
        ),
        "P2": history.hire(
            hire_values("УБ70000012"), {}, start=date(2025, 6, 1), job=job_values, salary=None, by=actor
        ),
        "P3": history.hire(
            hire_values("УБ70000013"), {}, start=date(2025, 6, 1), job=job_values, salary=None, by=actor
        ),
    }
    people["P4"] = history.hire(
        hire_values("УБ70000014"), {}, start=date(2026, 2, 10), job=job_values, salary=None, by=actor
    )
    record_signed(
        people["P3"],
        type="termination",
        effective=date(2026, 3, 15),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    return people


def test_each_month_counts_headcount_hires_leavers_and_turnover(
    hr_user: User, history_2026: dict[str, Employee]
) -> None:
    got = rows(hr_user, JAN_MAR)
    # January: P1, P2, P3 work on 31 Jan (3); nobody hired or left; average (3 + 3) / 2 = 3; turnover 0 / 3 = 0.0
    # February: P4 hired on 10 Feb (4 on 28 Feb); 1 hired; average (3 + 4) / 2 = 3.5; turnover 0 / 3.5 = 0.0
    # March: P3 left on 15 Mar (3 on 31 Mar); 1 left; average (4 + 3) / 2 = 3.5; turnover 1 * 100 / 3.5 = 28.57 -> 28.6
    assert got == [
        MonthRow(month="2026-01", headcount=3, hired=0, left=0, net=0, turnover=Decimal("0.0")),
        MonthRow(month="2026-02", headcount=4, hired=1, left=0, net=1, turnover=Decimal("0.0")),
        MonthRow(month="2026-03", headcount=3, hired=0, left=1, net=-1, turnover=Decimal("28.6")),
    ]


def test_turnover_is_none_when_the_average_is_zero(hr_user: User, job_values: dict[str, Any], actor: User) -> None:
    # nobody works before February, so January's average is 0 and its turnover has no value
    marketing = macs_writes.save_department("Маркетинг")
    history.hire(
        hire_values("УБ70000021"),
        {},
        start=date(2026, 2, 20),
        job={**job_values, "department": marketing},
        salary=None,
        by=actor,
    )
    got = rows(hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 2, 28)))
    assert got[0] == MonthRow(month="2026-01", headcount=0, hired=0, left=0, net=0, turnover=None)


def test_department_filter_counts_only_that_department(
    hr_user: User, history_2026: dict[str, Employee], job_values: dict[str, Any], actor: User
) -> None:
    marketing = macs_writes.save_department("Маркетинг")
    history.hire(
        hire_values("УБ70000022"),
        {},
        start=date(2026, 2, 20),
        job={**job_values, "department": marketing},
        salary=None,
        by=actor,
    )
    got = rows(hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31), department=marketing.pk))
    # only the one Marketing hire on 20 Feb: 1 working on 28 Feb and 31 Mar; the others are in Санхүү
    assert [(r.month, r.headcount, r.hired, r.left) for r in got] == [
        ("2026-01", 0, 0, 0),
        ("2026-02", 1, 1, 0),
        ("2026-03", 1, 0, 0),
    ]


def test_user_without_view_employees_is_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "own")
    assert client.get("/reports/headcount-trend/").status_code == 403


def test_page_shows_the_table_and_the_line_chart(
    client: Client, login_hr: User, history_2026: dict[str, Employee]
) -> None:
    table = client.get("/reports/headcount-trend/", {"from": "2026-01-01", "to": "2026-03-31"})
    assert table.status_code == 200
    assert "Ажилтны тоо, эргэц сараар" in table.content.decode()

    page = client.get(
        "/reports/headcount-trend/",
        {
            "from": "2026-01-01",
            "to": "2026-03-31",
            "layout": "chart",
            "lby": "month",
            "lval": "headcount:sum",
            "lchart": "line",
        },
    ).content.decode()
    match = CHART_JSON.search(page)
    assert match is not None, "no report-chart-data script"
    data: dict[str, Any] = json.loads(match.group(1))
    assert data["kind"] == "line"
    assert data["labels"] == ["2026-01", "2026-02", "2026-03"]
    assert data["values"] == [3.0, 4.0, 3.0]


def test_print_and_excel_open(client: Client, login_hr: User, history_2026: dict[str, Employee]) -> None:
    assert client.get("/reports/headcount-trend/print/").status_code == 200
    assert client.get("/reports/headcount-trend/excel/").status_code == 200


def test_saved_view_templates_are_offered(client: Client, login_hr: User, history_2026: dict[str, Employee]) -> None:
    page = client.get("/reports/headcount-trend/", {"from": "2026-01-01", "to": "2026-03-31"}).content.decode()
    assert "Ажилтны тоо (шугаман)" in page
    assert "Эргэц, % (шугаман)" in page


def test_report_is_registered_as_a_chart_report() -> None:
    assert REPORTS["headcount-trend"].layouts == ("chart",)
    assert REPORT.shows_count is False
    assert REPORT.group_options == ("month",)


def test_page_note_says_legacy_people_are_counted_at_todays_status(client: Client, login_hr: User) -> None:
    page = client.get("/reports/headcount-trend/").content.decode()
    assert "Хуучин програмаас ирсэн, ажлын түүхгүй ажилтныг" in page


def test_hire_on_the_first_and_leaving_on_the_last_day_count_in_their_month(
    hr_user: User, job_values: dict[str, Any], actor: User
) -> None:
    # a hire on 1 Feb and a termination on 28 Feb both count in February; one on 31 Mar counts in March
    before = {
        "stays": history.hire(
            hire_values("УБ70000031"), {}, start=date(2025, 6, 1), job=job_values, salary=None, by=actor
        ),
        "feb_leaver": history.hire(
            hire_values("УБ70000032"), {}, start=date(2025, 6, 1), job=job_values, salary=None, by=actor
        ),
        "mar_leaver": history.hire(
            hire_values("УБ70000033"), {}, start=date(2025, 6, 1), job=job_values, salary=None, by=actor
        ),
    }
    history.hire(hire_values("УБ70000034"), {}, start=date(2026, 2, 1), job=job_values, salary=None, by=actor)
    for name, on in (("feb_leaver", date(2026, 2, 28)), ("mar_leaver", date(2026, 3, 31))):
        record_signed(
            before[name],
            type="termination",
            effective=on,
            changes={},
            salary=None,
            reason="",
            note="",
            by=actor,
            fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
        )
    got = rows(hr_user, JAN_MAR)
    assert [(r.month, r.hired, r.left) for r in got] == [
        ("2026-01", 0, 0),
        ("2026-02", 1, 1),
        ("2026-03", 0, 1),
    ]


def test_a_change_after_today_is_not_counted(hr_user: User, job_values: dict[str, Any], actor: User) -> None:
    today = timezone.localdate()
    history.hire(
        hire_values("УБ70000035"),
        {},
        start=today + timedelta(days=1),
        job=job_values,
        salary=None,
        by=actor,
    )
    got = rows(hr_user, Filters(date_from=date(today.year, 1, 1), date_to=today + timedelta(days=1)))
    assert got and got[-1].month == f"{today:%Y-%m}"  # the period's last month ends today, not tomorrow
    assert sum(r.hired for r in got) == 0
