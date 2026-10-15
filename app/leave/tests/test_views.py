from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import Employee

from leave.models import Leave, LeaveType

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("leave.views.today", lambda: date(2026, 10, 14))
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: date(2026, 10, 14))


def _client(user: User) -> Client:
    c = Client()
    c.force_login(user)
    return c


def _in_group(name: str) -> User:
    u = User.objects.create_user(f"u_{name}", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=name))
    return u


def _post(employee: Employee, annual: LeaveType, **extra: str) -> dict[str, str]:
    data = {
        "employee": str(employee.pk),
        "leave_type": str(annual.pk),
        "start_date": "2026-11-02",
        "end_date": "2026-11-06",
        "note": "",
    }
    data.update(extra)
    return data


def test_list_requires_view_permission(employee: Employee) -> None:
    nobody = User.objects.create_user("nobody", password="x-long-pass-123")  # noqa: S106
    assert _client(nobody).get(reverse("leave:list")).status_code == 403
    assert _client(_in_group("Accountant")).get(reverse("leave:list")).status_code == 200


def test_accountant_cannot_record(employee: Employee, annual: LeaveType) -> None:
    r = _client(_in_group("Accountant")).post(reverse("leave:add"), _post(employee, annual))
    assert r.status_code == 403 and not Leave.objects.exists()


def test_hr_records_leave(employee: Employee, annual: LeaveType) -> None:
    r = _client(_in_group("HR")).post(reverse("leave:add"), _post(employee, annual))
    assert r.status_code == 204
    assert Leave.objects.get().working_days == 5


def test_check_fragment_shows_days_and_warnings(employee: Employee, annual: LeaveType) -> None:
    r = _client(_in_group("HR")).post(reverse("leave:check"), _post(employee, annual, end_date="2026-11-30"))
    body = r.content.decode()
    assert "21" in body and "Үлдэгдэл хүрэлцэхгүй" in body


def test_negative_balance_without_reason_rerenders_form(employee: Employee, annual: LeaveType) -> None:
    r = _client(_in_group("HR")).post(reverse("leave:add"), _post(employee, annual, end_date="2026-11-30"))
    assert r.status_code == 200 and "шалтгаан" in r.content.decode() and not Leave.objects.exists()


def test_list_filters_by_type(employee: Employee, annual: LeaveType) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    sick = LeaveType.objects.get(code="sick")
    assert "2026-11-02" not in hr.get(reverse("leave:list"), {"type": sick.pk}).content.decode()
    assert "2026-11-02" in hr.get(reverse("leave:list"), {"type": annual.pk}).content.decode()


def test_cancel(employee: Employee, annual: LeaveType) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    leave = Leave.objects.get()
    assert hr.post(reverse("leave:cancel", args=[leave.pk]), {"reason": "Өөрчлөгдсөн"}).status_code == 204
    leave.refresh_from_db()
    assert leave.status == "cancelled"


def test_missing_holidays_banner(employee: Employee) -> None:
    body = _client(_in_group("HR")).get(reverse("leave:list")).content.decode()
    assert "баярын өдөр бүртгээгүй" in body


@pytest.mark.parametrize("qs", ["type=abc", "employee=abc", "from=garbage", "to=garbage"])
def test_malformed_filters_ignored(employee: Employee, qs: str) -> None:
    assert _client(_in_group("HR")).get(reverse("leave:list") + "?" + qs).status_code == 200


def test_invisible_employee_rejected(annual: LeaveType) -> None:
    r = _client(_in_group("HR")).post(
        reverse("leave:add"),
        {"employee": "99999", "leave_type": str(annual.pk), "start_date": "2026-11-02", "end_date": "2026-11-06"},
    )
    assert r.status_code == 200 and not Leave.objects.exists()


def test_edit_changes_days(employee: Employee, annual: LeaveType) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    leave = Leave.objects.get()
    r = hr.post(
        reverse("leave:edit", args=[leave.pk]), _post(employee, annual, end_date="2026-11-04", leave_id=str(leave.pk))
    )
    assert r.status_code == 204
    leave.refresh_from_db()
    assert leave.working_days == 3


def test_edit_forbidden_without_record_permission(employee: Employee, annual: LeaveType) -> None:
    _client(_in_group("HR")).post(reverse("leave:add"), _post(employee, annual))
    leave = Leave.objects.get()
    assert _client(_in_group("Accountant")).get(reverse("leave:edit", args=[leave.pk])).status_code == 403


def test_edit_cannot_move_leave_to_other_employee(employee: Employee, annual: LeaveType, actor: User) -> None:
    from leave.tests.conftest import make_employee

    other = make_employee(actor, hired=date(2020, 6, 1), register_no="УБ55112233")
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    leave = Leave.objects.get()
    r = hr.post(reverse("leave:edit", args=[leave.pk]), _post(other, annual, end_date="2026-11-04"))
    assert r.status_code == 204
    leave.refresh_from_db()
    assert leave.employee_id == employee.pk


