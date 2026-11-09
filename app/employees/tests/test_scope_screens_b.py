"""Screens leak test, part B (spec §7): leave, orders register and print, reports and their exports, activity log,
and two scope modes (nothing ticked, own team). A limited HR user never sees, counts or opens a person outside the
scope. Shares fixtures and helpers with part A (test_scope_screens.py).
"""

# F811: pytest fixtures imported from part A are requested as test parameters, which is how pytest uses them.
# ruff: noqa: F811

import io
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

import openpyxl
import pytest
from accounts import roles
from accounts.models import AccessScope, User
from config import batching
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from leave.services import records
from leave.services.records import Draft
from macs.models import Command, DisciplineRow, DisciplineType, Entitlement, FactoryAccidentRow, LeaveAssign

from employees.models import ActivityEntry, Employee

from .conftest import link_login, named
from .test_scope_screens import (  # noqa: F401 (fixtures and helpers shared with part A)
    IN_FAMILY,
    OUT_FAMILY,
    OUT_GIVEN,
    OUT_ORDER,
    OUT_REGISTER,
    _client,
    _hire,
    _user_in,
    due_soon,
    hr_north,
    leave_type,
    north,
    people,
    root,
    south,
    working_day,
)
from .test_today import frozen_today  # noqa: F401 (the pinned clock, used by working_day)

pytestmark = pytest.mark.django_db

THIRD_FAMILY, THIRD_GIVEN = "Гуравдугаар", "Баатар"  # branch north, reports to the inside person (own-team scope)
FOURTH_FAMILY, FOURTH_GIVEN = "Дөрөвдүгээр", "Сараа"  # branch south, reports to nobody in scope
LEGACY_OUT = "Хуучин гадны тушаал"  # a MACS order row of the outside person
LEGACY_IN = "Хуучин дотны тушаал"  # a MACS order row of the inside person


def _year_period() -> dict[str, str]:
    """The whole current year, so the rows these tests create this year (dated from today's year) fall inside it."""
    year = timezone.localdate().year
    return {"from": f"{year}-01-01", "to": f"{year}-12-31"}


@pytest.fixture
def hr_all(db: None) -> Client:
    """Control: an HR user who is not limited sees everyone, so each screen really would show the outside person."""
    return _client(_user_in(roles.HR, "hr_all_b"))


def _get(client: Client, name: str, url: str, params: dict[str, str] | None = None, htmx: bool = False) -> str:
    headers = {"HX-Request": "true"} if htmx else {}
    response = client.get(url, params or {}, headers=headers)
    assert response.status_code == 200, f"{name} answered {response.status_code}"
    return response.content.decode()


def _xlsx_text(response: Any) -> str:
    assert response.status_code == 200, f"export answered {response.status_code}"
    book = openpyxl.load_workbook(io.BytesIO(response.content))
    cells = (cell for sheet in book.worksheets for row in sheet.iter_rows(values_only=True) for cell in row)
    return " ".join(str(cell) for cell in cells if cell is not None)


def _no_echo(body: str, query: str) -> str:
    """A search box echoes the typed text in its value, and a print link carries it in its address (?q=...).
    That echo is not a person or order shown by the screen. Only the echo is removed: the same text elsewhere stays."""
    body = body.replace(f'value="{query}"', "")
    return re.sub(rf"([?&](?:q|emp)={re.escape(quote_plus(query))})(?=[&\"'])", "", body)


