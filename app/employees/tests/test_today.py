import re
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from leave.models import LeaveSettings
from leave.services import records
from leave.services import writes as leave_writes
from leave.services.records import Draft
from macs.models import FiredReason, LeaveAssign, LeaveTypeRow, LegalHoliday

from employees import today
from employees.listing import Row, employee_rows
from employees.models import Employee
from employees.services import events, history, macs_writes

from .conftest import hire_values, link_login, named, set_ext
from .helpers import record_signed
from .test_views import login_as

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def _user(role: str, name: str = "t1") -> User:
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return u


def _rows() -> list[Row]:
    return employee_rows(Employee.objects.all(), TODAY)


def test_home_opens_the_today_page(client: Client) -> None:
    login_as(client, "HR")
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:today")


def test_today_page_needs_login(client: Client) -> None:
    assert client.get(reverse("employees:today")).status_code == 302


def test_today_page_shows_tiles_and_empty_states(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(reverse("employees:today")).content.decode()
    assert 'data-tile="headcount">1<' in body
    assert 'data-tile="away">0<' in body
    assert 'data-tile="orders"' in body  # HR handles orders
    assert "Өнөөдөр чөлөөтэй хүн алга." in body
    assert 'class="card-soft' in body


def test_orders_tile_hidden_without_the_manage_right(hired: Employee) -> None:
    assert today.pending_orders(_user("Accountant", "acc"), _rows()) is None


def test_pending_orders_counts_unnumbered_orders(hired: Employee) -> None:
    assert today.pending_orders(_user("HR", "hr1"), _rows()) == hired.hr_orders.filter(state="pending").count()
    hired.hr_orders.update(state="registered")
    assert today.pending_orders(_user("HR", "hr2"), _rows()) == 0


def test_headcount_skips_people_who_left(hired: Employee) -> None:
    assert today.headcount(_rows()) == 1
    assert today.headcount([]) == 0


@pytest.fixture
def annual(db: None) -> LeaveTypeRow:
    return leave_writes.save_leave_type(
        "Ээлжийн амралт", {"is_paid": True, "uses_annual_balance": True, "is_active": True, "order": 1}
    )


def test_away_lists_people_on_leave_today(hired: Employee, annual: LeaveTypeRow) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    actor = User.objects.create_superuser("leave_actor", password="x-long-pass-123")  # noqa: S106
    records.record(Draft(hired, annual, date(2026, 10, 13), date(2026, 10, 16)), actor, date(2026, 10, 1))
    found = today.away_on(_user("HR", "hr3"), _rows(), TODAY)
    assert [(a.row.employee.pk, a.label, a.until) for a in found] == [(hired.pk, annual.name, date(2026, 10, 16))]
    assert today.away_on(_user("HR", "hr4"), _rows(), date(2026, 10, 17)) == []


def test_away_is_empty_without_the_leave_right(hired: Employee) -> None:
    assert today.away_on(User.objects.create_user("nobody", password="x-long-pass-123"), _rows(), TODAY) == []  # noqa: S106


def test_birthday_and_anniversary_inside_the_window(hired: Employee) -> None:
    hired.birth_date = date(1990, 10, 20)
    hired.first_hire_date = date(2023, 10, 31)
    hired.save()
    found = today.upcoming(_user("HR", "hr5"), _rows(), TODAY)
    assert [(u.kind, u.on, u.years) for u in found] == [
        ("birthday", date(2026, 10, 20), None),
        ("anniversary", date(2026, 10, 31), 3),
    ]


def test_dates_outside_the_window_and_first_year_are_left_out(hired: Employee) -> None:
    hired.birth_date = date(1990, 12, 25)  # 72 days away
    hired.first_hire_date = date(2026, 10, 20)  # 0 years: that is the hire date itself
    hired.save()
    assert today.upcoming(_user("HR", "hr6"), _rows(), TODAY) == []


def test_birthday_wraps_into_next_year(hired: Employee) -> None:
    hired.birth_date = date(1990, 1, 3)
    hired.save()
    found = today.upcoming(_user("HR", "hr7"), _rows(), date(2026, 12, 20))
    assert [u.on for u in found if u.kind == "birthday"] == [date(2027, 1, 3)]


def test_leap_day_birthday_falls_on_28_feb(hired: Employee) -> None:
    hired.birth_date = date(1992, 2, 29)
    hired.save()
    found = today.upcoming(_user("HR", "hr8"), _rows(), date(2027, 2, 10))
    assert [u.on for u in found if u.kind == "birthday"] == [date(2027, 2, 28)]


def test_birthday_needs_the_personal_right(hired: Employee) -> None:
    hired.birth_date = date(1990, 10, 20)
    hired.save()
    kinds = [u.kind for u in today.upcoming(_user("Accountant", "acc2"), _rows(), TODAY)]
    assert "birthday" not in kinds


def test_employee_sees_only_their_own_row(client: Client, hired: Employee) -> None:
    user = login_as(client, "Employee", "emp_self")
    link_login(hired, user)
    body = client.get(reverse("employees:today")).content.decode()
    assert 'data-tile="headcount">1<' in body
    assert 'data-tile="orders"' not in body


@pytest.fixture
def leave_actor(db: None) -> User:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    return User.objects.create_superuser("leave_actor2", password="x-long-pass-123")  # noqa: S106


def _record(employee: Employee, annual: LeaveTypeRow, start: date, end: date, actor: User) -> None:
    records.record(Draft(employee, annual, start, end), actor, date(2026, 10, 1))


def _old_leave(employee: Employee, leave_type: LeaveTypeRow, start: date, end: date) -> LeaveAssign:
    """A row as the old program wrote it (status NULL = recorded). The validator refuses these shapes:
    a weekend-only leave has no working day, and a leave this long overdraws the annual balance."""
    return LeaveAssign.objects.create(employee=employee, leave_type=leave_type, date1=start, date2=end, status=None)


def _second_employee(actor: User, job_values: dict[str, object]) -> Employee:
    values = hire_values("УБ99112234") | {"given_name": "Бат"}
    return history.hire(values, {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)


def _timeline() -> today.Timeline:
    return today.away_timeline(_user("HR", "tl"), _rows(), TODAY)


def test_timeline_is_never_none(hired: Employee) -> None:
    t = today.away_timeline(User.objects.create_user("nobody", password="x-long-pass-123"), _rows(), TODAY)  # noqa: S106
    assert len(t.days) == 14
    assert t.lines == []
    assert t.show_leave is False


def test_timeline_without_leave_right_has_no_bars_and_no_counts(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User
) -> None:
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 15), leave_actor)
    t = today.away_timeline(User.objects.create_user("nobody2", password="x-long-pass-123"), _rows(), TODAY)  # noqa: S106
    assert t.show_leave is False
    assert all(not line.bars for line in t.lines)
    assert t.away_counts == [None] * 14


