import secrets
from datetime import date, timedelta
from decimal import Decimal

import pytest
from accounts.models import User
from accounts.roles import HR
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.utils import timezone
from employees.models import Employee, ensure_ext
from employees.services import history, macs_writes
from leave.models import LeaveSettings
from leave.services import records
from leave.services import writes as leave_writes
from leave.services.records import Draft
from macs.models import LeaveTypeRow

pytestmark = pytest.mark.django_db

PASSWORD = secrets.token_urlsafe(16)
TOP_KEYS = {
    "today",
    "headcount",
    "away_today",
    "has_own_page",
    "shortcuts",
    "box",
    "show_views",
    "strip",
    "upcoming",
    "company",
}


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("today-hr", password=PASSWORD, is_active=True)
    user.groups.add(Group.objects.get_or_create(name=HR)[0])
    return user


@pytest.fixture
def plain_user(db: None) -> User:
    return User.objects.create_user("today-plain", password=PASSWORD, is_active=True)


def _working_employee(actor: User, login: User | None, birth: date) -> Employee:
    """A hired person with a job (so the page counts them as working), optionally linked to `login`."""
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "УБ99112233",
        "birth_date": birth,
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    employee = history.hire(
        values,
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=actor,
        order_number="1",
        order_date=date(2026, 1, 5),
    )
    if login is not None:
        ext = ensure_ext(employee)
        ext.user = login
        ext.save(update_fields=["user"])
    return employee