def test_edit_form_keeps_inactive_type(employee: Employee, annual: LeaveType) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    leave = Leave.objects.get()
    LeaveType.objects.filter(pk=annual.pk).update(is_active=False)
    url = reverse("leave:edit", args=[leave.pk])
    assert f'value="{annual.pk}" selected' in hr.get(url).content.decode()
    assert hr.post(url, _post(employee, annual, end_date="2026-11-04")).status_code == 204


def test_bad_input_never_500s(employee: Employee, annual: LeaveType) -> None:
    hr = _client(_in_group("HR"))
    big = "9" * 5000
    assert hr.get(reverse("leave:list"), {"type": big, "employee": "²³"}).status_code == 200
    assert hr.post(reverse("leave:check"), {**_post(employee, annual), "leave_id": big}).status_code == 200
    for month in ("9999-12", "0001-01", "abc", "2026-13"):
        assert hr.get(reverse("leave:calendar"), {"month": month}).status_code == 200
    admin = _client(User.objects.create_superuser("adm", password="x-long-pass-123"))  # noqa: S106
    for year in ("99999999999999999999", "0", "9999"):
        assert admin.get(reverse("leave:holidays"), {"year": year}).status_code == 200
    r = admin.post(reverse("leave:holidays"), {"action": "delete", "id": big})
    assert r.status_code == 302


def _two_people_with_leave(actor: User, annual: LeaveType) -> tuple[Employee, Employee]:
    from leave.services import records
    from leave.services.records import Draft
    from leave.tests.conftest import make_employee

    a = make_employee(actor, hired=date(2020, 3, 1), register_no="УБ11112233")
    a.family_name, a.given_name = "Ганбатын", "Сарантуяа"
    a.save()
    b = make_employee(actor, hired=date(2020, 3, 1), register_no="УБ22112233")
    b.family_name, b.given_name = "Дорждэрэмийн", "Болд"
    b.save()
    records.record(Draft(a, annual, date(2026, 11, 2), date(2026, 11, 3)), actor, date(2026, 10, 14))
    records.record(Draft(b, annual, date(2026, 11, 9), date(2026, 11, 10)), actor, date(2026, 10, 14))
    return a, b


def test_search_by_name_ignores_case(actor: User, annual: LeaveType) -> None:
    _two_people_with_leave(actor, annual)
    body = _client(_in_group("HR")).get(reverse("leave:list"), {"q": "ГАН"}).content.decode()
    assert "2026-11-02" in body and "2026-11-09" not in body


def test_search_by_full_name_and_code(actor: User, annual: LeaveType) -> None:
    a, b = _two_people_with_leave(actor, annual)
    hr = _client(_in_group("HR"))
    assert "2026-11-09" in hr.get(reverse("leave:list"), {"q": "Дорждэрэмийн Болд"}).content.decode()
    by_code = hr.get(reverse("leave:list"), {"q": b.code.lower()}).content.decode()
    assert "2026-11-09" in by_code and "2026-11-02" not in by_code


def test_blank_search_shows_everyone(actor: User, annual: LeaveType) -> None:
    _two_people_with_leave(actor, annual)
    body = _client(_in_group("HR")).get(reverse("leave:list"), {"q": "  "}).content.decode()
    assert "2026-11-02" in body and "2026-11-09" in body


def test_employee_link_filters_and_prefills(actor: User, annual: LeaveType) -> None:
    a, _b = _two_people_with_leave(actor, annual)
    body = _client(_in_group("HR")).get(reverse("leave:list"), {"employee": a.pk}).content.decode()
    assert "2026-11-02" in body and "2026-11-09" not in body
    assert 'value="Ганбатын Сарантуяа"' in body


def test_list_labels_cancel_by_start_date(employee: Employee, annual: LeaveType) -> None:
    from decimal import Decimal

    c = _client(_in_group("HR"))
    past = Leave.objects.create(
        employee=employee,
        leave_type=annual,
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 18),
        working_days=Decimal(5),
        year_start=date(2026, 3, 1),
    )
    Leave.objects.create(
        employee=employee,
        leave_type=annual,
        start_date=date(2026, 11, 16),
        end_date=date(2026, 11, 20),
        working_days=Decimal(5),
        year_start=date(2026, 3, 1),
    )
    page = c.get("/leave/?status=all").content.decode()
    assert "Буруу бүртгэсэн</button>" in page and "Цуцлах</button>" in page
    modal = c.get(f"/leave/{past.pk}/cancel/").content.decode()
    assert "цуцлах биш, буруу бүртгэснийг засна" in modal