def test_timeline_window_is_14_days_from_today(hired: Employee) -> None:
    t = _timeline()
    assert t is not None
    assert len(t.days) == 14
    assert t.days[0].day == TODAY
    assert t.days[0].is_today
    assert t.days[13].day == date(2026, 10, 27)
    assert [d.day for d in t.days if d.off] == [date(2026, 10, n) for n in (17, 18, 24, 25)]


def test_timeline_empty_when_nobody_is_away(hired: Employee) -> None:
    t = _timeline()
    assert t is not None
    assert t.lines == []
    assert t.away_counts == [0, 0, 0, None, None, 0, 0, 0, 0, 0, None, None, 0, 0]


def test_timeline_clips_a_leave_cut_on_the_left(hired: Employee, annual: LeaveTypeRow, leave_actor: User) -> None:
    _record(hired, annual, date(2026, 10, 13), date(2026, 10, 16), leave_actor)
    t = _timeline()
    assert t is not None
    assert len(t.lines) == 1
    (bar,) = t.lines[0].bars
    assert (bar.column, bar.span) == (1, 3)
    assert (bar.cut_left, bar.cut_right) == (True, False)
    assert (bar.start, bar.end) == (date(2026, 10, 13), date(2026, 10, 16))
    assert bar.label == annual.name
    assert bar.annual is True