def _weekday_ahead(days: int) -> date:
    day = timezone.localdate() + timedelta(days=days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _leave_on(employee: Employee, leave_type_row: Any, actor: User, day: date) -> None:
    today = timezone.localdate()
    draft = Draft(employee, leave_type_row, day, day)
    assert not records.check(draft, today).errors
    records.record(draft, actor, today)


def _leave_today(employee: Employee, leave_type_row: Any, actor: User) -> None:
    _leave_on(employee, leave_type_row, actor, timezone.localdate())


def _writes_count() -> list[int]:
    """Every row a leave write could add (global counts): unchanged after a refused request."""
    return [LeaveAssign.objects.count(), Entitlement.objects.count(), ActivityEntry.objects.count()]


def _type_code() -> int:
    """The factory_accident_type row every accident row points to (no model for it)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT faccident_type_id FROM factory_accident_type")  # no LIMIT: Firebird has none
        found = cursor.fetchone()
        if found is not None:
            return int(found[0])
        cursor.execute(
            "INSERT INTO factory_accident_type (description) VALUES (%s) RETURNING faccident_type_id", ["Тест"]
        )
        return int(cursor.fetchone()[0])


def _accident(person: Employee) -> None:
    FactoryAccidentRow.objects.create(
        kind="accident",
        type_code=_type_code(),
        employee=person,
        accident_date=date(timezone.localdate().year, 6, 15),
        group_accident=None,
        facc_type=3,
        facc_reason=14,
        facc_result=3,
        name="Осол",
        branch=None,
    )


def _discipline(person: Employee) -> None:
    DisciplineRow.objects.create(
        employee=person,
        from_discipline="Санхүүгийн алба",
        discipline_type=named(DisciplineType, "Сануулга"),
        discipline_date=date(timezone.localdate().year, 2, 10),
        description="Хоцорсон",
        discipline_sal_percent=Decimal("12.50"),
        discipline_enddate=date(timezone.localdate().year, 5, 1),
    )


# --- leave: list, balances, team calendar ---


def test_leave_list_hides_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee], due_soon: None
) -> None:
    inside, outside = people
    url = reverse("leave:list")
    assert OUT_FAMILY in _get(hr_all, "leave list", url)  # control
    body = _get(hr_north, "leave list", url)
    assert IN_FAMILY in body
    assert OUT_FAMILY not in body
    batch = _get(hr_north, "leave list batch", url, htmx=True)
    assert IN_FAMILY in batch and OUT_FAMILY not in batch
    for query in (OUT_FAMILY, OUT_GIVEN):  # a search for the outside person finds nothing
        found = _get(hr_north, "leave search", url, {"q": query})
        assert OUT_FAMILY not in _no_echo(found, query)
    pop_up = {"employee": str(outside.pk)}  # the link from the outside person's page
    assert OUT_FAMILY not in _get(hr_north, "leave link", url, pop_up)
    assert OUT_FAMILY in _get(hr_all, "leave link", url, pop_up)  # control: the link would show the person


def test_leave_list_batch_offset_hides_outside_person(
    hr_north: Client,
    hr_all: Client,
    actor: User,
    people: tuple[Employee, Employee],
    due_soon: None,
    leave_type: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One row per batch. The newest leave is the inside person's, dated ahead, so the outside person's leave of today
    is row two (offset 1) for an unlimited user; a broken scope would show it to the limited user there too."""
    inside, _ = people
    _leave_on(inside, leave_type, actor, _weekday_ahead(10))
    monkeypatch.setattr(batching, "LIST_BATCH", 1)
    url = reverse("leave:list")
    assert OUT_FAMILY in _get(hr_all, "leave list batch 2", url, {"offset": "1"}, htmx=True)  # control
    body = _get(hr_north, "leave list batch 2", url, {"offset": "1"}, htmx=True)
    assert IN_FAMILY in body
    assert OUT_FAMILY not in body


def test_leave_balances_hide_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee], due_soon: None
) -> None:
    url = reverse("leave:balances")
    assert OUT_FAMILY in _get(hr_all, "balances", url)  # control
    body = _get(hr_north, "balances", url)
    assert IN_FAMILY in body
    assert OUT_FAMILY not in body


