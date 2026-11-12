"""The calendar's yearly repeat («Давтах»): a birthday or anniversary shows on its day in every later year, and
29 February shows on 28 February in other years. An entry shows from its own year on, and an entry with an end
never repeats. The choice turns the default off or on; the staff list repeats its birth date, and birthdays stay
hidden without view_personal."""

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client

from reports.filters import Filters, parse_filters
from reports.layouts import Calendar, Day, LayoutSpec, build_calendar, clean_params, layout_choices, resolve
from reports.staff_list import REPORT as STAFF_LIST
from reports.table import Table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
BIRTH = Column(key="birth", label="Төрсөн огноо", value=lambda r: r.birth, kind="date")
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
END = Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")


def _row(name: str, birth: object = None, start: object = None, end: object = None) -> Any:
    return SimpleNamespace(name=name, birth=birth, start=start, end=end)


def _spec(by: Column, month: date, by2: Column | None = None, rep: bool = True) -> LayoutSpec:
    return LayoutSpec(layout="calendar", by=by, by2=by2, value=(None, "count"), chart="bar", month=month, rep=rep)


def _build(rows: list[Any], spec: LayoutSpec) -> Calendar:
    table = Table(
        columns=[NAME, BIRTH, START, END], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec
    )
    return build_calendar(table, spec, (), TODAY)


def _day(cal: Calendar, day: date) -> Day:
    for week in cal.weeks:
        for cell in week:
            if cell.day == day:
                return cell
    raise AssertionError(f"{day} is not in the grid")


def _titles(cal: Calendar, day: date) -> list[str]:
    return [item.title for item in _day(cal, day).items]


def _parse(raw: str) -> Filters:
    return parse_filters(QueryDict(raw))


def _report(layout_repeat: tuple[str, ...]) -> Report:
    return Report(
        key="layout-repeat",
        title="Тайлан",
        filters=(),
        columns=(NAME, BIRTH, START, END),
        default_columns=("name",),
        rows=lambda user, filters: [],
        layouts=("calendar",),
        layout_repeat=layout_repeat,
    )


def test_birthday_repeats_in_another_year() -> None:
    rows = [_row("Бат", birth=date(1990, 11, 15))]
    cal = _build(rows, _spec(BIRTH, date(2026, 11, 1)))
    assert _titles(cal, date(2026, 11, 15)) == ["Бат"]
    assert _day(cal, date(2026, 11, 15)).items[0].note == "36 жил"


def test_december_grid_shows_an_early_january_anniversary_of_the_next_year() -> None:
    cal = _build([_row("Бат", birth=date(1990, 1, 3))], _spec(BIRTH, date(2026, 12, 1)))
    assert _titles(cal, date(2027, 1, 3)) == ["Бат"]
    assert _day(cal, date(2027, 1, 3)).items[0].note == "37 жил"


def test_january_grid_shows_a_late_december_anniversary_of_the_previous_year() -> None:
    cal = _build([_row("Бат", birth=date(1990, 12, 28))], _spec(BIRTH, date(2027, 1, 1)))
    assert _titles(cal, date(2026, 12, 28)) == ["Бат"]
    assert _day(cal, date(2026, 12, 28)).items[0].note == "36 жил"


def test_feb_29_in_a_non_leap_year_shows_on_feb_28() -> None:
    cal = _build([_row("Бат", birth=date(2000, 2, 29))], _spec(BIRTH, date(2027, 2, 1)))
    assert _titles(cal, date(2027, 2, 28)) == ["Бат"]
    assert _day(cal, date(2027, 2, 28)).items[0].note == "27 жил"
    assert _titles(cal, date(2027, 2, 27)) == []


def test_not_shown_before_its_own_year() -> None:
    cal = _build([_row("Бат", start=date(2030, 5, 1))], _spec(START, date(2026, 5, 1)))
    assert _titles(cal, date(2026, 5, 1)) == []
    assert all(not day.items for week in cal.weeks for day in week)


def test_entry_with_an_end_never_repeats() -> None:
    rows = [_row("Бат", start=date(2025, 11, 15), end=date(2025, 11, 16))]
    real = _build(rows, _spec(START, date(2025, 11, 1), by2=END))
    assert _titles(real, date(2025, 11, 15)) == ["Бат"]
    later = _build(rows, _spec(START, date(2026, 11, 1), by2=END))
    assert _titles(later, date(2026, 11, 15)) == []
    assert _titles(later, date(2026, 11, 16)) == []


def test_lrep_0_turns_the_report_default_off(accountant_user: User) -> None:
    report = _report(layout_repeat=("birth",))
    default = resolve(report, accountant_user, _parse("layout=calendar&lby=birth"))
    off = resolve(report, accountant_user, _parse("layout=calendar&lby=birth&lrep=0"))
    on = resolve(report, accountant_user, _parse("layout=calendar&lby=birth&lrep=1"))
    assert default.rep is True
    assert off.rep is False
    assert on.rep is True
    rows = [_row("Бат", birth=date(1990, 11, 15))]
    assert _titles(_build(rows, off), date(2026, 11, 15)) == []
    assert _titles(_build(rows, default), date(2026, 11, 15)) == ["Бат"]


def test_lrep_1_repeats_a_column_the_report_does_not_list(accountant_user: User) -> None:
    report = _report(layout_repeat=())
    assert resolve(report, accountant_user, _parse("layout=calendar&lby=birth")).rep is False
    assert resolve(report, accountant_user, _parse("layout=calendar&lby=birth&lrep=1")).rep is True


def test_staff_list_calendar_defaults_to_repeat_on_birth_date(hr_user: User) -> None:
    spec = resolve(STAFF_LIST, hr_user, _parse("layout=calendar&lby=birth_date"))
    assert spec.by is not None and spec.by.key == "birth_date"
    assert spec.rep is True


def test_birthdays_hidden_without_personal_permission(accountant_user: User) -> None:
    choices = layout_choices(STAFF_LIST, accountant_user, "calendar")
    assert "birth_date" not in [key for key, _ in choices.by]
    spec = resolve(STAFF_LIST, accountant_user, _parse("layout=calendar&lby=birth_date"))
    assert spec.by is not None and spec.by.key == "first_hire_date"
    assert clean_params(STAFF_LIST, accountant_user, _parse("layout=calendar&lby=birth_date"))["lby"] == ""


def test_staff_list_calendar_page_shows_the_birthday_with_its_years(client: Client, login_hr: User, hired: Any) -> None:
    query = {"layout": "calendar", "lby": "birth_date", "lmonth": "2026-11"}
    body = client.get("/reports/staff-list/", query).content.decode()
    assert " · 27 жил" in body  # hired fixture: born 1999-11-22


def test_rep_select_renders_for_the_calendar_with_the_request_value(client: Client, login_hr: User) -> None:
    body = client.get("/reports/staff-list/", {"layout": "calendar", "lrep": "0"}).content.decode()
    assert 'name="lrep"' in body
    assert 'value="0" selected>Үгүй' in body
    assert 'value="" selected>Автомат' not in body


def test_rep_select_is_not_on_the_board(client: Client, login_hr: User) -> None:
    body = client.get("/reports/staff-list/", {"layout": "board"}).content.decode()
    assert 'name="lrep"' not in body


def test_birthdays_not_on_the_page_without_personal_permission(client: Client, login_as: Any, hired: Any) -> None:
    login_as(client, "Accountant")
    url = "/reports/staff-list/"
    body = client.get(url, {"layout": "calendar", "lby": "birth_date", "lmonth": "2026-11"}).content.decode()
    assert " · 27 жил" not in body
    assert 'value="birth_date"' not in body