def test_timeline_clips_a_leave_cut_on_the_right(hired: Employee, annual: LeaveTypeRow, leave_actor: User) -> None:
    _record(hired, annual, date(2026, 10, 20), date(2026, 10, 30), leave_actor)
    t = _timeline()
    assert t is not None
    (bar,) = t.lines[0].bars
    assert (bar.column, bar.span) == (7, 8)
    assert (bar.cut_left, bar.cut_right) == (False, True)


def test_timeline_leave_over_the_whole_window_is_one_full_bar(hired: Employee, annual: LeaveTypeRow) -> None:
    _old_leave(hired, annual, date(2026, 10, 1), date(2026, 11, 30))
    t = _timeline()
    assert t is not None
    (bar,) = t.lines[0].bars
    assert (bar.column, bar.span) == (1, 14)
    assert (bar.cut_left, bar.cut_right) == (True, True)


def test_timeline_counts_people_per_working_day(hired: Employee, annual: LeaveTypeRow, leave_actor: User) -> None:
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    t = _timeline()
    assert t is not None
    assert t.away_counts[:3] == [1, 1, 1]
    assert t.away_counts[3] is None


def test_timeline_weekend_only_leave_gets_a_row_but_no_count(hired: Employee, annual: LeaveTypeRow) -> None:
    _old_leave(hired, annual, date(2026, 10, 17), date(2026, 10, 18))
    t = _timeline()
    assert t is not None
    assert len(t.lines) == 1
    assert t.away_counts == [0, 0, 0, None, None, 0, 0, 0, 0, 0, None, None, 0, 0]


def test_timeline_counts_distinct_people_on_the_same_day(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User, actor: User, job_values: dict[str, object]
) -> None:
    second = _second_employee(actor, job_values)
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    _record(second, annual, date(2026, 10, 15), date(2026, 10, 15), leave_actor)
    t = _timeline()
    assert t is not None
    assert t.away_counts[:3] == [1, 2, 1]


def test_timeline_one_person_with_overlapping_leaves_is_counted_once(hired: Employee, annual: LeaveTypeRow) -> None:
    _old_leave(hired, annual, date(2026, 10, 14), date(2026, 10, 16))
    _old_leave(hired, annual, date(2026, 10, 15), date(2026, 10, 16))
    t = _timeline()
    assert t is not None
    assert len(t.lines) == 1
    assert len(t.lines[0].bars) == 2
    assert t.away_counts[:3] == [1, 1, 1]


def test_timeline_two_leaves_make_two_bars_in_one_row(hired: Employee, annual: LeaveTypeRow, leave_actor: User) -> None:
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 15), leave_actor)
    _record(hired, annual, date(2026, 10, 21), date(2026, 10, 22), leave_actor)
    t = _timeline()
    assert t is not None
    assert len(t.lines) == 1
    assert [b.column for b in t.lines[0].bars] == [1, 8]


def test_timeline_marks_public_holidays_off(hired: Employee, annual: LeaveTypeRow, leave_actor: User) -> None:
    LegalHoliday.objects.create(
        name="Тестийн баяр", start_date=date(2026, 10, 19), end_date=date(2026, 10, 19), hdays=1
    )
    _record(hired, annual, date(2026, 10, 16), date(2026, 10, 20), leave_actor)  # Fri .. Tue across Mon 19
    t = _timeline()
    assert t is not None
    assert t.days[5].off is True
    assert t.away_counts[5] is None
    assert t.away_counts[2] == 1 and t.away_counts[6] == 1


def test_timeline_skips_people_who_left(hired: Employee, annual: LeaveTypeRow, leave_actor: User) -> None:
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    left = [replace(r, state="left") for r in _rows()]
    t = today.away_timeline(_user("HR", "tl2"), left, TODAY)
    assert t is not None
    assert t.lines == []
    assert t.away_counts[:3] == [0, 0, 0]


def test_timeline_lines_sort_by_first_bar(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User, actor: User, job_values: dict[str, object]
) -> None:
    second = _second_employee(actor, job_values)
    _record(hired, annual, date(2026, 10, 20), date(2026, 10, 21), leave_actor)
    _record(second, annual, date(2026, 10, 14), date(2026, 10, 14), leave_actor)
    t = _timeline()
    assert t is not None
    assert [line.row.employee.pk for line in t.lines] == [second.pk, hired.pk]


