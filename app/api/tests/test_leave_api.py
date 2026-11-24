"""GET /api/v1/leave, /leave/options, /leave/{pk} and /leave/{pk}/cancel: the leave screen's read routes as the React
page reads them. The rules come from leave.services; these tests pin the API's shape, its rights and its paging."""

from datetime import date, timedelta
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from config import batching
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees import access as employee_access
from employees import daily_sync
from employees.models import ActivityEntry, ActivityKind, Employee, EmployeeExt
from employees.tests.conftest import _no_offboarding_templates  # noqa: F401 (autouse: no checklist gate here)
from leave.models import LeaveExt, LeaveTypeExt
from leave.services import calendar, ledger, writes
from leave.services import rows as leave_rows
from leave.services.rows import State
from leave.tests.conftest import make_employee
from macs.models import LeaveAssign, LeaveTypeRow

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/leave"
OPTIONS_URL = "/api/v1/leave/options"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"]}
TODAY = timezone.localdate()
PAST_LABEL = "Буруу гэж тэмдэглэх"
FUTURE_LABEL = "Цуцлах"


@pytest.fixture
def annual() -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=True, is_paid=True)
    return row


@pytest.fixture
def sick() -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Өвчний амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True)
    return row


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily sync runs on the first signed-in request of a process; these tests do not want it to write grants."""
    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _direct(name: str, codenames: list[str]) -> User:
    """A user with leave permissions given one by one (no role group), for the cases a role does not cover."""
    user = User.objects.create_user(name, password=PASSWORD)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="leave"))
    return User.objects.get(pk=user.pk)


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def hr() -> User:
    return _user("leave_api_hr", roles.HR)


@pytest.fixture
def admin() -> User:
    return _user("leave_api_admin", roles.ADMIN)


@pytest.fixture
def accountant() -> User:
    """Can view leave, cannot record it; holds the reports right."""
    return _user("leave_api_accountant", roles.ACCOUNTANT)


@pytest.fixture
def no_leave_right() -> User:
    return _user("leave_api_employee", roles.EMPLOYEE)


@pytest.fixture
def viewer_only() -> User:
    """Can view leave, but has neither the reports right nor the record right."""
    return _direct("leave_api_viewer", ["view_leave"])


@pytest.fixture
def recorder_unseen() -> User:
    """Can record leave but sees no employee: nobody is linked to this login."""
    return _direct("leave_api_recorder", ["view_leave", "record_leave"])


@pytest.fixture
def person(hr: User) -> Employee:
    return make_employee(hr, hired=date(2020, 3, 1), register_no="УБ11112233")


@pytest.fixture
def person2(hr: User) -> Employee:
    other = make_employee(hr, hired=date(2020, 3, 1), register_no="УБ22112233")
    other.family_name, other.given_name = "Дорждэрэмийн", "Болд"
    other.save()
    return other


@pytest.fixture
def past_leave(person: Employee, annual: LeaveTypeRow) -> LeaveAssign:
    return LeaveAssign.objects.create(
        employee=person,
        leave_type=annual,
        date1=TODAY - timedelta(days=30),
        date2=TODAY - timedelta(days=29),
        status=LeaveAssign.APPROVED,
        adays=2,
        comment="Тайлбар",
    )


@pytest.fixture
def future_leave(person2: Employee, annual: LeaveTypeRow) -> LeaveAssign:
    return LeaveAssign.objects.create(
        employee=person2,
        leave_type=annual,
        date1=TODAY + timedelta(days=30),
        date2=TODAY + timedelta(days=31),
        status=LeaveAssign.APPROVED,
        adays=2,
        comment="",
    )


@pytest.fixture
def two_leaves(past_leave: LeaveAssign, future_leave: LeaveAssign) -> tuple[LeaveAssign, LeaveAssign]:
    return past_leave, future_leave


@pytest.fixture
def no_holidays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every year is missing its public holidays, so the banners do not depend on the test database."""
    monkeypatch.setattr(calendar, "has_holidays", lambda year: False)


def _leave_pk_url(pk: int, suffix: str = "") -> str:
    return f"{URL}/{pk}{suffix}"


# --- rights and login ----------------------------------------------------------------------------------------------


def test_every_route_needs_a_signed_in_user(past_leave: LeaveAssign) -> None:
    anonymous = Client()
    for url in (URL, OPTIONS_URL, _leave_pk_url(past_leave.pk), _leave_pk_url(past_leave.pk, "/cancel")):
        response = anonymous.get(url)
        assert response.status_code == 401, url
        assert response.json() == NOT_LOGGED_IN


def test_list_needs_the_view_right(no_leave_right: User) -> None:
    response = _client(no_leave_right).get(URL)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


