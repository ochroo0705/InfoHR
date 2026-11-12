from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.helpers import record_signed
from macs.models import Department, FiredReason

from reports.compare import JOINED, LEFT, MOVED, days, rows
from reports.filters import Filters
from reports.registry import REPORTS

from .conftest import hire_values, named, transfer

pytestmark = pytest.mark.django_db

FROM = date(2026, 1, 15)  # the first day: B is not hired yet; C, D and E are working
TO = date(2026, 3, 31)  # the second day: B is working; C has left; D and E have moved
PERIOD = Filters(date_from=FROM, date_to=TO)


def _hire(actor: User, job: dict[str, Any], register_no: str, family: str, start: date, **job_changes: Any) -> Employee:
    values = {**hire_values(register_no), "family_name": family, "given_name": "Бат"}
    return history.hire(values, {}, start=start, job={**job, **job_changes}, salary=None, by=actor)


@pytest.fixture
def people(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """A: unchanged on both days. B: hired between the days, into Маркетинг. C: terminated between the days.
    D: transferred from Санхүү to Борлуулалт. E: promoted (position changes), same department."""
    marketing = macs_writes.save_department("Маркетинг")
    senior = macs_writes.save_position("Ахлах нягтлан")
    early = date(2025, 6, 1)
    people = {
        "A": _hire(actor, job_values, "УБ71000001", "Сэргэлэн", early),
        "B": _hire(actor, job_values, "УБ71000002", "Авга", date(2026, 2, 10), department=marketing),
        "C": _hire(actor, job_values, "УБ71000003", "Ганбат", early),
        "D": _hire(actor, job_values, "УБ71000004", "Болд", early),
        "E": _hire(actor, job_values, "УБ71000005", "Сарнай", early),
    }
    record_signed(
        people["C"],
        type="termination",
        effective=date(2026, 2, 20),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    transfer(people["D"], to="Борлуулалт", on=date(2026, 2, 1), by=actor)
    record_signed(
        people["E"],
        type="promotion",
        effective=date(2026, 3, 1),
        changes={"position": senior},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    return people


def _by_pk(found: list[Any]) -> dict[int, Any]:
    return {r.employee.pk: r for r in found}


def test_rows_lists_joined_moved_and_left_in_that_order(hr_user: User, people: dict[str, Employee]) -> None:
    got = [(r.kind, r.employee.family_name) for r in rows(hr_user, PERIOD)]
    assert got == [(JOINED, "Авга"), (MOVED, "Болд"), (MOVED, "Сарнай"), (LEFT, "Ганбат")]


def test_person_working_on_both_days_unchanged_is_absent(hr_user: User, people: dict[str, Employee]) -> None:
    assert people["A"].pk not in _by_pk(rows(hr_user, PERIOD))


def test_moved_row_has_both_department_names(hr_user: User, people: dict[str, Employee]) -> None:
    moved = _by_pk(rows(hr_user, PERIOD))[people["D"].pk]
    assert moved.before is not None and moved.after is not None
    assert moved.before.job.department.name == "Санхүү"
    assert moved.after.job.department.name == "Борлуулалт"


def test_promotion_is_moved_with_the_same_department(hr_user: User, people: dict[str, Employee]) -> None:
    promoted = _by_pk(rows(hr_user, PERIOD))[people["E"].pk]
    assert promoted.before.job.department.name == "Санхүү"
    assert promoted.after.job.department.name == "Санхүү"
    assert promoted.before.job.position.name == "Нягтлан"
    assert promoted.after.job.position.name == "Ахлах нягтлан"


def test_joined_and_left_have_one_side_only(hr_user: User, people: dict[str, Employee]) -> None:
    by_pk = _by_pk(rows(hr_user, PERIOD))
    assert by_pk[people["B"].pk].before is None
    assert by_pk[people["C"].pk].after is None


def test_department_filter_on_the_old_department_finds_the_mover(hr_user: User, people: dict[str, Employee]) -> None:
    old = Department.objects.get(name="Санхүү")
    got = {r.employee.pk for r in rows(hr_user, Filters(date_from=FROM, date_to=TO, department=old.pk))}
    assert got == {people["C"].pk, people["D"].pk, people["E"].pk}  # B is in Маркетинг, so not listed


def test_department_filter_on_the_new_department_lists_the_mover_only(
    hr_user: User, people: dict[str, Employee]
) -> None:
    sales = Department.objects.get(name="Борлуулалт")
    got = [r.employee.pk for r in rows(hr_user, Filters(date_from=FROM, date_to=TO, department=sales.pk))]
    assert got == [people["D"].pk]


def test_same_day_on_both_ends_gives_no_rows(hr_user: User, people: dict[str, Employee]) -> None:
    assert rows(hr_user, Filters(date_from=date(2026, 2, 15), date_to=date(2026, 2, 15))) == []


def test_days_cuts_the_end_to_today_and_moves_a_future_start_to_today() -> None:
    today = timezone.localdate()
    assert days(Filters(date_from=date(2020, 1, 1), date_to=date(2999, 12, 31))) == (date(2020, 1, 1), today)
    assert days(Filters(date_from=date(2999, 1, 1), date_to=date(2999, 1, 5))) == (today, today)


def test_one_row_per_person(hr_user: User, people: dict[str, Employee]) -> None:
    pks = [r.employee.pk for r in rows(hr_user, PERIOD)]
    assert pks, "the fixture must produce rows, or the distinct check proves nothing"
    assert len(pks) == len(set(pks))


def test_report_is_registered_as_a_row_report_with_selection() -> None:
    report = REPORTS["staff-compare"]
    assert report.person is not None
    assert report.shows_count is True
    assert report.layouts  # the registry gives every row report its views


def test_page_opens_for_hr_with_the_count_and_selection(
    client: Client, login_hr: User, people: dict[str, Employee]
) -> None:
    page = client.get(f"/reports/staff-compare/?from={FROM.isoformat()}&to={TO.isoformat()}")
    assert page.status_code == 200
    body = page.content.decode()
    assert "Нийт: 4" in body
    assert 'type="checkbox"' in body
    assert f'data-person="{people["D"].pk}"' in body


def test_page_says_legacy_people_are_read_on_todays_state(
    client: Client, login_hr: User, people: dict[str, Employee]
) -> None:
    page = client.get(f"/reports/staff-compare/?from={FROM.isoformat()}&to={TO.isoformat()}")
    assert "Хуучин програмаас ирсэн, ажлын түүхгүй ажилтныг" in page.content.decode()


def test_page_is_refused_without_view_employees(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "own")
    assert client.get("/reports/staff-compare/").status_code == 403