def test_leave_balances_batch_offset_hides_outside_person(
    hr_north: Client,
    hr_all: Client,
    actor: User,
    north: Any,
    job_values: dict[str, Any],
    people: tuple[Employee, Employee],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One row per batch. Balances are listed by family name, and a person named before the outside one (branch north)
    takes row one, so the outside person is row two (offset 1) for an unlimited user."""
    _hire(actor, job_values, north, "УБ00000088", "Аюушийн", "Бат")
    monkeypatch.setattr(batching, "LIST_BATCH", 1)
    url = reverse("leave:balances")
    assert OUT_FAMILY in _get(hr_all, "balances batch 2", url, {"offset": "1"}, htmx=True)  # control
    body = _get(hr_north, "balances batch 2", url, {"offset": "1"}, htmx=True)
    assert IN_FAMILY in body
    assert OUT_FAMILY not in body


def test_team_calendar_hides_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee], due_soon: None, job_values: dict[str, Any]
) -> None:
    url = reverse("leave:calendar")
    month = {"month": timezone.localdate().strftime("%Y-%m")}
    by_department = {**month, "department": str(job_values["department"].pk)}
    for params in (month, by_department):
        assert OUT_FAMILY in _get(hr_all, "calendar", url, params)  # control
        body = _get(hr_north, "calendar", url, params)
        assert IN_FAMILY in body, params
        assert OUT_FAMILY not in body, params


# --- leave: the add form and its pop-up ---


def test_leave_add_offers_only_visible_people(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee], leave_type: Any
) -> None:
    inside, outside = people
    choices = set(
        hr_north.get(reverse("leave:add")).context["form"].fields["employee"].queryset.values_list("pk", flat=True)
    )
    assert choices == {inside.pk}
    everyone = hr_all.get(reverse("leave:add")).context["form"].fields["employee"].queryset
    assert outside.pk in set(everyone.values_list("pk", flat=True))  # control


def test_leave_add_post_for_outside_person_is_rejected(
    hr_north: Client, people: tuple[Employee, Employee], leave_type: Any
) -> None:
    inside, outside = people
    day = _weekday_ahead(10).isoformat()
    data = {
        "leave_type": str(leave_type.pk),
        "start_date": day,
        "end_date": day,
        "note": "",
        "override_reason": "",
    }
    before = _writes_count()
    response = hr_north.post(reverse("leave:add"), {**data, "employee": str(outside.pk)})
    assert response.status_code == 200  # the form is shown again with an error, not saved (204 = saved)
    assert "employee" in response.context["form"].errors
    assert _writes_count() == before
    # control: the same request for the in-scope person is saved
    saved = hr_north.post(reverse("leave:add"), {**data, "employee": str(inside.pk)})
    assert saved.status_code == 204
    assert LeaveAssign.objects.filter(employee_id=inside.pk, date1=day).exists()


def test_leave_popup_for_outside_person_shows_nothing(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee], leave_type: Any
) -> None:
    inside, outside = people
    url = reverse("leave:add")
    assert OUT_FAMILY in _get(hr_all, "leave pop-up", url, {"employee": str(outside.pk)})  # control
    assert OUT_FAMILY not in _get(hr_north, "leave pop-up", url, {"employee": str(outside.pk)})
    assert IN_FAMILY in _get(hr_north, "leave pop-up", url, {"employee": str(inside.pk)})
    day = _weekday_ahead(10).isoformat()
    check = hr_north.post(
        reverse("leave:check"),
        {"employee": str(outside.pk), "leave_type": str(leave_type.pk), "start_date": day, "end_date": day},
    )
    assert check.content == b""  # the posted person is not in the form's choices: no check is shown


def test_leave_pages_by_outside_pk_are_404_and_write_nothing(
    hr_north: Client, people: tuple[Employee, Employee], due_soon: None
) -> None:
    inside, outside = people
    outside_leave = LeaveAssign.objects.get(employee_id=outside.pk)
    inside_leave = LeaveAssign.objects.get(employee_id=inside.pk)
    routes: list[tuple[str, str, dict[str, Any]]] = [
        ("GET", reverse("leave:edit", args=[outside_leave.pk]), {}),
        ("POST", reverse("leave:edit", args=[outside_leave.pk]), {"note": "Буруу"}),
        ("GET", reverse("leave:cancel", args=[outside_leave.pk]), {}),
        ("POST", reverse("leave:cancel", args=[outside_leave.pk]), {"reason": "Буруу"}),
    ]
    before = _writes_count()
    for method, url, data in routes:
        response = getattr(hr_north, method.lower())(url, data)
        assert response.status_code == 404, f"{method} {url} answered {response.status_code}"
    assert _writes_count() == before
    # control: the same page opens for the in-scope person's leave
    assert hr_north.get(reverse("leave:edit", args=[inside_leave.pk])).status_code == 200


# --- orders register, its search and print ---


def _legacy_orders(people: tuple[Employee, Employee]) -> None:
    inside, outside = people
    Command.objects.create(employee_id=outside.pk, number="А/77", date=date(2025, 2, 2), summary=LEGACY_OUT)
    Command.objects.create(employee_id=inside.pk, number="А/78", date=date(2025, 2, 3), summary=LEGACY_IN)


def test_orders_register_hides_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]
) -> None:
    _legacy_orders(people)
    url = reverse("employees:orders")
    everyone = _get(hr_all, "orders", url)
    assert OUT_FAMILY in everyone and LEGACY_OUT in everyone  # control
    for body in (
        _get(hr_north, "orders", url),
        _get(hr_north, "orders batch", url, {"offset": "0"}, htmx=True),
        _get(hr_north, "orders legacy", url, {"state": "legacy"}),
    ):
        assert IN_FAMILY in body and LEGACY_IN in body
        assert OUT_FAMILY not in body
        assert LEGACY_OUT not in body
        assert OUT_ORDER not in body


@pytest.mark.parametrize("query", [OUT_FAMILY, OUT_GIVEN, OUT_ORDER, "А/77"])
def test_orders_search_finds_no_outside_order(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee], query: str
) -> None:
    _legacy_orders(people)
    url = reverse("employees:orders")
    assert OUT_FAMILY in _get(hr_all, "orders search", url, {"q": query})  # control: the search finds the person
    body = _no_echo(_get(hr_north, "orders search", url, {"q": query}), query)
    assert OUT_FAMILY not in body
    assert LEGACY_OUT not in body
    assert OUT_ORDER not in body


def test_orders_print_hides_outside_person(hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]) -> None:
    _legacy_orders(people)
    url = reverse("employees:orders_print")
    everyone = _get(hr_all, "orders print", url)
    assert OUT_FAMILY in everyone and LEGACY_OUT in everyone  # control
    body = _get(hr_north, "orders print", url)
    assert IN_FAMILY in body and LEGACY_IN in body
    assert OUT_FAMILY not in body
    assert LEGACY_OUT not in body
    assert OUT_ORDER not in body


def test_orders_register_batch_offset_hides_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One row per batch, newest first. A legacy order of the inside person dated today is row one, so the outside
    person's hire order is row two (offset 1) for an unlimited user."""
    inside, _ = people
    Command.objects.create(employee_id=inside.pk, number="А/79", date=timezone.localdate(), summary=LEGACY_IN)
    monkeypatch.setattr(batching, "LIST_BATCH", 1)
    url = reverse("employees:orders")
    assert OUT_FAMILY in _get(hr_all, "orders batch 2", url, {"offset": "1"}, htmx=True)  # control
    body = _get(hr_north, "orders batch 2", url, {"offset": "1"}, htmx=True)
    assert IN_FAMILY in body
    assert OUT_FAMILY not in body
    assert OUT_ORDER not in body


# --- reports: one per family, each on the page, the print page and the Excel file ---


def _report_surfaces(client: Client, key: str, params: dict[str, str]) -> dict[str, str]:
    return {
        "page": _get(client, f"{key} page", reverse("reports:report", args=[key]), params),
        "print": _get(client, f"{key} print", reverse("reports:print", args=[key]), params),
        "excel": _xlsx_text(client.get(reverse("reports:excel", args=[key]), params)),
    }


def _assert_report_scoped(hr_north: Client, hr_all: Client, key: str, params: dict[str, str]) -> None:
    for surface, text in _report_surfaces(hr_all, key, params).items():
        assert OUT_FAMILY in text, f"{key} {surface}: control does not show the outside person"
    for surface, text in _report_surfaces(hr_north, key, params).items():
        assert IN_FAMILY in text, f"{key} {surface}: the inside person is missing"
        assert OUT_FAMILY not in text, f"{key} {surface}: the outside person leaks"


def test_staff_list_report_and_exports_hide_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]
) -> None:
    _assert_report_scoped(hr_north, hr_all, "staff-list", {})