@pytest.mark.parametrize("suffix", ["", "/cancel"])
def test_edit_and_cancel_load_need_the_record_right(accountant: User, past_leave: LeaveAssign, suffix: str) -> None:
    response = _client(accountant).get(_leave_pk_url(past_leave.pk, suffix))
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_options_needs_the_record_right(accountant: User, viewer_only: User) -> None:
    for user in (accountant, viewer_only):
        response = _client(user).get(OPTIONS_URL)
        assert response.status_code == 403
        assert response.json() == FORBIDDEN


# --- the list ------------------------------------------------------------------------------------------------------


def test_list_rows_are_the_leaves_page(hr: User, two_leaves: tuple[LeaveAssign, LeaveAssign]) -> None:
    body = _client(hr).get(URL).json()
    expected, more = leave_rows.leaves_page(
        employee_access.visible_employees(hr),
        offset=0,
        size=batching.LIST_BATCH,
        state="RECORDED",
    )
    assert not more
    assert [row["id"] for row in body["rows"]] == [lv.id for lv in expected]
    first = body["rows"][0]  # the newest leave: the future one
    assert first["employee_name"] == "Дорждэрэмийн Болд"
    assert first["state"] == "Бүртгэсэн"
    assert first["state_chip"] is False
    assert first["counts"] is True
    assert first["start"] == (TODAY + timedelta(days=30)).isoformat()
    assert first["days"] == 2
    assert body["rows"][1]["comment"] == "Тайлбар"


def test_cancel_label_follows_the_started_rule_and_needs_record_right(
    hr: User, accountant: User, two_leaves: tuple[LeaveAssign, LeaveAssign]
) -> None:
    labels = {row["id"]: row["cancel_label"] for row in _client(hr).get(URL).json()["rows"]}
    past, future = two_leaves
    assert labels == {past.pk: PAST_LABEL, future.pk: FUTURE_LABEL}

    viewed = _client(accountant).get(URL).json()
    assert viewed["can_record"] is False
    assert {row["cancel_label"] for row in viewed["rows"]} == {None}


def test_list_is_never_cached(hr: User, two_leaves: tuple[LeaveAssign, LeaveAssign]) -> None:
    response = _client(hr).get(URL)
    assert response["Cache-Control"] == "no-store"


def test_next_offset_follows_the_batch_size(
    monkeypatch: pytest.MonkeyPatch, hr: User, two_leaves: tuple[LeaveAssign, LeaveAssign]
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 1)
    client = _client(hr)
    first = client.get(URL).json()
    assert len(first["rows"]) == 1
    assert first["next_offset"] == 1

    second = client.get(URL, {"offset": "1"}).json()
    assert len(second["rows"]) == 1
    assert second["next_offset"] is None


def test_unknown_status_matches_nothing(hr: User, two_leaves: tuple[LeaveAssign, LeaveAssign]) -> None:
    body = _client(hr).get(URL, {"status": "garbage"}).json()
    assert body["rows"] == []
    assert body["next_offset"] is None
    assert body["filters"]["status"] == "garbage"


@pytest.mark.parametrize("bad", ["abc", "99999999999"])
def test_bad_employee_is_ignored(hr: User, two_leaves: tuple[LeaveAssign, LeaveAssign], bad: str) -> None:
    body = _client(hr).get(URL, {"employee": bad}).json()
    assert len(body["rows"]) == 2
    assert body["filters"]["employee"] is None


def test_employee_link_narrows_the_list_and_sets_the_search_text(
    hr: User, person: Employee, two_leaves: tuple[LeaveAssign, LeaveAssign]
) -> None:
    body = _client(hr).get(URL, {"employee": str(person.pk)}).json()
    assert [row["employee_id"] for row in body["rows"]] == [person.pk]
    assert body["filters"]["q"] == person.full_name


def test_date_range_and_type_filters_narrow_the_list(
    hr: User, annual: LeaveTypeRow, sick: LeaveTypeRow, two_leaves: tuple[LeaveAssign, LeaveAssign]
) -> None:
    past, future = two_leaves
    client = _client(hr)
    only_future = client.get(URL, {"from": (TODAY + timedelta(days=1)).isoformat()}).json()
    assert [row["id"] for row in only_future["rows"]] == [future.pk]
    assert only_future["filters"]["date_from"] == (TODAY + timedelta(days=1)).isoformat()

    only_past = client.get(URL, {"to": (TODAY - timedelta(days=1)).isoformat()}).json()
    assert [row["id"] for row in only_past["rows"]] == [past.pk]

    no_sick = client.get(URL, {"type": str(sick.pk)}).json()
    assert no_sick["rows"] == []
    assert client.get(URL, {"type": str(annual.pk)}).json()["filters"]["type_id"] == annual.pk


