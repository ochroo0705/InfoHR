"""The holidays page's rules: the year, the add and delete of one date, and the recount after an action.

The Django view calls this module; the API routes will call it too, so these tests pin the rules for both.
"""

from datetime import date

import pytest
from accounts.models import User
from macs.models import Employee, LeaveAssign, LeaveTypeRow

from leave.services import calendar, writes
from leave.services.holiday_page import (
    add_holiday,
    apply_holiday_action,
    delete_holiday,
    holiday_page,
    parse_year,
)

pytestmark = pytest.mark.django_db

NOV_WEEK = (date(2026, 11, 2), date(2026, 11, 6))  # Mon-Fri, 5 working days
BAD_DATE = "Огноо буруу эсвэл нэр хоосон байна."
OTHER_YEAR = "Огноо сонгосон жилийнх байх ёстой."
TOO_LONG = "Нэр 100 тэмдэгтээс урт байж болохгүй."


def test_parse_year_reads_a_valid_year() -> None:
    assert parse_year("2027", 2026) == 2027


def test_parse_year_falls_back_on_junk_and_out_of_range() -> None:
    assert parse_year("abc", 2026) == 2026
    assert parse_year(None, 2026) == 2026
    assert parse_year("", 2026) == 2026
    assert parse_year("1899", 2026) == 2026
    assert parse_year("3000", 2026) == 2026


def test_add_holiday_refusals_leave_the_table_unchanged() -> None:
    before = calendar.holiday_names(2026)
    cases = [
        ("x", "Амралт", BAD_DATE),
        ("2026-11-04", "", BAD_DATE),
        ("2026-11-04", "   ", BAD_DATE),
        ("2027-01-01", "Шинэ жил", OTHER_YEAR),
        ("2026-11-04", "а" * 101, TOO_LONG),
    ]
    for raw_date, raw_name, text in cases:
        assert add_holiday(2026, raw_date, raw_name) == text
        assert calendar.holiday_names(2026) == before


def test_add_holiday_saves_a_stripped_name() -> None:
    assert add_holiday(2026, "2026-11-04", "  Амралт  ") == ""
    assert calendar.holiday_names(2026)[date(2026, 11, 4)] == "Амралт"


def test_delete_holiday_removes_one_day() -> None:
    add_holiday(2026, "2026-11-04", "Амралт")
    delete_holiday(2026, "2026-11-04")
    assert date(2026, 11, 4) not in calendar.holiday_names(2026)


def test_delete_holiday_ignores_a_bad_date_and_a_day_not_listed() -> None:
    add_holiday(2026, "2026-11-04", "Амралт")
    before = calendar.holiday_names(2026)
    delete_holiday(2026, "x")
    delete_holiday(2026, "2026-11-05")
    assert calendar.holiday_names(2026) == before


def test_holiday_page_lists_the_year_with_the_fixed_count() -> None:
    add_holiday(2026, "2026-11-04", "Амралт")
    page = holiday_page(2026)
    assert page.year == 2026
    assert (date(2026, 11, 4), "Амралт") in page.holidays
    assert page.holidays == sorted(calendar.holiday_names(2026).items())
    assert page.fixed_count == len(calendar.FIXED_HOLIDAYS)


def test_prefill_adds_the_fixed_days_once(actor: User) -> None:
    assert apply_holiday_action(2026, "prefill", "", "", actor) == ""
    first = len(calendar.holiday_names(2026))
    assert first == len(calendar.FIXED_HOLIDAYS)
    assert apply_holiday_action(2026, "prefill", "", "", actor) == ""
    assert len(calendar.holiday_names(2026)) == first


def test_add_action_recounts_an_info_hr_leave_and_skips_an_old_row(
    employee: Employee, annual: LeaveTypeRow, sick: LeaveTypeRow, actor: User
) -> None:
    info_hr = writes.record_assign(employee, annual, *NOV_WEEK, 5, "", actor)
    old = LeaveAssign.objects.create(
        employee=employee,
        leave_type=sick,  # the unique key is (employee, type, dates): another type keeps both rows
        date1=NOV_WEEK[0],
        date2=NOV_WEEK[1],
        status=LeaveAssign.APPROVED,
        adays=5,
        comment="",
    )
    assert apply_holiday_action(2026, "add", "2026-11-04", "Амралт", actor) == ""
    info_hr.refresh_from_db()
    old.refresh_from_db()
    assert info_hr.adays == 4
    assert old.adays == 5


def test_add_action_returns_the_refusal_text(actor: User) -> None:
    assert apply_holiday_action(2026, "add", "x", "Амралт", actor) == BAD_DATE
    assert date(2026, 11, 4) not in calendar.holiday_names(2026)


def test_delete_action_recounts_back(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    info_hr = writes.record_assign(employee, annual, *NOV_WEEK, 5, "", actor)
    apply_holiday_action(2026, "add", "2026-11-04", "Амралт", actor)
    assert apply_holiday_action(2026, "delete", "2026-11-04", "", actor) == ""
    info_hr.refresh_from_db()
    assert info_hr.adays == 5


def test_unknown_action_changes_nothing(actor: User) -> None:
    add_holiday(2026, "2026-11-04", "Амралт")
    before = calendar.holiday_names(2026)
    assert apply_holiday_action(2026, "bogus", "2026-11-04", "", actor) == ""
    assert calendar.holiday_names(2026) == before
