"""GET and POST under /api/v1/leave/holidays, /settings and /settings/types: the public holidays page, the leave
settings page and the leave-type pop-up as the React pages call them. The rules come from leave.services.holiday_page,
settings_page and writes; these tests pin the API's shape, its rights, the refusals and the recount."""

from datetime import date
from typing import Any

import pytest
from accounts import roles
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.utils import timezone
from employees import daily_sync
from employees.models import Employee
from employees.tests.conftest import _no_offboarding_templates  # noqa: F401 (autouse: no checklist gate here)
from leave.forms import GROUP_PREFIX, MANAGER_CHOICE
from leave.models import LeaveSettings, LeaveTypeExt
from leave.services import calendar, records, writes
from leave.services.holiday_page import holiday_page
from leave.services.records import Draft
from leave.services.settings_page import type_rows
from leave.tests.conftest import make_employee
from macs.models import LeaveAssign, LeaveTypeRow

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
HOLIDAYS = "/api/v1/leave/holidays"
SETTINGS = "/api/v1/leave/settings"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"]}
SAVED = {"ok": True, "error": "", "form_errors": [], "field_errors": {}}
FIXED_TODAY = date(2026, 11, 24)  # a Tuesday in the year the holiday tests read
BAD_DATE = "Огноо буруу эсвэл нэр хоосон байна."
OTHER_YEAR = "Огноо сонгосон жилийнх байх ёстой."
TOO_LONG = "Нэр 100 тэмдэгтээс урт байж болохгүй."
IN_USE_SUFFIX = "ашиглаж байгаа тул устгах боломжгүй."
UNKNOWN_CHOICE = "Жагсаалтаас сонгоно уу."
NOV_WEEK = (date(2026, 11, 2), date(2026, 11, 6))  # Mon-Fri, 5 working days
TYPE_BODY: dict[str, Any] = {
    "name": "Шинэ төрөл",
    "is_paid": True,
    "uses_annual_balance": False,
    "is_active": True,
    "order": 3,
    "staff_may_request": True,
}
HOLIDAY_KEYS = {"year", "holidays", "fixed_count", "empty_text"}
SETTINGS_KEYS = {"types", "auto_annual_grant", "approval", "step1_choices", "step2_choices"}
TYPE_KEYS = {"id", "name", "is_paid", "uses_annual_balance", "is_active", "order", "staff_may_request"}


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily sync runs on the first signed-in request of a process; these tests do not want it to write grants."""
    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("leave_setup_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def annual(db: None) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=True, is_paid=True)
    return row


@pytest.fixture
def sick(db: None) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Өвчний амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True)
    return row


@pytest.fixture
def grants_on(db: None) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})


@pytest.fixture
def employee(actor: User, grants_on: None) -> Employee:
    return make_employee(actor, hired=date(2024, 3, 1))


@pytest.fixture
def today(monkeypatch: pytest.MonkeyPatch) -> date:
    """The API reads the year with timezone.localdate(); the junk-year test needs a fixed day."""
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: FIXED_TODAY)
    return FIXED_TODAY


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _direct(name: str, codenames: list[str]) -> User:
    """A user with the given leave permissions and no role group."""
    user = User.objects.create_user(name, password=PASSWORD)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="leave"))
    return User.objects.get(pk=user.pk)


def _post(client: Client, url: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(url, data=body or {}, content_type="application/json")


def _refused(error: str = "", **field_errors: list[str]) -> dict[str, Any]:
    return {"ok": False, "error": error, "form_errors": [], "field_errors": field_errors}


def _snapshot() -> tuple[dict[Any, str], list[str], bool]:
    """What the writes could change: the holiday names of the test year, the type names, the auto-grant flag."""
    return (
        calendar.holiday_names(2026),
        sorted(LeaveTypeRow.objects.values_list("name", flat=True)),
        LeaveSettings.get().auto_annual_grant,
    )


# --- rights and login ----------------------------------------------------------------------------------------------


def test_every_route_needs_a_signed_in_user(annual: LeaveTypeRow) -> None:
    anonymous = Client()
    for url in (HOLIDAYS, SETTINGS, f"{SETTINGS}/types/{annual.pk}"):
        response = anonymous.get(url)
        assert response.status_code == 401, url
        assert response.json() == NOT_LOGGED_IN
    for url in (f"{HOLIDAYS}/add", f"{HOLIDAYS}/delete", f"{HOLIDAYS}/prefill", f"{SETTINGS}/approval"):
        assert _post(anonymous, url).status_code == 401, url
    assert _post(anonymous, f"{SETTINGS}/types", TYPE_BODY).status_code == 401


def test_every_route_needs_the_settings_right_and_writes_nothing(annual: LeaveTypeRow) -> None:
    nobody = _direct("leave_setup_viewer", ["view_leave"])
    client = _client(nobody)
    before = _snapshot()
    reads = [HOLIDAYS, SETTINGS, f"{SETTINGS}/types/{annual.pk}"]
    writes_ = [
        (f"{HOLIDAYS}/add", {"year": 2026, "date": "2026-11-04", "name": "Амралт"}),
        (f"{HOLIDAYS}/delete", {"year": 2026, "date": "2026-11-04"}),
        (f"{HOLIDAYS}/prefill", {"year": 2026}),
        (f"{SETTINGS}/approval", {"step1": MANAGER_CHOICE, "step2": ""}),
        (f"{SETTINGS}/auto", {"auto_annual_grant": True}),
        (f"{SETTINGS}/types", TYPE_BODY),
        (f"{SETTINGS}/types/{annual.pk}", TYPE_BODY),
        (f"{SETTINGS}/types/{annual.pk}/delete", None),
    ]
    for url in reads:
        response = client.get(url)
        assert response.status_code == 403, url
        assert response.json() == FORBIDDEN
    for url, body in writes_:
        response = _post(client, url, body)
        assert response.status_code == 403, url
        assert response.json() == FORBIDDEN
    assert _snapshot() == before


# --- holidays ------------------------------------------------------------------------------------------------------


def test_holidays_read_keys_no_store_and_the_service_list(actor: User) -> None:
    calendar.prefill_year(2026)
    writes.set_holiday_dates(2026, {date(2026, 11, 4): "Амралт"})
    response = _client(actor).get(HOLIDAYS, {"year": "2026"})
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == HOLIDAY_KEYS
    page = holiday_page(2026)
    assert body["year"] == 2026
    assert body["holidays"] == [{"date": d.isoformat(), "name": name} for d, name in page.holidays]
    assert body["fixed_count"] == len(calendar.FIXED_HOLIDAYS)
    assert body["empty_text"] == "Бүртгээгүй"


def test_holidays_junk_year_is_this_year(actor: User, today: date) -> None:
    client = _client(actor)
    assert client.get(HOLIDAYS, {"year": "abc"}).json()["year"] == 2026
    assert client.get(HOLIDAYS, {"year": "3000"}).json()["year"] == 2026
    assert client.get(HOLIDAYS).json()["year"] == 2026


def test_add_then_listed(actor: User) -> None:
    client = _client(actor)
    body = {"year": 2026, "date": "2026-11-04", "name": "  Амралт  "}
    assert _post(client, f"{HOLIDAYS}/add", body).json() == SAVED
    listed = client.get(HOLIDAYS, {"year": "2026"}).json()["holidays"]
    assert {"date": "2026-11-04", "name": "Амралт"} in listed


@pytest.mark.parametrize(
    ("raw_date", "raw_name", "text"),
    [
        ("x", "Амралт", BAD_DATE),
        ("2026-11-04", "", BAD_DATE),
        ("2026-11-04", "   ", BAD_DATE),
        ("2027-01-01", "Шинэ жил", OTHER_YEAR),
        ("2026-11-04", "а" * 101, TOO_LONG),
    ],
)
def test_add_refusals_use_the_django_texts_and_change_nothing(
    actor: User, raw_date: str, raw_name: str, text: str
) -> None:
    before = calendar.holiday_names(2026)
    response = _post(_client(actor), f"{HOLIDAYS}/add", {"year": 2026, "date": raw_date, "name": raw_name})
    assert response.json() == _refused(text)
    assert calendar.holiday_names(2026) == before


def test_delete_ok_and_a_bad_date_is_still_ok(actor: User) -> None:
    client = _client(actor)
    _post(client, f"{HOLIDAYS}/add", {"year": 2026, "date": "2026-11-04", "name": "Амралт"})
    assert _post(client, f"{HOLIDAYS}/delete", {"year": 2026, "date": "2026-11-04"}).json() == SAVED
    assert date(2026, 11, 4) not in calendar.holiday_names(2026)
    assert _post(client, f"{HOLIDAYS}/delete", {"year": 2026, "date": "x"}).json() == SAVED


def test_prefill_twice_adds_nothing_the_second_time(actor: User) -> None:
    client = _client(actor)
    assert _post(client, f"{HOLIDAYS}/prefill", {"year": 2026}).json() == SAVED
    first = len(calendar.holiday_names(2026))
    assert first == len(calendar.FIXED_HOLIDAYS)
    assert _post(client, f"{HOLIDAYS}/prefill", {"year": 2026}).json() == SAVED
    assert len(calendar.holiday_names(2026)) == first


def test_add_recounts_an_info_hr_leave_covering_the_day(actor: User, employee: Employee, annual: LeaveTypeRow) -> None:
    records.record(Draft(employee, annual, *NOV_WEEK), actor, date(2026, 10, 14))
    assert _post(_client(actor), f"{HOLIDAYS}/add", {"year": 2026, "date": "2026-11-04", "name": "Амралт"}).json() == (
        SAVED
    )
    assert LeaveAssign.objects.get(employee=employee).adays == 4


def test_body_year_null_is_this_year(actor: User, today: date) -> None:
    response = _post(_client(actor), f"{HOLIDAYS}/add", {"year": None, "date": "2026-11-04", "name": "Амралт"})
    assert response.json() == SAVED
    assert date(2026, 11, 4) in calendar.holiday_names(2026)


# --- settings ------------------------------------------------------------------------------------------------------


def test_settings_read_keys_no_store_and_the_types_in_service_order(actor: User, annual: LeaveTypeRow) -> None:
    writes.save_leave_type("Гадаад төрөл", {"order": 9})
    writes.save_leave_type("Анхны төрөл", {"order": 1})
    response = _client(actor).get(SETTINGS)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == SETTINGS_KEYS
    assert [t["id"] for t in body["types"]] == [row.pk for row, _ in type_rows()]
    assert [t["order"] for t in body["types"]] == sorted(t["order"] for t in body["types"])
    assert all(set(t) == TYPE_KEYS for t in body["types"])
    assert body["approval"] == {"step1": "", "step2": ""}
    assert body["step1_choices"][0] == {"value": "", "label": "Батлахгүй"}
    assert body["step1_choices"][1] == {"value": MANAGER_CHOICE, "label": "Шууд удирдлага"}
    assert body["step2_choices"][0] == {"value": "", "label": "—"}


def test_step_choices_have_one_group_choice_per_group(actor: User) -> None:
    group = Group.objects.get_or_create(name=roles.HR)[0]
    body = _client(actor).get(SETTINGS).json()
    group_values = [c for c in body["step1_choices"] if c["value"].startswith(GROUP_PREFIX)]
    assert len(group_values) == Group.objects.count()
    assert {"value": f"{GROUP_PREFIX}{group.pk}", "label": roles.ROLE_LABELS[roles.HR]} in group_values


def test_approval_save_stores_values_and_clears_removed_flag(actor: User) -> None:
    group = Group.objects.create(name="Step role")
    setting = LeaveSettings.get()
    setting.approval_role_removed = True
    setting.save()
    response = _post(
        _client(actor),
        f"{SETTINGS}/approval",
        {"step1": f"{GROUP_PREFIX}{group.pk}", "step2": MANAGER_CHOICE},
    )
    assert response.json() == SAVED
    stored = LeaveSettings.objects.get(pk=1)
    assert stored.approval1_group_id == group.pk
    assert stored.approval2_manager is True
    assert stored.approval_role_removed is False


def test_approval_unknown_choice_is_a_field_error_and_nothing_changes(actor: User) -> None:
    before = LeaveSettings.get().approval1_group_id
    response = _post(_client(actor), f"{SETTINGS}/approval", {"step1": f"{GROUP_PREFIX}999999", "step2": ""})
    assert response.json() == _refused(step1=[UNKNOWN_CHOICE])
    assert LeaveSettings.get().approval1_group_id == before


def test_approval_empty_step1_forces_step2_empty(actor: User) -> None:
    response = _post(_client(actor), f"{SETTINGS}/approval", {"step1": "", "step2": MANAGER_CHOICE})
    assert response.json() == SAVED
    stored = LeaveSettings.objects.get(pk=1)
    assert stored.approval2_manager is False
    assert stored.approval2_group_id is None


def test_auto_save_flips_only_the_flag_and_writes_the_audit_line(actor: User) -> None:
    setting = LeaveSettings.get()
    setting.approval1_manager = True
    setting.save()
    before = SystemLogEntry.objects.filter(action="setting_changed").count()
    response = _post(_client(actor), f"{SETTINGS}/auto", {"auto_annual_grant": True})
    assert response.json() == SAVED
    stored = LeaveSettings.objects.get(pk=1)
    assert stored.auto_annual_grant is True
    assert stored.approval1_manager is True
    assert SystemLogEntry.objects.filter(action="setting_changed").count() == before + 1


# --- leave types ---------------------------------------------------------------------------------------------------


def test_type_read_returns_the_type(actor: User, annual: LeaveTypeRow) -> None:
    response = _client(actor).get(f"{SETTINGS}/types/{annual.pk}")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == TYPE_KEYS
    assert body["id"] == annual.pk
    assert body["name"] == "Ээлжийн амралт"
    assert body["uses_annual_balance"] is True


def test_type_read_unknown_pk_is_404(actor: User) -> None:
    response = _client(actor).get(f"{SETTINGS}/types/999999")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_type_create_saves_name_and_ext(actor: User) -> None:
    response = _post(_client(actor), f"{SETTINGS}/types", TYPE_BODY)
    assert response.json() == SAVED
    row = LeaveTypeRow.objects.get(name="Шинэ төрөл")
    assert LeaveTypeExt.objects.get(leave_type=row).order == 3


def test_type_create_refusals_are_field_errors(actor: User) -> None:
    client = _client(actor)
    for changes, field in (({"order": 40000}, "order"), ({"name": ""}, "name"), ({"name": "а" * 201}, "name")):
        response = _post(client, f"{SETTINGS}/types", {**TYPE_BODY, **changes})
        body = response.json()
        assert body["ok"] is False, changes
        assert set(body["field_errors"]) == {field}, changes
    assert not LeaveTypeRow.objects.filter(name="Шинэ төрөл").exists()


def test_type_update_changes_name_and_ext(actor: User, annual: LeaveTypeRow) -> None:
    body = {**TYPE_BODY, "name": "Ээлжийн (шинэ)", "is_paid": False, "order": 7}
    assert _post(_client(actor), f"{SETTINGS}/types/{annual.pk}", body).json() == SAVED
    annual.refresh_from_db()
    assert annual.name == "Ээлжийн (шинэ)"
    ext = LeaveTypeExt.objects.get(leave_type=annual)
    assert ext.is_paid is False
    assert ext.order == 7


def test_type_update_unknown_pk_is_404(actor: User) -> None:
    response = _post(_client(actor), f"{SETTINGS}/types/999999", TYPE_BODY)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_type_delete_in_use_is_refused_and_the_type_stays(actor: User, employee: Employee, sick: LeaveTypeRow) -> None:
    records.record(Draft(employee, sick, *NOV_WEEK), actor, date(2026, 10, 14))
    body = _post(_client(actor), f"{SETTINGS}/types/{sick.pk}/delete").json()
    assert body["ok"] is False
    assert body["error"].endswith(IN_USE_SUFFIX)
    assert LeaveTypeRow.objects.filter(pk=sick.pk).exists()


def test_type_delete_unused_is_ok(actor: User) -> None:
    unused = LeaveTypeRow.objects.create(name="Хэрэглээгүй")
    assert _post(_client(actor), f"{SETTINGS}/types/{unused.pk}/delete").json() == SAVED
    assert not LeaveTypeRow.objects.filter(pk=unused.pk).exists()


def test_type_delete_unknown_pk_is_404(actor: User) -> None:
    response = _post(_client(actor), f"{SETTINGS}/types/999999/delete")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