def test_report_link_needs_the_reports_right(
    hr: User, viewer_only: User, two_leaves: tuple[LeaveAssign, LeaveAssign]
) -> None:
    report = reverse("reports:report", args=["annual-leave"])
    assert _client(hr).get(URL).json()["report_url"] == report
    assert _client(viewer_only).get(URL).json()["report_url"] is None


def test_missing_holidays_can_register_needs_the_settings_right(no_holidays: None, hr: User, admin: User) -> None:
    for user, expected in ((admin, True), (hr, False)):
        years = _client(user).get(URL).json()["missing_holidays"]
        assert {"year": TODAY.year, "can_register": expected} in years


def test_not_configured_text_when_no_annual_type(sick: LeaveTypeRow, hr: User) -> None:
    body = _client(hr).get(URL).json()
    assert body["not_configured"] == ledger.NOT_CONFIGURED


def test_list_types_and_empty_text(annual: LeaveTypeRow, sick: LeaveTypeRow, hr: User) -> None:
    body = _client(hr).get(URL).json()
    assert {t["label"] for t in body["types"]} == {annual.name, sick.name}
    assert body["empty_text"] == "Чөлөө бүртгэгдээгүй"
    assert body["rows"] == []


# --- the add pop-up's options --------------------------------------------------------------------------------------


def test_options_without_a_link_start_on_today(hr: User, person: Employee, annual: LeaveTypeRow) -> None:
    body = _client(hr).get(OPTIONS_URL).json()
    assert body["initial"] == {
        "employee": None,
        "leave_type": None,
        "start_date": TODAY.isoformat(),
        "end_date": TODAY.isoformat(),
    }
    assert body["assisted"] is None
    assert body["not_configured"] == ""
    assert {"value": person.pk, "label": str(person)} in body["employees"]
    assert {"value": annual.pk, "label": annual.name} in body["types"]


def test_options_leave_out_inactive_types(hr: User, annual: LeaveTypeRow) -> None:
    inactive = LeaveTypeRow.objects.create(name="Идэвхгүй төрөл")
    LeaveTypeExt.objects.create(leave_type=inactive, is_active=False)
    body = _client(hr).get(OPTIONS_URL, {"type": str(inactive.pk)}).json()
    assert inactive.pk not in {t["value"] for t in body["types"]}
    assert body["initial"]["leave_type"] is None