def test_leave_report_and_exports_hide_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee], due_soon: None
) -> None:
    _assert_report_scoped(hr_north, hr_all, "leave-requests", _year_period())


def test_movements_report_and_exports_hide_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]
) -> None:
    _assert_report_scoped(hr_north, hr_all, "movements", _year_period())


def test_personal_list_report_and_exports_hide_outside_person(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]
) -> None:
    inside, outside = people
    _discipline(inside)
    _discipline(outside)
    _assert_report_scoped(hr_north, hr_all, "discipline", _year_period())


def test_safety_report_and_exports_ignore_outside_accident(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]
) -> None:
    """The safety report shows counts, not names: the outside accident must change the control's numbers
    (page, print and Excel) and must leave the limited user's numbers as they were."""
    inside, outside = people
    _accident(inside)
    before_all = _report_surfaces(hr_all, "accidents", _year_period())
    before_limited = _report_surfaces(hr_north, "accidents", _year_period())
    _accident(outside)
    after_all = _report_surfaces(hr_all, "accidents", _year_period())
    after_limited = _report_surfaces(hr_north, "accidents", _year_period())

    def same_page(text: str) -> str:
        return re.sub(r"[A-Za-z0-9]{32,}", "", text)  # a page carries a new CSRF token on every request

    for surface in before_all:
        assert same_page(after_all[surface]) != same_page(before_all[surface]), (
            f"{surface}: control does not count the outside accident"
        )
        assert same_page(after_limited[surface]) == same_page(before_limited[surface]), (
            f"{surface}: the outside accident is counted"
        )


# --- activity log by employee ---


