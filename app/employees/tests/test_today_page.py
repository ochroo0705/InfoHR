# ruff: noqa: F811  (the reused fixtures are imported, then named as test arguments)
"""The assembled Today page: block order, rights and scope of each block, names only after a click, query count."""

import re
from datetime import date, timedelta
from decimal import Decimal

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from lists.models import DEATH, MeaningfulEntry
from macs.models import Branch, ContactRow, ContactType, FiredReason, LeaveTypeRow

from employees import access, attention, views
from employees import today as today_facts
from employees.listing import employee_rows
from employees.models import Employee
from employees.services import history, macs_writes

from .conftest import hire_values, link_login, named, set_account, set_ext
from .helpers import record_signed
from .test_today import (  # noqa: F401
    TODAY,
    _record,
    annual,
    frozen_today,
    leave_actor,
)
from .test_views import login_as

pytestmark = pytest.mark.django_db

MARKERS = ("data-tile", "data-attention-group", "data-away-strip", "data-upcoming", "data-today-company")


def _page(client: Client) -> str:
    response = client.get(reverse("employees:today"))
    assert response.status_code == 200
    return response.content.decode()


def _scheduled_transfer(employee: Employee, actor: User) -> None:
    """A signed transfer three days ahead: the attention box shows it as a «scheduled» group."""
    dept = macs_writes.save_department("Бусад хэлтэс")
    record_signed(
        employee, type="transfer", effective=TODAY + timedelta(days=3), changes={"department": dept},
        salary=None, reason="", note="", by=actor,
    )  # fmt: skip


def _viewer_without_leave_right() -> User:
    """Sees every employee (macs.view_employees) but has no leave.view_leave."""
    user = User.objects.create_user("no_leave_page", password="x-long-pass-123")  # noqa: S106
    user.user_permissions.add(Permission.objects.get(codename="view_employees"))
    return User.objects.get(pk=user.pk)


def test_page_order_tiles_attention_away_upcoming_summary(
    client: Client, hired: Employee, actor: User, frozen_today: date
) -> None:
    _scheduled_transfer(hired, actor)
    login_as(client, "HR")
    body = _page(client)
    positions = [body.find(marker) for marker in MARKERS]
    assert all(p >= 0 for p in positions), dict(zip(MARKERS, positions, strict=True))
    assert positions == sorted(positions)


def test_scheduled_change_stays_visible_in_the_attention_box(
    client: Client, hired: Employee, actor: User, frozen_today: date
) -> None:
    """The per-person timeline is gone; a scheduled transfer in the next days must still show on the page."""
    _scheduled_transfer(hired, actor)
    login_as(client, "HR")
    assert 'data-attention-group data-kind="scheduled"' in _page(client)


def test_company_block_hidden_for_a_user_without_view_employees(
    client: Client, hired: Employee, frozen_today: date
) -> None:
    own = login_as(client, "Employee", "emp_page")
    link_login(hired, own)
    response = client.get(reverse("employees:today"))
    body = response.content.decode()
    assert response.context["company"] is None
    assert "data-company" not in body
    assert "Компанийн байдал" not in body


def test_company_block_shows_headings_hint_and_month_numbers(
    client: Client, hired: Employee, frozen_today: date
) -> None:
    login_as(client, "HR")
    body = client.get(reverse("employees:company")).content.decode()
    section = body[body.index("data-company") :]
    assert "Компанийн байдал" in section
    assert "Сарын эргэлт = гарсан ÷ сарын дундаж ажилтны тоо" in section
    assert "Энэ сард орсон 0" in section
    assert "Гарсан 0" in section
    assert "Таны харах ажилтнууд" not in section  # HR sees the whole company


def test_company_block_is_labelled_for_a_limited_scope_user(
    client: Client, hired: Employee, actor: User, job_values: dict[str, object], frozen_today: date
) -> None:
    second = history.hire(
        hire_values("УБ99112234") | {"given_name": "Бат"}, {}, start=date(2026, 1, 5), job=job_values,
        salary=Decimal("2500000"), by=actor,
    )  # fmt: skip
    north, south = Branch.objects.create(name="Хойд"), Branch.objects.create(name="Өмнөд")
    Employee.objects.filter(pk=hired.pk).update(branch_id=north.pk)
    Employee.objects.filter(pk=second.pk).update(branch_id=south.pk)
    hr = login_as(client, "HR", "hr_scoped_page")
    AccessScope.objects.update_or_create(user=hr, defaults={"limited": True, "branch_ids": [north.pk]})
    response = client.get(reverse("employees:company"))
    body = response.content.decode()
    company = response.context["company"]
    assert company is not None and company.partial_scope
    assert company.headcount[-1].value == 1  # only the person inside the scope
    section = body[body.index("data-company") :]
    assert "Таны харах ажилтнууд" in section