def test_assistant_link_fills_the_form_and_its_lines(hr: User, person: Employee, annual: LeaveTypeRow) -> None:
    start, end = TODAY - timedelta(days=2), TODAY - timedelta(days=1)
    body = (
        _client(hr)
        .get(
            OPTIONS_URL,
            {
                "from": "assistant",
                "employee": str(person.pk),
                "type": str(annual.pk),
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        .json()
    )
    assert body["initial"] == {
        "employee": person.pk,
        "leave_type": annual.pk,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    assert body["assisted"]["person_line"].startswith(person.full_name)
    assert body["assisted"]["filled_line"] == "Асуултаас бөглөсөн: Ажилтан, Төрөл, Эхлэх, Дуусах"


def test_assisted_lines_need_the_assistant_origin(hr: User, person: Employee, annual: LeaveTypeRow) -> None:
    body = _client(hr).get(OPTIONS_URL, {"employee": str(person.pk), "type": str(annual.pk)}).json()
    assert body["assisted"] is None
    assert body["initial"]["employee"] == person.pk
    assert body["initial"]["leave_type"] == annual.pk


def test_end_before_start_and_far_dates_are_dropped(hr: User) -> None:
    far = TODAY - timedelta(days=366 * 11)
    body = (
        _client(hr)
        .get(
            OPTIONS_URL,
            {"start": (TODAY + timedelta(days=5)).isoformat(), "end": TODAY.isoformat()},
        )
        .json()
    )
    assert body["initial"]["start_date"] == (TODAY + timedelta(days=5)).isoformat()
    assert body["initial"]["end_date"] == ""  # ends before it starts: end dropped

    far_body = _client(hr).get(OPTIONS_URL, {"start": far.isoformat(), "end": TODAY.isoformat()}).json()
    assert far_body["initial"]["start_date"] == ""
    assert far_body["initial"]["end_date"] == TODAY.isoformat()


def test_options_employees_are_only_the_visible_ones(recorder_unseen: User, person: Employee) -> None:
    body = _client(recorder_unseen).get(OPTIONS_URL, {"employee": str(person.pk)}).json()
    assert body["employees"] == []
    assert body["initial"]["employee"] is None


# --- the edit pop-up's load ----------------------------------------------------------------------------------------


def test_edit_load_returns_the_row_as_loaded(
    hr: User, person: Employee, annual: LeaveTypeRow, past_leave: LeaveAssign
) -> None:
    body = _client(hr).get(_leave_pk_url(past_leave.pk)).json()
    assert body["id"] == past_leave.pk
    assert body["initial"] == {
        "employee": person.pk,
        "leave_type": annual.pk,
        "start_date": past_leave.date1.isoformat(),
        "end_date": past_leave.date2.isoformat(),
        "note": "Тайлбар",
        "override_reason": "",
    }
    assert body["loaded"] == {
        "leave_type": annual.pk,
        "date1": past_leave.date1.isoformat(),
        "date2": past_leave.date2.isoformat(),
        "status": LeaveAssign.APPROVED,
        "adays": 2,
        "comment": "Тайлбар",
    }
    assert {"value": annual.pk, "label": annual.name} in body["types"]
    assert {"value": person.pk, "label": str(person)} in body["employees"]


def test_edit_load_keeps_the_leave_own_inactive_type(hr: User, person: Employee) -> None:
    retired = LeaveTypeRow.objects.create(name="Хуучин төрөл")
    LeaveTypeExt.objects.create(leave_type=retired, is_active=False)
    leave = LeaveAssign.objects.create(
        employee=person,
        leave_type=retired,
        date1=TODAY - timedelta(days=60),
        date2=TODAY - timedelta(days=59),
        status=LeaveAssign.APPROVED,
        adays=2,
        comment=None,
    )
    body = _client(hr).get(_leave_pk_url(leave.pk)).json()
    assert retired.pk in {t["value"] for t in body["types"]}
    assert body["loaded"]["comment"] is None  # a NULL comment stays NULL


@pytest.mark.parametrize("suffix", ["", "/cancel"])
def test_invisible_or_missing_leave_is_404(recorder_unseen: User, past_leave: LeaveAssign, suffix: str) -> None:
    client = _client(recorder_unseen)
    assert client.get(_leave_pk_url(past_leave.pk, suffix)).status_code == 404
    response = client.get(_leave_pk_url(999999, suffix))
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


# --- the cancel pop-up's info --------------------------------------------------------------------------------------


def test_cancel_info_of_a_started_leave_is_a_mistake(hr: User, annual: LeaveTypeRow, past_leave: LeaveAssign) -> None:
    body = _client(hr).get(_leave_pk_url(past_leave.pk, "/cancel")).json()
    assert body["mistake"] is True
    assert body["label"] == annual.name
    assert body["restores_balance"] is True  # the annual type gives its days back
    assert body["start"] == past_leave.date1.isoformat()
    assert body["end"] == past_leave.date2.isoformat()
    assert body["loaded"]["leave_type"] == annual.pk


def test_cancel_info_of_a_future_leave_is_not_a_mistake(hr: User, future_leave: LeaveAssign) -> None:
    body = _client(hr).get(_leave_pk_url(future_leave.pk, "/cancel")).json()
    assert body["mistake"] is False


def test_cancel_info_of_a_leave_starting_today_is_a_mistake(hr: User, person: Employee, annual: LeaveTypeRow) -> None:
    leave = LeaveAssign.objects.create(
        employee=person,
        leave_type=annual,
        date1=TODAY,
        date2=TODAY + timedelta(days=1),
        status=LeaveAssign.APPROVED,
        adays=2,
        comment="",
    )
    assert _client(hr).get(_leave_pk_url(leave.pk, "/cancel")).json()["mistake"] is True


def test_cancel_info_of_a_sick_leave_does_not_restore_the_balance(
    hr: User, person: Employee, sick: LeaveTypeRow
) -> None:
    leave = LeaveAssign.objects.create(
        employee=person,
        leave_type=sick,
        date1=TODAY + timedelta(days=3),
        date2=TODAY + timedelta(days=4),
        status=LeaveAssign.APPROVED,
        adays=2,
        comment="",
    )
    assert _client(hr).get(_leave_pk_url(leave.pk, "/cancel")).json()["restores_balance"] is False


def test_cancelled_leave_row_has_no_cancel_button(hr: User, person: Employee, annual: LeaveTypeRow) -> None:
    cancelled = LeaveAssign.objects.create(
        employee=person,
        leave_type=annual,
        date1=TODAY - timedelta(days=90),
        date2=TODAY - timedelta(days=89),
        status=LeaveAssign.CANCELLED,
        adays=2,
        comment="",
    )
    LeaveExt.objects.create(assign=cancelled, mistake=True)
    body = _client(hr).get(URL, {"status": "mistake"}).json()
    [row] = body["rows"]
    assert row["state"] == "Буруу бүртгэсэн"
    assert row["state_chip"] is True
    assert row["counts"] is False
    assert row["cancel_label"] is None


# --- the read routes' cache header ----------------------------------------------------------------------------------


def test_edit_load_and_cancel_info_are_never_cached(hr: User, past_leave: LeaveAssign) -> None:
    client = _client(hr)
    assert client.get(_leave_pk_url(past_leave.pk))["Cache-Control"] == "no-store"
    assert client.get(_leave_pk_url(past_leave.pk, "/cancel"))["Cache-Control"] == "no-store"


# --- writes ---------------------------------------------------------------------------------------------------------

CREATE_URL = URL
CHECK_URL = f"{URL}/check"
START = TODAY + timedelta(days=100)  # a span of seven days always holds working days
END = TODAY + timedelta(days=106)


def _loaded(leave: LeaveAssign) -> dict[str, Any]:
    """The row as the edit pop-up sends it back (the shape GET /leave/{pk} returns under `loaded`)."""
    return {
        "leave_type": leave.leave_type_id,
        "date1": leave.date1.isoformat(),
        "date2": leave.date2.isoformat(),
        "status": leave.status,
        "adays": leave.adays,
        "comment": leave.comment,
    }


def _form(
    person: Employee, leave_type: LeaveTypeRow, start: date | None, end: date | None, **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "employee": person.pk,
        "leave_type": leave_type.pk,
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        "note": "",
        "override_reason": "",
    }
    body.update(extra)
    return body


def _post(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, data=body, content_type="application/json")


@pytest.fixture
def sick_leave(person: Employee, sick: LeaveTypeRow) -> LeaveAssign:
    return LeaveAssign.objects.create(
        employee=person,
        leave_type=sick,
        date1=START,
        date2=START + timedelta(days=4),
        status=LeaveAssign.APPROVED,
        adays=5,
        comment="Анхны",
    )


def _write_urls(pk: int) -> list[str]:
    return [CREATE_URL, _leave_pk_url(pk), CHECK_URL, _leave_pk_url(pk, "/cancel")]


def test_writes_need_a_signed_in_user(past_leave: LeaveAssign) -> None:
    for url in _write_urls(past_leave.pk):
        response = _post(Client(), url, {})
        assert response.status_code == 401, url
        assert response.json() == NOT_LOGGED_IN


@pytest.mark.parametrize("user_fixture", ["accountant", "viewer_only", "no_leave_right"])
def test_writes_need_the_record_right_and_write_nothing(
    request: pytest.FixtureRequest, past_leave: LeaveAssign, person: Employee, sick: LeaveTypeRow, user_fixture: str
) -> None:
    client = _client(request.getfixturevalue(user_fixture))
    before = LeaveAssign.objects.count()
    bodies = [
        _form(person, sick, START, END),
        _form(person, sick, START, END, loaded=_loaded(past_leave)),
        _form(person, sick, START, END, leave_id=past_leave.pk),
        {"reason": "Шалтгаан", "loaded": _loaded(past_leave)},
    ]
    for url, body in zip(_write_urls(past_leave.pk), bodies, strict=True):
        response = _post(client, url, body)
        assert response.status_code == 403, url
        assert response.json() == FORBIDDEN
    assert LeaveAssign.objects.count() == before
    assert LeaveAssign.objects.get(pk=past_leave.pk).comment == "Тайлбар"


def test_create_records_the_leave_and_logs_it(hr: User, person: Employee, sick: LeaveTypeRow) -> None:
    response = _post(_client(hr), CREATE_URL, _form(person, sick, START, END, note="Тэмдэглэл"))
    assert response.status_code == 200
    assert response.json() == {"ok": True, "error": "", "form_errors": [], "field_errors": {}}

    created = LeaveAssign.objects.get(employee=person, leave_type=sick, date1=START, date2=END)
    assert created.status == LeaveAssign.APPROVED
    assert created.comment == "Тэмдэглэл"
    entry = ActivityEntry.objects.filter(employee=person).latest("id")
    assert entry.kind == ActivityKind.CHANGED
    assert entry.message.startswith("Чөлөө бүртгэсэн: ")  # the same message the Django add view writes


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"end_date": None}, "end_date"),
        ({"leave_type": None}, "leave_type"),
        ({"note": "я" * 201}, "note"),
    ],
)
def test_create_invalid_input_is_refused_with_field_errors(
    hr: User, person: Employee, sick: LeaveTypeRow, change: dict[str, Any], field: str
) -> None:
    before = LeaveAssign.objects.count()
    body = {**_form(person, sick, START, END), **change}
    response = _post(_client(hr), CREATE_URL, body).json()
    assert response["ok"] is False
    assert field in response["field_errors"]
    assert response["error"] == ""
    assert LeaveAssign.objects.count() == before


