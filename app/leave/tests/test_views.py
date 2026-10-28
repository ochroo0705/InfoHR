from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from macs.models import Entitlement, LeaveAssign, LeaveTypeRow

from leave.models import GrantKind, LeaveGrantExt, LeaveSettings, LeaveTypeExt
from leave.services import records, writes
from leave.services.records import Draft
from leave.services.writes import DUPLICATE, STALE

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]


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


def _post(employee: Employee, annual: LeaveTypeRow, **extra: str) -> dict[str, str]:
    data = {
        "employee": str(employee.pk),
        "leave_type": str(annual.pk),
        "start_date": "2026-11-02",
        "end_date": "2026-11-06",
        "note": "",
    }
    data.update(extra)
    return data


def _loaded(a: LeaveAssign) -> dict[str, str]:
    """The hidden fields the edit and cancel forms post back (spec §10)."""
    snap = writes.snapshot(a)
    data = {
        "loaded_type": str(snap.leave_type_id),
        "loaded_date1": snap.date1.isoformat(),
        "loaded_date2": snap.date2.isoformat(),
        "loaded_status": "" if snap.status is None else str(snap.status),
        "loaded_adays": "" if snap.adays is None else str(snap.adays),
    }
    if snap.comment is not None:
        data["loaded_comment"] = snap.comment
    return data


def test_list_requires_view_permission(employee: Employee) -> None:
    nobody = User.objects.create_user("nobody", password="x-long-pass-123")  # noqa: S106
    assert _client(nobody).get(reverse("leave:list")).status_code == 403
    assert _client(_in_group("Accountant")).get(reverse("leave:list")).status_code == 200


def test_accountant_cannot_record(employee: Employee, annual: LeaveTypeRow) -> None:
    r = _client(_in_group("Accountant")).post(reverse("leave:add"), _post(employee, annual))
    assert r.status_code == 403 and not LeaveAssign.objects.exists()


def test_hr_records_leave(employee: Employee, annual: LeaveTypeRow) -> None:
    r = _client(_in_group("HR")).post(reverse("leave:add"), _post(employee, annual))
    assert r.status_code == 204
    assert LeaveAssign.objects.get().adays == 5


def test_check_fragment_shows_days_and_warnings(employee: Employee, annual: LeaveTypeRow) -> None:
    r = _client(_in_group("HR")).post(reverse("leave:check"), _post(employee, annual, end_date="2026-11-30"))
    body = r.content.decode()
    assert "21" in body and "Үлдэгдэл хүрэлцэхгүй" in body


def test_negative_balance_without_reason_rerenders_form(employee: Employee, annual: LeaveTypeRow) -> None:
    r = _client(_in_group("HR")).post(reverse("leave:add"), _post(employee, annual, end_date="2026-11-30"))
    assert r.status_code == 200 and "шалтгаан" in r.content.decode() and not LeaveAssign.objects.exists()


def test_conflict_message_on_duplicate(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    assert hr.post(reverse("leave:add"), _post(employee, annual)).status_code == 204
    r = hr.post(reverse("leave:add"), _post(employee, annual))
    assert r.status_code == 200 and DUPLICATE in r.content.decode()
    assert LeaveAssign.objects.count() == 1


def test_stale_edit_refused_view(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual, note="первый"))
    a = LeaveAssign.objects.get()
    posted = {**_post(employee, annual, end_date="2026-11-04", note="мой"), **_loaded(a)}
    LeaveAssign.objects.filter(pk=a.pk).update(comment="хуучин программ")  # the old program changed it meanwhile
    r = hr.post(reverse("leave:edit", args=[a.pk]), posted)
    assert r.status_code == 200 and STALE in r.content.decode()
    a.refresh_from_db()
    assert a.comment == "хуучин программ" and a.adays == 5