def test_away_block_omitted_without_the_leave_right(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    _record(hired, annual, TODAY, TODAY + timedelta(days=2), leave_actor)
    client.force_login(_viewer_without_leave_right())
    body = _page(client)
    assert "data-away-strip" not in body
    assert reverse("employees:today_away") not in body
    assert "data-today-company" in body  # the employee-list right still gets the Today summary line
    client.logout()
    login_as(client, "HR", "hr_leave_page")
    assert "data-away-strip" in _page(client)


def test_away_strip_cells_are_shaded_ringed_and_clickable_on_working_days(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    _record(hired, annual, TODAY, TODAY + timedelta(days=1), leave_actor)
    login_as(client, "HR")
    body = _page(client)
    strip = body[body.index("data-away-strip") : body.index("data-upcoming")]
    day_url = reverse("employees:today_away")
    assert f'hx-get="{day_url}?day={TODAY:%Y-%m-%d}"' in strip
    assert f"?day={date(2026, 10, 17):%Y-%m-%d}" not in strip  # Saturday: off, not clickable
    assert strip.count('hx-target="#away-names"') == 10  # the 10 working days of the window
    assert "bg-sky-600" in strip  # 1 of 1 person away today = 100 % of headcount
    assert "bg-slate-100" in strip
    assert "data-today" in strip
    assert f"Өнөөдөр: {annual.name} 1" in strip


def test_page_has_no_person_names_for_away_or_birthdays_until_clicked(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    Employee.objects.filter(pk=hired.pk).update(birth_date=date(1990, 10, 20), first_hire_date=date(2023, 10, 31))
    _record(hired, annual, TODAY, TODAY + timedelta(days=2), leave_actor)
    login_as(client, "HR")
    body = _page(client)
    name = hired.full_name
    assert name not in body[: body.index('id="attention"')]  # tiles
    assert name not in body[body.index("data-away-strip") :]  # away, upcoming and company blocks
    assert "Төрсөн өдөр 1" in body
    assert "Ажилласан жилийн ой 1" in body
    away = client.get(f"{reverse('employees:today_away')}?day={TODAY:%Y-%m-%d}").content.decode()
    birthdays = client.get(f"{reverse('employees:today_upcoming')}?kind=birthday").content.decode()
    anniversaries = client.get(f"{reverse('employees:today_upcoming')}?kind=anniversary").content.decode()
    assert name in away and name in birthdays and name in anniversaries


def test_upcoming_lines_load_their_names_into_their_own_container(
    client: Client, hired: Employee, frozen_today: date
) -> None:
    login_as(client, "HR")
    body = _page(client)
    url = reverse("employees:today_upcoming")
    assert f'hx-get="{url}?kind=birthday"' in body
    assert f'hx-get="{url}?kind=anniversary"' in body
    assert 'hx-target="#upcoming-birthday"' in body and 'id="upcoming-birthday"' in body
    assert 'hx-target="#upcoming-anniversary"' in body and 'id="upcoming-anniversary"' in body


def test_count_lines_render_collapsed_with_aria_expanded(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "HR")
    body = _page(client)
    url = reverse("employees:today_upcoming")
    for kind in ("birthday", "anniversary"):
        assert re.search(rf'<button[^>]*hx-get="{url}\?kind={kind}"[^>]*aria-expanded="false"', body)


def test_count_lines_control_their_own_container(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "HR")
    body = _page(client)
    for kind in ("birthday", "anniversary"):
        target = f"upcoming-{kind}"
        assert re.search(rf'<button[^>]*aria-controls="{target}"', body)
        assert f'id="{target}"' in body


def _hire_many(n: int, start: int, actor: User, job_values: dict[str, object]) -> list[Employee]:
    return [
        history.hire(
            hire_values(f"УБ{80000000 + start + i}")
            | {"given_name": f"Ажилтан{start + i}", "birth_date": date(1990, 10, 15 + i % 10)},
            {},
            start=date(2024, 3, 1),
            job=job_values,
            salary=Decimal("2500000"),
            by=actor,
        )  # fmt: skip
        for i in range(n)
    ]


def test_page_query_count_is_flat_in_staff_count(
    client: Client,
    annual: LeaveTypeRow,
    leave_actor: User,
    actor: User,
    job_values: dict[str, object],
    frozen_today: date,
) -> None:
    login_as(client, "HR", "hr_scale_page")
    first = _hire_many(5, 0, actor, job_values)
    _record(first[0], annual, TODAY, TODAY + timedelta(days=1), leave_actor)
    _page(client)  # warm the per-user caches

    def page_queries() -> int:
        with CaptureQueriesContext(connection) as ctx:
            _page(client)
        return len(ctx.captured_queries)

    five = page_queries()
    more = _hire_many(25, 5, actor, job_values)
    _record(more[0], annual, TODAY, TODAY + timedelta(days=2), leave_actor)
    thirty = page_queries()
    assert thirty == five, f"page queries: 5 people {five}, 30 people {thirty}"


def test_birthday_line_hidden_without_the_personal_right(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "Accountant", "acc_no_personal")  # view_employees and view_leave, no view_personal
    body = _page(client)
    assert "?kind=birthday" not in body
    assert "Төрсөн өдөр" not in body
    assert "Ажилласан жилийн ой 0" in body
    client.logout()
    login_as(client, "HR", "hr_personal")
    assert "Төрсөн өдөр 0" in _page(client)


def test_off_day_says_today_is_a_day_off(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    saturday = date(2026, 10, 17)
    _record(hired, annual, date(2026, 10, 16), date(2026, 10, 19), leave_actor)
    monkeypatch.setattr(timezone, "localdate", lambda *a, **k: saturday)
    login_as(client, "HR")
    body = _page(client)
    strip = body[body.index("data-away-strip") : body.index("data-upcoming")]
    assert "Өнөөдөр амралтын өдөр" in strip
    assert "Өнөөдөр чөлөөтэй хүн алга." not in strip


def test_away_names_panel_names_its_day(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    _record(hired, annual, TODAY, TODAY + timedelta(days=2), leave_actor)
    login_as(client, "HR")
    day = TODAY + timedelta(days=1)
    body = client.get(f"{reverse('employees:today_away')}?day={day:%Y-%m-%d}").content.decode()
    assert body.index(f"{day:%Y-%m-%d}") < body.index(hired.full_name)
    assert re.search(rf"<h3[^>]*data-away-day[^>]*>{day:%Y-%m-%d}</h3>", body)


_WORK = today_facts.TimelineDay(TODAY, off=False, is_today=True)
_OFF = today_facts.TimelineDay(TODAY, off=True, is_today=False)


@pytest.mark.parametrize(
    ("day", "count", "shade"),
    [
        (_WORK, 0, "bg-sky-50"),
        (_WORK, 1, "bg-sky-200"),
        (_WORK, 4, "bg-sky-200"),
        (_WORK, 5, "bg-sky-400"),  # exactly 5 % of 100
        (_WORK, 9, "bg-sky-400"),
        (_WORK, 10, "bg-sky-600"),  # exactly 10 % of 100
        (_OFF, None, "bg-slate-100"),
    ],
)
def test_away_cells_shade_thresholds(day: today_facts.TimelineDay, count: int | None, shade: str) -> None:
    strip = today_facts.AwayStrip(days=[day], counts=[count], today_split=[], show_leave=True)
    (cell,) = views.away_cells(strip, 100)
    assert cell.shade.split()[0] == shade
    assert cell.count == count


def _query_count(client: Client, url: str) -> int:
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == 200, url
    return len(ctx.captured_queries)


def _first_group_url(user: User) -> str:
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), TODAY)
    shown, _ = attention.split(user, attention.items(user, rows, TODAY))
    groups = attention.group(shown)
    assert groups, "the test needs at least one attention group"
    return f"{reverse('employees:attention_more')}?kind={groups[0].kind}&urgency={groups[0].urgency}"


def test_fragment_query_counts_are_flat_in_staff_count_without_the_personal_right(
    client: Client,
    actor: User,
    job_values: dict[str, object],
    frozen_today: date,
) -> None:
    accountant = login_as(client, "Accountant", "acc_scale")  # view_employees, no view_personal
    _hire_many(5, 0, actor, job_values)
    more_url = _first_group_url(accountant)
    birthday_url = f"{reverse('employees:today_upcoming')}?kind=birthday"
    urls = (more_url, birthday_url)
    for url in urls:
        client.get(url)  # warm the per-user caches
    five = [_query_count(client, url) for url in urls]
    _hire_many(25, 5, actor, job_values)
    thirty = [_query_count(client, url) for url in urls]
    assert thirty == five, f"queries (attention_more, today_upcoming): 5 people {five}, 30 people {thirty}"


def _person(given: str, register_no: str, actor: User, job_values: dict[str, object]) -> Employee:
    return history.hire(
        hire_values(register_no) | {"given_name": given},
        {}, start=date(2024, 3, 1), job=job_values, salary=Decimal("2500000"), by=actor,
    )  # fmt: skip


def _tidy(employee: Employee) -> None:
    """Nothing to fix on this person, so the page shows only what a test sets on purpose."""
    MeaningfulEntry.objects.get_or_create(key=DEATH, defaults={"value": named(FiredReason, "Нас барсан").pk})
    set_ext(employee, setup_required=False)
    ContactRow.objects.create(
        employee=employee, contact_type=named(ContactType, "Утас"), name="А", relative="Ах", value="99"
    )
    set_account(employee, "123")
    employee.hr_orders.update(state="registered")


def test_page_splits_queue(
    client: Client, hired: Employee, actor: User, job_values: dict[str, object], frozen_today: date
) -> None:
    _tidy(hired)
    hired.job_records.update(contract_end=TODAY - timedelta(days=10))  # overdue: urgent
    probation = _person("Наран", "УБ99112234", actor, job_values)
    _tidy(probation)
    set_ext(probation, probation_end=TODAY + timedelta(days=3))  # due soon
    gap = _person("Болд", "УБ99112235", actor, job_values)
    _tidy(gap)
    set_account(gap, "")  # missing bank record: a gap
    login_as(client, "Accountant")
    response = client.get(reverse("employees:today"))
    assert response.status_code == 200
    assert response.context["urgent_count"] == 1
    assert response.context["soon_count"] == 1
    assert response.context["gap_count"] == 1  # only the person without a bank account
    assert response.content.decode().count("Өгөгдөл дутуу") == 1


def test_gap_groups_hidden_rows_by_default(
    client: Client, hired: Employee, actor: User, job_values: dict[str, object], frozen_today: date
) -> None:
    _tidy(hired)
    hired.job_records.update(contract_end=TODAY - timedelta(days=10))
    gap = _person("Болд", "УБ99112235", actor, job_values)
    _tidy(gap)
    set_account(gap, "")
    login_as(client, "Accountant")
    body = _page(client)
    assert gap.full_name not in body  # the gap group is closed and shows counts, not names
    gaps = body[body.index("data-attention-gaps") :]
    assert " open" not in gaps.split(">", 1)[0]


def test_gap_group_names_load_on_request(
    client: Client, hired: Employee, actor: User, job_values: dict[str, object], frozen_today: date
) -> None:
    """Opening a missing-data row loads its people with their fix links (the first page has none of them)."""
    _tidy(hired)
    gap = _person("Болд", "УБ99112235", actor, job_values)
    _tidy(gap)
    set_account(gap, "")
    login_as(client, "Accountant")
    assert gap.full_name not in _page(client)
    url = f"{reverse('employees:attention_more')}?kind=bank&urgency={attention.MISSING}&all=1"
    response = client.get(url)
    assert response.status_code == 200
    body = response.content.decode()
    assert gap.full_name in body
    assert f'href="{reverse("employees:detail", args=[gap.pk])}#salary"' in body


def test_gap_row_is_a_lazy_loader_for_its_group(
    client: Client, hired: Employee, actor: User, job_values: dict[str, object], frozen_today: date
) -> None:
    _tidy(hired)
    gap = _person("Болд", "УБ99112235", actor, job_values)
    _tidy(gap)
    set_account(gap, "")
    login_as(client, "Accountant")
    body = _page(client)
    assert f'kind=bank&urgency={attention.MISSING}&all=1" hx-trigger="toggle once"' in body
    assert 'hx-target="find [data-gap-people]"' in body
    details = body[body.index('hx-trigger="toggle once"') :]
    details = details[: details.index("</details>")]
    assert "data-gap-people" in details  # the names load inside the open details, not beside them


def test_gap_row_offers_dismiss_all_only_for_several_items(
    client: Client, hired: Employee, actor: User, job_values: dict[str, object], frozen_today: date
) -> None:
    _tidy(hired)
    gap = _person("Болд", "УБ99112235", actor, job_values)
    _tidy(gap)
    set_account(gap, "")
    login_as(client, "Accountant")
    body = _page(client)
    section = body[body.index("data-attention-gaps") :]
    section = section[: section.index("</ul>")]
    assert "Бүгдийг мэдлээ" not in section  # one person: no group dismiss
    other = _person("Наран", "УБ99112236", actor, job_values)
    _tidy(other)
    set_account(other, "")
    body = _page(client)
    section = body[body.index("data-attention-gaps") :]
    assert "Бүгдийг мэдлээ" in section[: section.index("</ul>")]


def test_shortcuts_follow_rights(client: Client, hired: Employee, frozen_today: date) -> None:
    """HR (manage + record leave) sees the three links; an Accountant (no manage, no record leave) sees none of them."""
    login_as(client, "HR", "hr_shortcuts")
    body = _page(client)
    shortcuts = body[body.index("data-shortcuts") :]
    shortcuts = shortcuts[: shortcuts.index("</div>")]
    assert f'href="{reverse("employees:add")}"' in shortcuts
    assert "Ажилтан нэмэх" in shortcuts
    assert f'href="{reverse("employees:orders")}"' in shortcuts
    assert "Тушаал" in shortcuts
    assert f'hx-get="{reverse("leave:add")}"' in shortcuts  # a modal fragment: never a plain link (it renders unstyled)
    assert "Чөлөө бүртгэх" in shortcuts
    assert "Хайх" in shortcuts and "Ctrl K" in shortcuts and "data-palette-open" in shortcuts
    client.logout()
    login_as(client, "Accountant", "acc_shortcuts")
    body = _page(client)
    shortcuts = body[body.index("data-shortcuts") :]
    shortcuts = shortcuts[: shortcuts.index("</div>")]
    assert "Ажилтан нэмэх" not in shortcuts
    assert "Тушаал" not in shortcuts
    assert "Чөлөө бүртгэх" not in shortcuts
    assert "data-palette-open" in shortcuts  # the search needs no right


def test_attention_tile_counts_urgent_only(
    client: Client, hired: Employee, actor: User, job_values: dict[str, object], frozen_today: date
) -> None:
    _tidy(hired)
    hired.job_records.update(contract_end=TODAY - timedelta(days=10))  # 1 overdue: urgent
    for i in range(5):
        gap = _person(f"Дутуу{i}", f"УБ9911224{i}", actor, job_values)
        _tidy(gap)
        set_account(gap, "")  # 5 missing bank records: gaps, not urgent
    login_as(client, "Accountant")
    body = _page(client)
    assert 'data-tile="attention">1<' in body
    assert "+ 0 удахгүй · 5 дутуу" in body


def _box_summary(body: str) -> str:
    start = body.index('<details id="attention-box"')
    return body[start : body.index("</summary>", start)]


def test_box_header_matches_tile(
    client: Client, hired: Employee, actor: User, job_values: dict[str, object], frozen_today: date
) -> None:
    _tidy(hired)
    hired.job_records.update(contract_end=TODAY - timedelta(days=10))  # 1 overdue
    for given, register_no in (("Наран", "УБ99112234"), ("Төмөр", "УБ99112237")):  # 2 due soon
        person = _person(given, register_no, actor, job_values)
        _tidy(person)
        set_ext(person, probation_end=TODAY + timedelta(days=3))
    for i in range(5):  # 5 missing bank accounts
        person = _person(f"Гэрэл{i}", f"УБ9911224{i}", actor, job_values)
        _tidy(person)
        set_account(person, "")
    login_as(client, "Accountant")
    body = _page(client)
    summary = _box_summary(body)
    assert re.search(r'rounded-full[^"]*">1</span>', summary)  # the header chip is the urgent count
    assert "+ 2 удахгүй · 5 дутуу" in summary
    assert ">8</span>" not in summary  # not the total of all items
    assert re.search(r'data-tile="attention">1<', body)


@pytest.mark.parametrize(("scenario", "tone"), [("urgent", "urgent"), ("soon", "soon"), ("gaps", "calm")])
def test_box_tone_follows_urgency(
    client: Client, hired: Employee, job_values: dict[str, object], frozen_today: date, scenario: str, tone: str
) -> None:
    _tidy(hired)
    if scenario == "urgent":
        hired.job_records.update(contract_end=TODAY - timedelta(days=10))
    elif scenario == "soon":
        set_ext(hired, probation_end=TODAY + timedelta(days=3))
    else:
        set_account(hired, "")
    login_as(client, "Accountant")
    tag = re.search(r'<details id="attention-box"[^>]*>', _page(client))
    assert tag is not None and f'data-tone="{tone}"' in tag.group(0)