def test_create_service_refusals_come_back_as_error_text(hr: User, person: Employee, sick: LeaveTypeRow) -> None:
    client = _client(hr)
    backwards = _post(client, CREATE_URL, _form(person, sick, END, START)).json()
    assert backwards == {
        "ok": False,
        "error": "Дуусах огноо эхлэхээс өмнө байна.",
        "form_errors": [],
        "field_errors": {},
    }

    assert _post(client, CREATE_URL, _form(person, sick, START, END)).json()["ok"] is True
    again = _post(client, CREATE_URL, _form(person, sick, START, END)).json()
    assert again["ok"] is False
    assert again["error"] == writes.DUPLICATE


def test_create_for_an_employee_outside_the_visible_set_is_refused(
    recorder_unseen: User, person: Employee, sick: LeaveTypeRow
) -> None:
    response = _post(_client(recorder_unseen), CREATE_URL, _form(person, sick, START, END)).json()
    assert response["ok"] is False
    assert "employee" in response["field_errors"]
    assert not LeaveAssign.objects.filter(employee=person, date1=START).exists()


def test_update_saves_the_changed_leave_and_logs_it(
    hr: User, person: Employee, sick: LeaveTypeRow, sick_leave: LeaveAssign
) -> None:
    body = _form(person, sick, START, sick_leave.date2, note="Шинэ", loaded=_loaded(sick_leave))
    response = _post(_client(hr), _leave_pk_url(sick_leave.pk), body).json()
    assert response == {"ok": True, "error": "", "form_errors": [], "field_errors": {}}
    sick_leave.refresh_from_db()
    assert sick_leave.comment == "Шинэ"
    entry = ActivityEntry.objects.filter(employee=person).latest("id")
    assert entry.message.startswith("Чөлөө засварласан: ")