def test_today_as_hr_has_all_keys(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    response = client.get("/api/v1/today")

    assert response.status_code == 200
    assert TOP_KEYS <= set(response.json())


def test_strip_has_fourteen_cells_and_today_first(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    strip = client.get("/api/v1/today").json()["strip"]

    assert len(strip["cells"]) == 14
    assert strip["cells"][0]["is_today"] is True


def test_plain_user_without_leave_right_sees_no_counts(client: Client, plain_user: User) -> None:
    client.force_login(plain_user)

    strip = client.get("/api/v1/today").json()["strip"]

    assert strip["show_leave"] is False
    assert all(cell["count"] is None for cell in strip["cells"])
    assert strip["today_line"] == ""  # no sentence about who is away without the leave right


def test_plain_user_own_birthday_is_not_counted(client: Client, hr_user: User, plain_user: User) -> None:
    birth = (timezone.localdate() + timedelta(days=10)).replace(year=1990)  # inside the 30-day window
    _working_employee(hr_user, login=plain_user, birth=birth)

    client.force_login(hr_user)
    assert client.get("/api/v1/today").json()["upcoming"]["birthdays"] == 1  # the birthday is really there

    client.force_login(plain_user)
    upcoming = client.get("/api/v1/today").json()["upcoming"]
    assert upcoming["show_birthdays"] is False
    assert upcoming["birthdays"] == 0


def test_plain_user_without_personal_right_sees_no_birthdays(client: Client, plain_user: User) -> None:
    client.force_login(plain_user)

    upcoming = client.get("/api/v1/today").json()["upcoming"]

    assert upcoming["show_birthdays"] is False


def test_today_anonymous_401(client: Client) -> None:
    response = client.get("/api/v1/today")

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "not_authenticated"
    assert body["form_errors"] == ["Нэвтрэх шаардлагатай."]
    assert body["field_errors"] == {}


def _iso_days_from_today(offset: int) -> str:
    return (timezone.localdate() + timedelta(days=offset)).isoformat()


def test_away_for_today_is_200(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    response = client.get("/api/v1/today/away", {"day": _iso_days_from_today(0)})

    assert response.status_code == 200
    assert response.json()["day"] == _iso_days_from_today(0)
    assert response.json()["people"] == []


def test_away_fourteen_days_ahead_is_404(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    assert client.get("/api/v1/today/away", {"day": _iso_days_from_today(14)}).status_code == 404


def test_away_yesterday_is_404(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    assert client.get("/api/v1/today/away", {"day": _iso_days_from_today(-1)}).status_code == 404


def test_away_bad_day_is_404(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    assert client.get("/api/v1/today/away", {"day": "x"}).status_code == 404


def test_upcoming_unknown_kind_is_404(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    assert client.get("/api/v1/today/upcoming", {"kind": "foo"}).status_code == 404


def test_upcoming_birthday_has_items_list(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    response = client.get("/api/v1/today/upcoming", {"kind": "birthday"})

    assert response.status_code == 200
    assert response.json() == {"kind": "birthday", "items": []}


def test_hires_is_a_list(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    response = client.get("/api/v1/today/hires")

    assert response.status_code == 200
    assert response.json() == []


def test_views_empty_without_reports_right(client: Client, plain_user: User) -> None:
    client.force_login(plain_user)

    response = client.get("/api/v1/today/views")

    assert response.status_code == 200
    assert response.json() == []


def test_today_answers_carry_no_store(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    urls = [
        ("/api/v1/today/away", {"day": _iso_days_from_today(0)}),
        ("/api/v1/today/upcoming", {"kind": "birthday"}),
        ("/api/v1/today/upcoming", {"kind": "anniversary"}),
        ("/api/v1/today/hires", {}),
        ("/api/v1/today/views", {}),
    ]
    for url, params in urls:
        response = client.get(url, params)
        assert response.status_code == 200, url
        assert response["Cache-Control"] == "no-store", url


@pytest.fixture
def annual(db: None) -> LeaveTypeRow:
    return leave_writes.save_leave_type(
        "Ээлжийн амралт", {"is_paid": True, "uses_annual_balance": True, "is_active": True, "order": 1}
    )


@pytest.fixture
def leave_actor(db: None) -> User:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    return User.objects.create_superuser("today-leave-actor", password=PASSWORD, is_active=True)


@pytest.fixture
def viewer(db: None) -> User:
    """Sees every employee (macs.view_employees) but has neither the leave right nor the personal right."""
    user = User.objects.create_user("today-viewer", password=PASSWORD, is_active=True)
    user.user_permissions.add(Permission.objects.get(content_type__app_label="macs", codename="view_employees"))
    return user


def test_away_today_lists_the_person_on_leave_for_hr(
    client: Client, hr_user: User, leave_actor: User, annual: LeaveTypeRow
) -> None:
    colleague = _working_employee(hr_user, login=None, birth=date(1990, 5, 5))
    today = timezone.localdate()
    records.record(Draft(colleague, annual, today - timedelta(days=1), today + timedelta(days=1)), leave_actor, today)
    client.force_login(hr_user)

    response = client.get("/api/v1/today/away", {"day": _iso_days_from_today(0)})

    assert response.status_code == 200
    assert response.json()["people"] == [
        {
            "id": colleague.pk,
            "full_name": colleague.full_name,
            "label": annual.name,
            "until": _iso_days_from_today(1),
        }
    ]


def test_away_today_is_empty_without_the_leave_right(
    client: Client, hr_user: User, viewer: User, leave_actor: User, annual: LeaveTypeRow
) -> None:
    colleague = _working_employee(hr_user, login=None, birth=date(1990, 5, 5))
    today = timezone.localdate()
    records.record(Draft(colleague, annual, today - timedelta(days=1), today + timedelta(days=1)), leave_actor, today)
    client.force_login(viewer)

    response = client.get("/api/v1/today/away", {"day": _iso_days_from_today(0)})

    assert response.status_code == 200
    assert response.json()["people"] == []


def test_birthday_inside_the_window_is_listed_for_hr_only(client: Client, hr_user: User, viewer: User) -> None:
    birth = (timezone.localdate() + timedelta(days=10)).replace(year=1990)  # inside the 30-day window
    colleague = _working_employee(hr_user, login=None, birth=birth)

    client.force_login(hr_user)
    items = client.get("/api/v1/today/upcoming", {"kind": "birthday"}).json()["items"]
    assert [(item["id"], item["kind"], item["on"]) for item in items] == [
        (colleague.pk, "birthday", _iso_days_from_today(10))
    ]

    client.force_login(viewer)
    assert client.get("/api/v1/today/upcoming", {"kind": "birthday"}).json()["items"] == []


def test_away_thirteen_days_ahead_is_the_last_allowed_day(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    response = client.get("/api/v1/today/away", {"day": _iso_days_from_today(13)})

    assert response.status_code == 200
    assert response.json()["day"] == _iso_days_from_today(13)