def test_list_filters_by_type(employee: Employee, annual: LeaveTypeRow, sick: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    assert "2026-11-02" not in hr.get(reverse("leave:list"), {"type": sick.pk}).content.decode()
    assert "2026-11-02" in hr.get(reverse("leave:list"), {"type": annual.pk}).content.decode()


def test_cancel(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    a = LeaveAssign.objects.get()
    r = hr.post(reverse("leave:cancel", args=[a.pk]), {"reason": "Өөрчлөгдсөн", **_loaded(a)})
    assert r.status_code == 204
    a.refresh_from_db()
    assert a.status == LeaveAssign.CANCELLED


def test_missing_holidays_banner(employee: Employee) -> None:
    body = _client(_in_group("HR")).get(reverse("leave:list")).content.decode()
    assert "баярын өдөр бүртгээгүй" in body


def test_banner_when_not_configured(employee: Employee) -> None:
    LeaveTypeExt.objects.all().delete()  # no type uses the annual balance
    body = _client(_in_group("Admin")).get(reverse("leave:list")).content.decode()
    assert "Ээлжийн амралтын төрлийг сонгоогүй байна" in body
    assert reverse("leave:settings") in body


def test_rejected_filter(employee: Employee, annual: LeaveTypeRow) -> None:
    LeaveAssign.objects.create(
        employee=employee,
        leave_type=annual,
        date1=date(2026, 9, 1),
        date2=date(2026, 9, 2),
        status=LeaveAssign.REJECTED,
        adays=2,
        comment="",
    )
    hr = _client(_in_group("HR"))
    assert "2026-09-01" not in hr.get(reverse("leave:list")).content.decode()
    rejected = hr.get(reverse("leave:list"), {"status": "rejected"}).content.decode()
    assert "2026-09-01" in rejected and "Татгалзсан" in rejected


def test_comment_over_200_refused(employee: Employee, annual: LeaveTypeRow) -> None:
    r = _client(_in_group("HR")).post(reverse("leave:add"), _post(employee, annual, note="x" * 201))
    assert r.status_code == 200 and not LeaveAssign.objects.exists()


@pytest.mark.parametrize("qs", ["type=abc", "employee=abc", "from=garbage", "to=garbage"])
def test_malformed_filters_ignored(employee: Employee, qs: str) -> None:
    assert _client(_in_group("HR")).get(reverse("leave:list") + "?" + qs).status_code == 200


def test_invisible_employee_rejected(annual: LeaveTypeRow) -> None:
    r = _client(_in_group("HR")).post(
        reverse("leave:add"),
        {"employee": "99999", "leave_type": str(annual.pk), "start_date": "2026-11-02", "end_date": "2026-11-06"},
    )
    assert r.status_code == 200 and not LeaveAssign.objects.exists()


def test_edit_changes_days(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    a = LeaveAssign.objects.get()
    r = hr.post(
        reverse("leave:edit", args=[a.pk]),
        {**_post(employee, annual, end_date="2026-11-04"), **_loaded(a)},
    )
    assert r.status_code == 204
    a.refresh_from_db()
    assert a.adays == 3


def test_edit_forbidden_without_record_permission(employee: Employee, annual: LeaveTypeRow) -> None:
    _client(_in_group("HR")).post(reverse("leave:add"), _post(employee, annual))
    a = LeaveAssign.objects.get()
    assert _client(_in_group("Accountant")).get(reverse("leave:edit", args=[a.pk])).status_code == 403


def test_edit_cannot_move_leave_to_other_employee(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    from leave.tests.conftest import make_employee

    other = make_employee(actor, hired=date(2020, 6, 1), register_no="УБ55112233")
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    a = LeaveAssign.objects.get()
    r = hr.post(
        reverse("leave:edit", args=[a.pk]),
        {**_post(other, annual, end_date="2026-11-04"), **_loaded(a)},
    )
    assert r.status_code == 204
    a.refresh_from_db()
    assert a.employee_id == employee.pk


def test_edit_form_keeps_inactive_type(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    a = LeaveAssign.objects.get()
    LeaveTypeExt.objects.filter(pk=annual.pk).update(is_active=False)
    url = reverse("leave:edit", args=[a.pk])
    assert f'value="{annual.pk}" selected' in hr.get(url).content.decode()
    assert hr.post(url, {**_post(employee, annual, end_date="2026-11-04"), **_loaded(a)}).status_code == 204


def test_bad_input_never_500s(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    big = "9" * 5000
    assert hr.get(reverse("leave:list"), {"type": big, "employee": "²³"}).status_code == 200
    assert hr.post(reverse("leave:check"), {**_post(employee, annual), "leave_id": big}).status_code == 200
    for month in ("9999-12", "0001-01", "abc", "2026-13"):
        assert hr.get(reverse("leave:calendar"), {"month": month}).status_code == 200
    admin = _client(User.objects.create_superuser("adm", password="x-long-pass-123"))  # noqa: S106
    for year in ("99999999999999999999", "0", "9999"):
        assert admin.get(reverse("leave:holidays"), {"year": year}).status_code == 200
    r = admin.post(reverse("leave:holidays"), {"action": "delete", "date": "garbage"})
    assert r.status_code == 302


def test_settings_toggle_requires_permission() -> None:
    accountant = _client(_in_group("Accountant"))
    assert accountant.get(reverse("leave:settings")).status_code == 403
    assert accountant.post(reverse("leave:settings"), {"auto_annual_grant": "on"}).status_code == 403
    hr = _client(_in_group("HR"))  # leave settings are Admin only (user, 2026-10-19)
    assert hr.get(reverse("leave:settings")).status_code == 403
    assert hr.get(reverse("leave:holidays")).status_code == 403
    assert LeaveSettings.get().auto_annual_grant is True  # set by the grants_on fixture
    LeaveSettings.objects.filter(pk=1).update(auto_annual_grant=False)
    assert _client(_in_group("Admin")).post(reverse("leave:settings"), {"auto_annual_grant": "on"}).status_code == 302
    assert LeaveSettings.get().auto_annual_grant is True


def test_settings_type_delete_refused_when_used(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("Admin"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    r = hr.post(reverse("leave:type_delete", args=[annual.pk]))
    assert r.status_code == 200 and "ашиглаж байгаа тул устгах боломжгүй" in r.content.decode()
    assert LeaveTypeRow.objects.filter(pk=annual.pk).exists()


def test_manual_grant_view_creates_entitlement(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    url = reverse("leave:grant", args=[employee.pk])
    r = hr.post(url, {"start": "2026-03-01", "end": "2027-02-28", "days": "3", "reason": "Захирал"})
    assert r.status_code == 204
    grant = Entitlement.objects.get(employee=employee)
    assert grant.ent_days == 3 and grant.date1 == date(2026, 3, 1)
    assert LeaveGrantExt.objects.get(grant=grant).kind == GrantKind.MANUAL


def test_manual_grant_shows_law_suggestion(employee: Employee, annual: LeaveTypeRow) -> None:
    body = (
        _client(_in_group("HR"))
        .post(reverse("leave:grant", args=[employee.pk]), {"start": "2026-03-01", "end": "", "days": "", "reason": ""})
        .content.decode()
    )
    assert "Хуулийн дагуу" in body


def test_adjust_view_uses_period_dates(employee: Employee, annual: LeaveTypeRow) -> None:
    r = _client(_in_group("HR")).post(
        reverse("leave:adjust", args=[employee.pk, "2026-03-01", "2027-02-28"]),
        {"days": "-2", "reason": "Өмнө авсан"},
    )
    assert r.status_code == 204
    assert Entitlement.objects.filter(employee=employee, ent_days=-2).exists()


def _two_people_with_leave(actor: User, annual: LeaveTypeRow) -> tuple[Employee, Employee]:
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


def test_search_by_name_ignores_case(actor: User, annual: LeaveTypeRow) -> None:
    _two_people_with_leave(actor, annual)
    body = _client(_in_group("HR")).get(reverse("leave:list"), {"q": "ГАН"}).content.decode()
    assert "2026-11-02" in body and "2026-11-09" not in body


def test_search_by_full_name_and_code(actor: User, annual: LeaveTypeRow) -> None:
    _a, b = _two_people_with_leave(actor, annual)
    hr = _client(_in_group("HR"))
    assert "2026-11-09" in hr.get(reverse("leave:list"), {"q": "Дорждэрэмийн Болд"}).content.decode()
    by_code = hr.get(reverse("leave:list"), {"q": str(b.code).lower()}).content.decode()
    assert "2026-11-09" in by_code and "2026-11-02" not in by_code


def test_blank_search_shows_everyone(actor: User, annual: LeaveTypeRow) -> None:
    _two_people_with_leave(actor, annual)
    body = _client(_in_group("HR")).get(reverse("leave:list"), {"q": "  "}).content.decode()
    assert "2026-11-02" in body and "2026-11-09" in body


def test_employee_link_filters_and_prefills(actor: User, annual: LeaveTypeRow) -> None:
    a, _b = _two_people_with_leave(actor, annual)
    body = _client(_in_group("HR")).get(reverse("leave:list"), {"employee": a.pk}).content.decode()
    assert "2026-11-02" in body and "2026-11-09" not in body
    assert 'value="Ганбатын Сарантуяа"' in body


def test_list_labels_cancel_by_start_date(employee: Employee, annual: LeaveTypeRow) -> None:
    c = _client(_in_group("HR"))
    past = LeaveAssign.objects.create(
        employee=employee,
        leave_type=annual,
        date1=date(2026, 9, 14),
        date2=date(2026, 9, 18),
        status=LeaveAssign.APPROVED,
        adays=5,
        comment="",
    )
    LeaveAssign.objects.create(
        employee=employee,
        leave_type=annual,
        date1=date(2026, 11, 16),
        date2=date(2026, 11, 20),
        status=LeaveAssign.APPROVED,
        adays=5,
        comment="",
    )
    page = c.get("/leave/?status=all").content.decode()
    assert "Буруу бүртгэсэн</button>" in page and "Цуцлах</button>" in page
    modal = c.get(f"/leave/{past.pk}/cancel/").content.decode()
    assert "цуцлах биш, буруу бүртгэснийг засна" in modal


def test_settings_page_lists_types(annual: LeaveTypeRow) -> None:
    body = _client(_in_group("Admin")).get(reverse("leave:settings")).content.decode()
    assert annual.name in body and "auto_annual_grant" in body


def test_type_add_creates_type_with_ext(actor: User) -> None:
    hr = _client(_in_group("Admin"))
    values = {"name": "Шинэ төрөл", "is_paid": "on", "order": "2", "is_active": "on"}
    assert hr.post(reverse("leave:type_add"), values).status_code == 204
    row = LeaveTypeRow.objects.get(name="Шинэ төрөл")
    ext = LeaveTypeExt.objects.get(leave_type=row)
    assert ext.is_paid is True and ext.uses_annual_balance is False and ext.order == 2


def test_type_edit_updates_flags(annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("Admin"))
    url = reverse("leave:type_edit", args=[annual.pk])
    assert hr.get(url).status_code == 200
    values = {"name": annual.name, "order": "0", "is_active": "on"}  # uses_annual_balance left unticked
    assert hr.post(url, values).status_code == 204
    assert LeaveTypeExt.objects.get(leave_type=annual).uses_annual_balance is False


def test_type_delete_when_unused(sick: LeaveTypeRow) -> None:
    assert _client(_in_group("Admin")).post(reverse("leave:type_delete", args=[sick.pk])).status_code == 204
    assert not LeaveTypeRow.objects.filter(pk=sick.pk).exists()


def test_edit_and_grant_forms_render(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    hr.post(reverse("leave:add"), _post(employee, annual))
    a = LeaveAssign.objects.get()
    edit = hr.get(reverse("leave:edit", args=[a.pk])).content.decode()
    assert 'name="loaded_date1" value="2026-11-02"' in edit and 'name="loaded_comment"' in edit
    assert hr.get(reverse("leave:grant", args=[employee.pk])).status_code == 200


def test_holidays_page_lists_one_line_per_date(actor: User) -> None:
    writes.set_holiday_dates(
        2026, {date(2026, 11, 26): "Тусгаар тогтнолын өдөр", date(2026, 11, 27): "Тусгаар тогтнолын өдөр"}
    )
    body = _client(_in_group("Admin")).get(reverse("leave:holidays"), {"year": "2026"}).content.decode()
    assert "2026-11-26" in body and "2026-11-27" in body


def test_huge_days_refused_not_500(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    grant = hr.post(
        reverse("leave:grant", args=[employee.pk]),
        {"start": "2026-03-01", "end": "2027-02-28", "days": "3000000000", "reason": "Захирал"},
    )
    adjust = hr.post(
        reverse("leave:adjust", args=[employee.pk, "2026-03-01", "2027-02-28"]),
        {"days": "3000000000", "reason": "Өмнө авсан"},
    )
    assert grant.status_code == 200
    assert adjust.status_code == 200
    assert not Entitlement.objects.filter(employee=employee).exists()


def test_leave_list_links_to_the_annual_leave_report() -> None:
    body = _client(_in_group("HR")).get(reverse("leave:list")).content.decode()
    assert 'href="/reports/annual-leave/"' in body and "Тайлан гаргах" in body