@pytest.mark.parametrize(
    "loaded_change",
    [
        None,  # the object is missing
        {"leave_type": "abc"},  # text where an id belongs
        {"date1": 20261124},  # a number where a date belongs
        {"status": "one"},
        {"comment": 5},
    ],
)
def test_update_with_missing_or_malformed_loaded_is_stale_and_writes_nothing(
    hr: User, person: Employee, sick: LeaveTypeRow, sick_leave: LeaveAssign, loaded_change: dict[str, Any] | None
) -> None:
    loaded = None if loaded_change is None else {**_loaded(sick_leave), **loaded_change}
    body = _form(person, sick, START, sick_leave.date2, note="Шинэ", loaded=loaded)
    response = _post(_client(hr), _leave_pk_url(sick_leave.pk), body)
    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": writes.STALE, "form_errors": [], "field_errors": {}}
    sick_leave.refresh_from_db()
    assert sick_leave.comment == "Анхны"


def test_update_of_a_row_someone_else_changed_is_stale(
    hr: User, person: Employee, sick: LeaveTypeRow, sick_leave: LeaveAssign
) -> None:
    loaded = _loaded(sick_leave)  # what the user loaded
    LeaveAssign.objects.filter(pk=sick_leave.pk).update(comment="Өөр хэрэглэгч")
    body = _form(person, sick, START, sick_leave.date2, note="Шинэ", loaded=loaded)
    response = _post(_client(hr), _leave_pk_url(sick_leave.pk), body).json()
    assert response["ok"] is False
    assert response["error"] == writes.STALE
    assert LeaveAssign.objects.get(pk=sick_leave.pk).comment == "Өөр хэрэглэгч"


def test_update_refuses_an_overlong_note(
    hr: User, person: Employee, sick: LeaveTypeRow, sick_leave: LeaveAssign
) -> None:
    body = _form(person, sick, START, sick_leave.date2, note="я" * 201, loaded=_loaded(sick_leave))
    response = _post(_client(hr), _leave_pk_url(sick_leave.pk), body).json()
    assert response["ok"] is False
    assert "note" in response["field_errors"]
    sick_leave.refresh_from_db()
    assert sick_leave.comment == "Анхны"


def test_update_of_an_invisible_leave_is_404(
    recorder_unseen: User, person: Employee, sick: LeaveTypeRow, sick_leave: LeaveAssign
) -> None:
    body = _form(person, sick, START, sick_leave.date2, loaded=_loaded(sick_leave))
    client = _client(recorder_unseen)
    response = _post(client, _leave_pk_url(sick_leave.pk), body)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert _post(client, _leave_pk_url(999999), body).status_code == 404


def test_cancel_of_a_started_leave_marks_it_a_mistake(hr: User, past_leave: LeaveAssign) -> None:
    body = {"reason": "Буруу оруулсан", "loaded": _loaded(past_leave)}
    response = _post(_client(hr), _leave_pk_url(past_leave.pk, "/cancel"), body).json()
    assert response == {"ok": True, "error": "", "form_errors": [], "field_errors": {}}
    assert leave_rows.leave(past_leave.pk).state is State.MISTAKE
    assert LeaveExt.objects.get(assign_id=past_leave.pk).mistake is True