@pytest.fixture
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """The Today page reads timezone.localdate(); freeze it so the fixed leave dates sit in the window."""
    monkeypatch.setattr(timezone, "localdate", lambda *a, **k: TODAY)
    return TODAY


def _timeline_section(body: str) -> str:
    start = body.index("data-timeline")
    return body[start : body.index("</section>", start)]


def test_today_page_shows_the_timeline_card(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    assign = records.record(
        Draft(hired, annual, date(2026, 10, 13), date(2026, 10, 16)), leave_actor, date(2026, 10, 1)
    )
    login_as(client, "HR")
    body = client.get(reverse("employees:today")).content.decode()
    assert "data-timeline" in body
    assert "Ойрын 14 хоногт юу болох вэ" in body
    assert f'data-leave-bar="{assign.pk}"' in body
    assert "Бүтэн хуанли" in body


def test_timeline_card_empty_state(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "HR")
    body = client.get(reverse("employees:today")).content.decode()
    assert "data-timeline" in body
    assert "Дараагийн 14 хоногт товлогдсон зүйл алга" in body
    assert "data-leave-bar" not in body


def test_timeline_card_without_the_leave_right_has_no_leave_bars(
    client: Client, hired: Employee, frozen_today: date
) -> None:
    login_as(client, "Employee", "emp_view")
    response = client.get(reverse("employees:today"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "data-timeline" in body  # the card is for every signed-in user now
    assert "data-leave-bar" not in body
    assert "data-away-count" not in body


def test_timeline_bar_opens_the_leave_pop_up_only_with_the_record_right(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    assign = records.record(
        Draft(hired, annual, date(2026, 10, 13), date(2026, 10, 16)), leave_actor, date(2026, 10, 1)
    )
    login_as(client, "HR")
    section = _timeline_section(client.get(reverse("employees:today")).content.decode())
    tag = re.search(rf'<[^<>]*data-leave-bar="{assign.pk}"[^<>]*>', section)
    assert tag is not None
    assert f'hx-get="{reverse("leave:edit", args=[assign.pk])}"' in tag.group(0)
    client.logout()

    login_as(client, "Accountant", "acc_view")  # view_leave without record_leave
    section = _timeline_section(client.get(reverse("employees:today")).content.decode())
    assert f'data-leave-bar="{assign.pk}"' in section
    assert "hx-get=" not in section


def test_timeline_card_query_count_does_not_grow_with_people(
    hired: Employee,
    annual: LeaveTypeRow,
    leave_actor: User,
    actor: User,
    job_values: dict[str, object],
) -> None:
    """Measured on away_timeline itself: the rest of the Today page already queries per employee,
    so a page-level count would not isolate the timeline."""
    hr = _user("HR", "tlq")
    assert today.away_timeline(hr, _rows(), TODAY) is not None  # warm the user's permission cache

    def timeline_queries() -> int:
        rows = _rows()  # built outside the capture: employee_rows is the page's own query, not the timeline's
        with CaptureQueriesContext(connection) as ctx:
            assert today.away_timeline(hr, rows, TODAY) is not None
        return len(ctx.captured_queries)

    records.record(Draft(hired, annual, date(2026, 10, 14), date(2026, 10, 15)), leave_actor, date(2026, 10, 1))
    one = timeline_queries()
    second = _second_employee(actor, job_values)
    records.record(Draft(second, annual, date(2026, 10, 14), date(2026, 10, 16)), leave_actor, date(2026, 10, 1))
    assert timeline_queries() == one


@pytest.fixture
def other(db: None) -> LeaveTypeRow:
    return leave_writes.save_leave_type(
        "Бусад чөлөө", {"is_paid": True, "uses_annual_balance": False, "is_active": True, "order": 2}
    )


def _hr_card(client: Client) -> str:
    login_as(client, "HR")
    return _timeline_section(client.get(reverse("employees:today")).content.decode())


def _bar_tag(section: str, leave_id: int) -> str:
    found = re.search(rf'<[^<>]*data-leave-bar="{leave_id}"[^<>]*>', section)
    assert found is not None
    return found.group(0)


def test_today_column_is_marked_once_on_the_header_of_today(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    records.record(Draft(hired, annual, date(2026, 10, 13), date(2026, 10, 14)), leave_actor, date(2026, 10, 1))
    section = _hr_card(client)
    assert section.count("data-today-col") == 1
    header = re.search(r"<div [^<>]*data-today-col>\s*<span [^<>]*>(\d+)</span>", section)
    assert header is not None
    assert header.group(1) == str(TODAY.day)


def test_away_count_cells_show_counts_blank_off_days_and_amber_from_two(
    client: Client,
    hired: Employee,
    annual: LeaveTypeRow,
    leave_actor: User,
    actor: User,
    job_values: dict[str, object],
    frozen_today: date,
) -> None:
    second = _second_employee(actor, job_values)
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 15), leave_actor)
    _record(second, annual, date(2026, 10, 15), date(2026, 10, 16), leave_actor)
    cells = re.findall(r'<div data-away-count class="([^"]*)" style="[^"]*">([^<]*)</div>', _hr_card(client))
    assert [text for _, text in cells] == ["1", "2", "1", "", "", "0", "0", "0", "0", "0", "", "", "0", "0"]
    assert [i for i, (cls, _) in enumerate(cells) if "bg-amber-100" in cls] == [1]
    assert "bg-violet-50" in cells[0][0]  # today's column is tinted


def test_leave_cut_at_the_window_edge_is_squared(
    client: Client,
    hired: Employee,
    annual: LeaveTypeRow,
    leave_actor: User,
    actor: User,
    job_values: dict[str, object],
    frozen_today: date,
) -> None:
    left = records.record(Draft(hired, annual, date(2026, 10, 13), date(2026, 10, 16)), leave_actor, date(2026, 10, 1))
    second = _second_employee(actor, job_values)
    right = records.record(
        Draft(second, annual, date(2026, 10, 20), date(2026, 10, 30)), leave_actor, date(2026, 10, 1)
    )
    section = _hr_card(client)
    left_tag = _bar_tag(section, left.pk)
    assert "rounded-l-none" in left_tag and "rounded-r-none" not in left_tag
    right_tag = _bar_tag(section, right.pk)
    assert "rounded-r-none" in right_tag and "rounded-l-none" not in right_tag


def test_annual_bar_is_violet_and_other_leave_amber(
    client: Client,
    hired: Employee,
    annual: LeaveTypeRow,
    other: LeaveTypeRow,
    leave_actor: User,
    actor: User,
    job_values: dict[str, object],
    frozen_today: date,
) -> None:
    second = _second_employee(actor, job_values)
    a = records.record(Draft(hired, annual, date(2026, 10, 14), date(2026, 10, 15)), leave_actor, date(2026, 10, 1))
    b = _old_leave(second, other, date(2026, 10, 16), date(2026, 10, 16))
    section = _hr_card(client)
    annual_tag = _bar_tag(section, a.pk)
    assert "bg-violet-200" in annual_tag and "bg-amber-200" not in annual_tag
    other_tag = _bar_tag(section, b.pk)
    assert "bg-amber-200" in other_tag and "bg-violet-200" not in other_tag


def _timeline_as(role: str, name: str) -> today.Timeline:
    return today.away_timeline(_user(role, name), _rows(), TODAY)


def _markers_of(t: today.Timeline, employee: Employee) -> list[today.Marker]:
    return [m for line in t.lines if line.row.employee.pk == employee.pk for m in line.markers]


def _kinds(t: today.Timeline, employee: Employee) -> list[tuple[int, str]]:
    """(column, kind of the first item) for each marker of this employee."""
    return [(m.column, m.items[0].kind) for m in _markers_of(t, employee)]


def _day(n: int) -> date:
    return TODAY + timedelta(days=n)


def test_marker_for_a_signed_transfer_in_the_window(hired: Employee, actor: User) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    record_signed(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    (marker,) = _markers_of(_timeline(), hired)
    assert marker.column == 4
    assert marker.waiting is False
    (item,) = marker.items
    assert (item.kind, item.label, item.on, item.waiting) == ("transfer", "Шилжүүлэх", _day(3), False)


def test_window_edges_for_events(hired: Employee, actor: User) -> None:
    for delta in (-1, 0, 13, 14):  # ascending: a later record must not precede an earlier one
        events.record(
            hired, type="contract", effective=_day(delta), changes={"contract_no": f"CN{delta}"},
            salary=None, reason="", note="", by=actor,
        )  # fmt: skip
    assert [(m.column, m.items[0].on) for m in _markers_of(_timeline(), hired)] == [(1, _day(0)), (14, _day(13))]


@pytest.mark.parametrize(("delta", "column"), [(-1, None), (0, 1), (13, 14), (14, None)])
def test_window_edges_for_birthdays(hired: Employee, delta: int, column: int | None) -> None:
    hired.birth_date = _day(delta).replace(year=1990)
    hired.save()
    assert [m.column for m in _markers_of(_timeline(), hired)] == ([] if column is None else [column])


@pytest.mark.parametrize(("delta", "column"), [(-1, None), (0, 1), (13, 14), (14, None)])
def test_window_edges_for_contract_end(hired: Employee, delta: int, column: int | None) -> None:
    job = hired.job_records.get()
    job.contract_end = _day(delta)
    job.save()
    t = _timeline()
    assert [m.column for m in _markers_of(t, hired)] == ([] if column is None else [column])
    if column is not None:
        assert _markers_of(t, hired)[0].items[0].label == "Гэрээ дуусах"


def test_waiting_change_is_a_dashed_marker(hired: Employee, actor: User) -> None:
    events.record(
        hired, type="termination", effective=_day(5), changes={}, salary=None, reason="",
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    (marker,) = _markers_of(_timeline(), hired)
    assert (marker.column, marker.waiting, marker.items[0].kind, marker.items[0].waiting) == (
        6,
        True,
        "termination",
        True,
    )


def test_overdue_waiting_change_is_not_on_the_card(hired: Employee, actor: User) -> None:
    events.record(
        hired, type="termination", effective=_day(-1), changes={}, salary=None, reason="",
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    assert _markers_of(_timeline(), hired) == []


def test_merged_marker_is_solid_unless_every_item_is_waiting(hired: Employee, actor: User) -> None:
    events.record(
        hired, type="termination", effective=_day(3), changes={}, salary=None, reason="",
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    events.record(
        hired, type="contract", effective=_day(3), changes={"contract_no": "CN3"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    (marker,) = _markers_of(_timeline(), hired)
    assert [(i.kind, i.waiting) for i in marker.items] == [("termination", True), ("contract", False)]
    assert marker.waiting is False


def test_merged_marker_is_dashed_when_every_item_is_waiting(hired: Employee, actor: User) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    events.record(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    events.record(
        hired, type="termination", effective=_day(3), changes={}, salary=None, reason="",
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    (marker,) = _markers_of(_timeline(), hired)
    assert len(marker.items) == 2
    assert marker.waiting is True


def test_salary_marker_needs_the_salary_right(hired: Employee, actor: User) -> None:
    events.record(
        hired, type="salary_change", effective=_day(2), changes={}, salary=Decimal("3000000"),
        reason="", note="", by=actor,
    )  # fmt: skip
    assert _kinds(_timeline_as("HR", "sal_hr"), hired) == []
    assert _kinds(_timeline_as("Accountant", "sal_acc"), hired) == [(3, "salary")]


def test_birthday_marker_needs_the_personal_right(hired: Employee) -> None:
    hired.birth_date = _day(2).replace(year=1990)
    hired.save()
    assert _kinds(_timeline_as("Accountant", "bd_acc"), hired) == []
    assert _kinds(_timeline_as("HR", "bd_hr"), hired) == [(3, "birthday")]


def _long_leave_with_contract_and_probation(hired: Employee, actor: User) -> None:
    events.record(
        hired, type="leave_start", effective=_day(-3), changes={}, salary=None, reason="unpaid",
        note="", by=actor, expected_return=_day(6),
    )  # fmt: skip
    set_ext(hired, probation_end=_day(4))
    job = history.job_on(hired, TODAY)
    assert job is not None
    job.contract_end = _day(2)
    job.save()


def test_contract_probation_and_return_markers_need_hr_dates_right(hired: Employee, actor: User) -> None:
    _long_leave_with_contract_and_probation(hired, actor)
    assert _kinds(_timeline_as("HR", "gate_hr"), hired) == [(3, "contract"), (5, "probation"), (7, "leave_return")]
    assert _kinds(_timeline_as("Employee", "gate_emp"), hired) == []


def test_leave_start_marker_in_the_window(hired: Employee, actor: User) -> None:
    events.record(
        hired, type="leave_start", effective=_day(5), changes={}, salary=None, reason="unpaid",
        note="", by=actor, expected_return=_day(12),
    )  # fmt: skip
    assert _kinds(_timeline(), hired) == [(6, "leave_start")]


def test_termination_marker_in_the_window(hired: Employee, actor: User) -> None:
    record_signed(
        hired, type="termination", effective=_day(5), changes={}, salary=None, reason="",
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    (marker,) = _markers_of(_timeline(), hired)
    assert (marker.column, marker.items[0].kind, marker.waiting) == (6, "termination", False)


def test_anniversary_marker_names_the_years(hired: Employee) -> None:
    hired.first_hire_date = date(2023, 10, 16)
    hired.save()
    (marker,) = _markers_of(_timeline(), hired)
    assert (marker.column, marker.items[0].kind, marker.items[0].label) == (
        3,
        "anniversary",
        "Ажилд орсны 3 жилийн ой",
    )


def test_29_feb_birthday_shows_on_28_feb_in_a_common_year(hired: Employee) -> None:
    hired.birth_date = date(1992, 2, 29)
    hired.save()
    t = today.away_timeline(_user("HR", "leap_hr"), _rows(), date(2027, 2, 20))
    (marker,) = _markers_of(t, hired)
    assert (marker.column, marker.items[0].on, marker.items[0].kind) == (9, date(2027, 2, 28), "birthday")


def test_left_employee_with_a_waiting_rehire_still_gets_a_marker(hired: Employee, actor: User) -> None:
    record_signed(
        hired, type="termination", effective=_day(-5), changes={}, salary=None, reason="",
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), note="", by=actor,
    )  # fmt: skip
    events.record(hired, type="rehire", effective=_day(4), changes={}, salary=None, reason="", note="", by=actor)
    t = _timeline()
    assert t.lines[0].row.state == "left"
    (marker,) = _markers_of(t, hired)
    assert (marker.column, marker.items[0].kind, marker.items[0].waiting) == (5, "transfer", True)


def test_holiday_name_is_on_the_day(hired: Employee) -> None:
    LegalHoliday.objects.create(
        name="Тестийн баяр", start_date=date(2026, 10, 19), end_date=date(2026, 10, 19), hdays=1
    )
    t = _timeline()
    assert t.days[5].holiday == "Тестийн баяр"
    assert t.days[0].holiday == ""


def test_lines_sort_by_first_column_then_name(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User, actor: User, job_values: dict[str, object]
) -> None:
    second = _second_employee(actor, job_values)
    _record(second, annual, _day(2), _day(3), leave_actor)  # bar from column 3
    dept = macs_writes.save_department("Бусад хэлтэс")
    record_signed(
        hired, type="transfer", effective=_day(6), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    assert [line.row.employee.pk for line in _timeline().lines] == [second.pk, hired.pk]


def test_lines_with_the_same_first_column_sort_by_name(
    hired: Employee, actor: User, job_values: dict[str, object]
) -> None:
    second = _second_employee(actor, job_values)  # "Батын Бат" sorts before "Батын Сараа"
    hired.birth_date = _day(2).replace(year=1990)
    hired.save()
    second.birth_date = _day(2).replace(year=1991)
    second.save()
    assert [line.row.employee.pk for line in _timeline().lines] == [second.pk, hired.pk]


def _marker_tag(section: str, kind: str) -> str:
    found = re.search(rf'<[^<>]*data-marker="{kind}"[^<>]*>', section)
    assert found is not None
    return found.group(0)


def _marker_html(section: str, kind: str) -> str:
    found = re.search(rf'<a [^<>]*data-marker="{kind}".*?</a>', section, re.S)
    assert found is not None
    return found.group(0)


def test_card_shows_for_a_user_without_the_leave_right(client: Client, frozen_today: date) -> None:
    login_as(client, "Employee", "emp_empty")
    section = _timeline_section(client.get(reverse("employees:today")).content.decode())
    assert "Ойрын 14 хоногт юу болох вэ" in section
    assert "Дараагийн 14 хоногт товлогдсон зүйл алга" in section


def test_card_has_no_leave_parts_without_the_leave_right_but_shows_markers(
    client: Client, hired: Employee, actor: User, frozen_today: date
) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    record_signed(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    own = login_as(client, "Employee", "emp_own")
    link_login(hired, own)
    section = _timeline_section(client.get(reverse("employees:today")).content.decode())
    assert 'data-marker="transfer"' in section
    assert "data-leave-bar" not in section
    assert "data-away-count" not in section
    assert "Бүтэн хуанли" not in section
    assert "Ээлжийн" not in section


def test_marker_renders_with_kind_hover_and_link(
    client: Client, hired: Employee, actor: User, frozen_today: date
) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    record_signed(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    tag = _marker_tag(_hr_card(client), "transfer")
    assert f'href="{reverse("employees:detail", args=[hired.pk])}"' in tag
    assert "Шилжүүлэх: 2026-10-17" in tag
    assert "data-marker-waiting" not in tag


def test_waiting_marker_is_dashed(client: Client, hired: Employee, actor: User, frozen_today: date) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    events.record(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    section = _hr_card(client)
    assert "data-marker-waiting" in _marker_tag(section, "transfer")
    assert "data-legend-waiting" in section


def test_signed_only_card_has_no_waiting_legend_note(
    client: Client, hired: Employee, actor: User, frozen_today: date
) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    record_signed(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    section = _hr_card(client)
    assert "data-marker-waiting" not in section
    assert "data-legend-waiting" not in section


def test_merged_marker_shows_how_many_more_items_it_holds(
    client: Client, hired: Employee, actor: User, frozen_today: date
) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    events.record(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    events.record(
        hired, type="contract", effective=_day(3), changes={"contract_no": "CN3"},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    html_marker = _marker_html(_hr_card(client), "transfer")  # the first item: transfer ranks above contract
    assert "+1" in html_marker
    assert "data-marker-waiting" not in html_marker  # one item is applied: solid


def test_marker_is_above_the_leave_bar(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, actor: User, frozen_today: date
) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    assign = records.record(Draft(hired, annual, TODAY, date(2026, 10, 16)), leave_actor, date(2026, 10, 1))
    record_signed(
        hired, type="transfer", effective=TODAY, changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    section = _hr_card(client)
    assert "z-20" in _marker_tag(section, "transfer")
    bar = _bar_tag(section, assign.pk)
    assert "z-10" in bar and "z-20" not in bar


def test_holiday_column_has_the_holiday_name(client: Client, hired: Employee, actor: User, frozen_today: date) -> None:
    LegalHoliday.objects.create(
        name="Тестийн баяр", start_date=date(2026, 10, 19), end_date=date(2026, 10, 19), hdays=1
    )
    dept = macs_writes.save_department("Бусад хэлтэс")
    record_signed(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    assert 'title="Тестийн баяр"' in _hr_card(client)


def test_legend_lists_the_marker_kinds_shown(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, actor: User, frozen_today: date
) -> None:
    dept = macs_writes.save_department("Бусад хэлтэс")
    _record(hired, annual, TODAY, TODAY, leave_actor)
    record_signed(
        hired, type="transfer", effective=_day(3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip
    section = _hr_card(client)
    assert "Шилжилт, албан тушаал" in section
    assert "Цалингийн өөрчлөлт" not in section  # no salary change in the window
    assert "Ээлжийн" in section
    assert "Бүтэн хуанли" in section