def test_activity_log_hides_outside_person(hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]) -> None:
    inside, outside = people
    url = reverse("logs:employee")
    assert OUT_FAMILY in _get(hr_all, "activity log", url)  # control
    body = _get(hr_north, "activity log", url)
    assert IN_FAMILY in body
    assert OUT_FAMILY not in body
    for params in ({"employee": str(outside.pk)}, {"emp": OUT_FAMILY}):
        assert OUT_FAMILY not in _no_echo(_get(hr_north, "activity log", url, params), OUT_FAMILY)
    assert OUT_FAMILY in _get(hr_all, "activity log", url, {"employee": str(outside.pk)})  # control
    export = _xlsx_text(hr_north.get(reverse("logs:employee_xlsx")))
    assert IN_FAMILY in export
    assert OUT_FAMILY not in export


# --- scope modes across the screens ---


def _screens(client: Client) -> dict[str, str]:
    """The full page of each screen the scope governs: leave, orders, staff report (the employees screen), activity log."""
    return {
        "leave list": _get(client, "leave list", reverse("leave:list")),
        "orders register": _get(client, "orders register", reverse("employees:orders")),
        "staff report": _get(client, "staff report", reverse("reports:report", args=["staff-list"])),
        "activity log": _get(client, "activity log", reverse("logs:employee")),
    }


def test_nothing_ticked_user_sees_only_own_record(
    hr_all: Client,
    people: tuple[Employee, Employee],
    due_soon: None,
    actor: User,
    job_values: dict[str, Any],
    north: Any,
    leave_type: Any,
) -> None:
    inside, outside = people
    third = _hire(actor, job_values, north, "УБ00000055", THIRD_FAMILY, THIRD_GIVEN)
    _leave_today(third, leave_type, actor)
    own = _user_in(roles.HR, "hr_own_only", limit=[])  # limited, nothing ticked
    link_login(inside, own)  # the login is the inside person's own record
    for screen, body in _screens(hr_all).items():  # control
        assert OUT_FAMILY in body and THIRD_FAMILY in body, screen
    for screen, body in _screens(_client(User.objects.get(pk=own.pk))).items():
        assert IN_FAMILY in body, screen
        assert OUT_FAMILY not in body, screen
        assert THIRD_FAMILY not in body, screen


def test_own_team_user_sees_self_and_team_only(
    hr_all: Client,
    people: tuple[Employee, Employee],
    due_soon: None,
    actor: User,
    job_values: dict[str, Any],
    north: Any,
    south: Any,
    leave_type: Any,
) -> None:
    inside, outside = people
    third = _hire(actor, {**job_values, "manager": inside}, north, "УБ00000055", THIRD_FAMILY, THIRD_GIVEN)
    fourth = _hire(actor, job_values, south, "УБ00000066", FOURTH_FAMILY, FOURTH_GIVEN)
    _leave_today(third, leave_type, actor)
    _leave_today(fourth, leave_type, actor)
    lead = _user_in(roles.HR, "hr_team_lead")
    AccessScope.objects.create(user=lead, limited=True, own_team=True)
    link_login(inside, lead)  # the lead's own record is the inside person; the third reports to them
    for screen, body in _screens(hr_all).items():  # control
        assert OUT_FAMILY in body and FOURTH_FAMILY in body and THIRD_FAMILY in body, screen
    for screen, body in _screens(_client(User.objects.get(pk=lead.pk))).items():
        assert IN_FAMILY in body and THIRD_FAMILY in body, screen
        assert OUT_FAMILY not in body, screen
        assert FOURTH_FAMILY not in body, screen


# --- reports: the employee filter, and a saved view (only the staff list keeps saved views) ---


def test_movements_employee_filter_for_outside_person_is_reset(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]
) -> None:
    """The movements report has an employee filter. An outside pk in the address is reset to the default (table.py),
    so the visible people show and the outside person does not."""
    inside, outside = people
    params = {**_year_period(), "employee": str(outside.pk)}
    for surface, text in _report_surfaces(hr_all, "movements", params).items():  # control
        assert OUT_FAMILY in text, surface
    for surface, text in _report_surfaces(hr_north, "movements", params).items():
        assert IN_FAMILY in text, surface
        assert OUT_FAMILY not in text, surface


def test_saved_staff_view_with_outside_pk_shows_only_visible_people(
    hr_north: Client, hr_all: Client, people: tuple[Employee, Employee]
) -> None:
    inside, outside = people
    query = f"employee={outside.pk}"
    saved = hr_north.post(reverse("reports:view_new", args=["staff-list"]), {"name": "Бүх ажилтан", "query": query})
    assert saved.status_code == 204
    assert OUT_FAMILY in _get(hr_all, "saved view", saved["HX-Redirect"])  # control: the view lists everyone
    body = _get(hr_north, "saved view", saved["HX-Redirect"])
    assert IN_FAMILY in body
    assert OUT_FAMILY not in body