def test_cancel_of_a_future_leave_is_cancelled(hr: User, future_leave: LeaveAssign) -> None:
    body = {"reason": "Амралт цуцлагдсан", "loaded": _loaded(future_leave)}
    assert _post(_client(hr), _leave_pk_url(future_leave.pk, "/cancel"), body).json()["ok"] is True
    assert leave_rows.leave(future_leave.pk).state is State.CANCELLED


@pytest.mark.parametrize("reason", ["", "   ", "я" * 201])
def test_cancel_needs_a_reason_of_at_most_200_characters(hr: User, past_leave: LeaveAssign, reason: str) -> None:
    body = {"reason": reason, "loaded": _loaded(past_leave)}
    response = _post(_client(hr), _leave_pk_url(past_leave.pk, "/cancel"), body).json()
    assert response["ok"] is False
    assert "reason" in response["field_errors"]
    assert leave_rows.leave(past_leave.pk).state is State.RECORDED


def test_cancel_with_missing_or_changed_loaded_is_stale(hr: User, past_leave: LeaveAssign) -> None:
    client = _client(hr)
    url = _leave_pk_url(past_leave.pk, "/cancel")
    missing = _post(client, url, {"reason": "Шалтгаан", "loaded": None}).json()
    assert missing == {"ok": False, "error": writes.STALE, "form_errors": [], "field_errors": {}}

    stale_loaded = {**_loaded(past_leave), "comment": "Өөр"}
    changed = _post(client, url, {"reason": "Шалтгаан", "loaded": stale_loaded}).json()
    assert changed["error"] == writes.STALE
    assert leave_rows.leave(past_leave.pk).state is State.RECORDED


def test_cancel_of_an_invisible_leave_is_404(recorder_unseen: User, past_leave: LeaveAssign) -> None:
    body = {"reason": "Шалтгаан", "loaded": _loaded(past_leave)}
    response = _post(_client(recorder_unseen), _leave_pk_url(past_leave.pk, "/cancel"), body)
    assert response.status_code == 404
    assert leave_rows.leave(past_leave.pk).state is State.RECORDED


# --- the live check -----------------------------------------------------------------------------------------------


def test_check_of_a_valid_form(hr: User, person: Employee, sick: LeaveTypeRow) -> None:
    body = _form(person, sick, date(2026, 11, 16), date(2026, 11, 20))  # Mon to Fri
    response = _post(_client(hr), CHECK_URL, body).json()
    assert response["valid"] is True
    assert response["working_days"] == 5  # a literal count: no public holidays fall in that week
    assert response["errors"] == []
    assert response["period"] is None  # only annual leave has a grant period


def test_check_of_an_invalid_form_answers_empty(hr: User, person: Employee, sick: LeaveTypeRow) -> None:
    body = {**_form(person, sick, START, END), "leave_type": None}
    response = _post(_client(hr), CHECK_URL, body).json()
    assert response == {
        "valid": False,
        "working_days": 0,
        "balance_after": None,
        "period": None,
        "errors": [],
        "warnings": [],
    }


def test_check_reports_a_backwards_range_as_an_error(hr: User, person: Employee, sick: LeaveTypeRow) -> None:
    response = _post(_client(hr), CHECK_URL, _form(person, sick, END, START)).json()
    assert response["valid"] is False
    assert response["errors"] == ["Дуусах огноо эхлэхээс өмнө байна."]
    assert response["working_days"] == 0


def test_check_ignores_a_leave_the_user_may_not_see(
    person: Employee, person2: Employee, sick: LeaveTypeRow, past_leave: LeaveAssign
) -> None:
    """A user who sees only their own employee: a leave_id of someone else's leave changes nothing (check_for)."""
    user = _direct("leave_api_self", ["view_leave", "record_leave"])
    EmployeeExt.objects.update_or_create(employee=person2, defaults={"user": user})
    client = _client(user)
    body = _form(person2, sick, START, END)
    plain = _post(client, CHECK_URL, body).json()
    with_hidden = _post(client, CHECK_URL, {**body, "leave_id": past_leave.pk}).json()
    assert plain["valid"] is True
    assert with_hidden == plain


# --- review follow-ups ---------------------------------------------------------------------------------------------

NOT_AN_OBJECT = ["text", 5, [1, 2], True]
STALE_RESULT = {"ok": False, "error": writes.STALE, "form_errors": [], "field_errors": {}}


@pytest.mark.parametrize("loaded", NOT_AN_OBJECT)
def test_update_with_a_loaded_that_is_not_an_object_is_stale(
    hr: User, person: Employee, sick: LeaveTypeRow, sick_leave: LeaveAssign, loaded: Any
) -> None:
    body = _form(person, sick, START, sick_leave.date2, note="Шинэ", loaded=loaded)
    response = _post(_client(hr), _leave_pk_url(sick_leave.pk), body)
    assert response.status_code == 200
    assert response.json() == STALE_RESULT
    sick_leave.refresh_from_db()
    assert sick_leave.comment == "Анхны"


@pytest.mark.parametrize("loaded", NOT_AN_OBJECT)
def test_cancel_with_a_loaded_that_is_not_an_object_is_stale(hr: User, past_leave: LeaveAssign, loaded: Any) -> None:
    body = {"reason": "Шалтгаан", "loaded": loaded}
    response = _post(_client(hr), _leave_pk_url(past_leave.pk, "/cancel"), body)
    assert response.status_code == 200
    assert response.json() == STALE_RESULT
    assert leave_rows.leave(past_leave.pk).state is State.RECORDED


def test_check_of_an_annual_leave_shows_the_balance_and_period(
    hr: User, person: Employee, annual: LeaveTypeRow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: date(2026, 10, 14))
    ledger.manual_grant(person, date(2026, 3, 1), date(2027, 2, 28), 20, "тест", hr)
    body = _form(person, annual, date(2026, 11, 16), date(2026, 11, 18))  # Mon to Wed
    response = _post(_client(hr), CHECK_URL, body).json()
    assert response["valid"] is True
    assert response["errors"] == []
    assert response["working_days"] == 3
    assert response["balance_after"] == 17  # 20 days granted, 3 charged
    assert response["period"] == {"start": "2026-03-01", "end": "2027-02-28"}


def test_check_with_an_employee_outside_the_visible_set_answers_empty(
    recorder_unseen: User, person: Employee, sick: LeaveTypeRow
) -> None:
    response = _post(_client(recorder_unseen), CHECK_URL, _form(person, sick, START, END)).json()
    assert response == {
        "valid": False,
        "working_days": 0,
        "balance_after": None,
        "period": None,
        "errors": [],
        "warnings": [],
    }


def test_create_with_an_inactive_leave_type_is_refused(hr: User, person: Employee) -> None:
    retired = LeaveTypeRow.objects.create(name="Хаагдсан төрөл")
    LeaveTypeExt.objects.create(leave_type=retired, is_active=False)
    before = LeaveAssign.objects.count()
    response = _post(_client(hr), CREATE_URL, _form(person, retired, START, END)).json()
    assert response["ok"] is False
    assert "leave_type" in response["field_errors"]
    assert LeaveAssign.objects.count() == before


def test_a_search_of_only_spaces_is_no_filter(hr: User, two_leaves: tuple[LeaveAssign, LeaveAssign]) -> None:
    body = _client(hr).get(URL, {"q": "   "}).json()
    assert len(body["rows"]) == 2
    assert body["filters"]["q"] == ""


def test_from_after_to_is_read_as_the_page_reads_it(hr: User, two_leaves: tuple[LeaveAssign, LeaveAssign]) -> None:
    start, end = TODAY + timedelta(days=40), TODAY + timedelta(days=20)
    body = _client(hr).get(URL, {"from": start.isoformat(), "to": end.isoformat()}).json()
    expected, more = leave_rows.leaves_page(
        employee_access.visible_employees(hr),
        offset=0,
        size=batching.LIST_BATCH,
        start=start,
        end=end,
        state="RECORDED",
    )
    assert not more
    assert [row["id"] for row in body["rows"]] == [lv.id for lv in expected]
    assert body["rows"] == []  # neither leave reaches back to `from` while ending before `to`


def test_bad_iso_dates_are_ignored(hr: User, two_leaves: tuple[LeaveAssign, LeaveAssign]) -> None:
    body = _client(hr).get(URL, {"from": "2026-13-45", "to": "abc"}).json()
    assert len(body["rows"]) == 2
    assert body["filters"]["date_from"] == ""
    assert body["filters"]["date_to"] == ""


def test_can_settings_follows_the_leave_settings_right(admin: User, hr: User) -> None:
    assert _client(admin).get(URL).json()["can_settings"] is True
    assert _client(hr).get(URL).json()["can_settings"] is False


def test_check_with_a_huge_leave_id_checks_a_new_leave(hr: User, person: Employee, sick: LeaveTypeRow) -> None:
    body = {**_form(person, sick, date(2026, 11, 16), date(2026, 11, 20)), "leave_id": 10**30}
    response = _post(_client(hr), CHECK_URL, body)
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["working_days"] == 5
