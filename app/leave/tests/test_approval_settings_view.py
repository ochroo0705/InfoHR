from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees import attention
from employees.listing import employee_rows
from employees.models import Employee
from macs.models import LeaveTypeRow

from leave.models import LeaveSettings, LeaveTypeExt
from leave.services import requests
from leave.services.approvers import Rule, approvers

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105
REMOVED_TEXT = "Чөлөө батлах роль устгагдсан тул тохиргоо өөрчлөгдсөн"


def _client(user: User) -> Client:
    c = Client()
    c.force_login(user)
    return c


def _in_group(name: str) -> User:
    u = User.objects.create_user(f"u_{name}_{User.objects.count()}", password=PASSWORD)
    u.groups.add(Group.objects.get(name=name))
    return u


def _settings() -> LeaveSettings:
    return LeaveSettings.get()


def _set_step1(group: Group) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_group": group, "approval1_manager": False})


def _attention_texts(user: User) -> list[str]:
    return [a.text for a in attention.items(user, employee_rows(Employee.objects.all(), TODAY), TODAY)]


def test_settings_lists_current_roles() -> None:
    role = Group.objects.create(name="Салбарын HR")
    body = _client(_in_group("Admin")).get(reverse("leave:settings")).content.decode()
    assert "Салбарын HR" in body
    assert f'value="group:{role.pk}"' in body
    assert 'value="manager"' in body


def test_save_step1_role_and_step2_manager() -> None:
    role = Group.objects.create(name="Салбарын HR")
    resp = _client(_in_group("Admin")).post(
        reverse("leave:settings"), {"step1": f"group:{role.pk}", "step2": "manager"}
    )
    assert resp.status_code == 302
    s = _settings()
    assert s.approval1_group_id == role.pk and s.approval1_manager is False
    assert s.approval2_group_id is None and s.approval2_manager is True


def test_manager_in_step1_has_no_group() -> None:
    _client(_in_group("Admin")).post(reverse("leave:settings"), {"step1": "manager", "step2": ""})
    s = _settings()
    assert s.approval1_group_id is None and s.approval1_manager is True and s.approval_on


def test_step2_cleared_when_step1_off() -> None:
    role = Group.objects.create(name="Салбар")
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval2_group": role, "approval2_manager": True})
    _client(_in_group("Admin")).post(reverse("leave:settings"), {"step1": "", "step2": f"group:{role.pk}"})
    s = _settings()
    assert s.approval_on is False
    assert s.approval2_group_id is None and s.approval2_manager is False


def test_unknown_or_missing_group_refused() -> None:
    _set_step1(Group.objects.create(name="Анхны бүлэг"))
    before = _settings().approval1_group_id
    admin = _client(_in_group("Admin"))
    resp = admin.post(reverse("leave:settings"), {"step1": "group:999999", "step2": ""})
    assert resp.status_code == 200
    assert "step1" in resp.context["approval_form"].errors
    resp = admin.post(reverse("leave:settings"), {"step1": "group:abc", "step2": ""})
    assert resp.status_code == 200
    assert _settings().approval1_group_id == before


def test_unknown_group_in_step2_refused() -> None:
    role = Group.objects.create(name="Бүлэг")
    resp = _client(_in_group("Admin")).post(
        reverse("leave:settings"), {"step1": f"group:{role.pk}", "step2": "group:999999"}
    )
    assert resp.status_code == 200
    assert "step2" in resp.context["approval_form"].errors
    assert _settings().approval1_group_id is None


def test_settings_admin_only() -> None:
    role = Group.objects.create(name="Салбар")
    hr = _client(_in_group("HR"))
    assert hr.get(reverse("leave:settings")).status_code == 403
    assert hr.post(reverse("leave:settings"), {"step1": f"group:{role.pk}", "step2": ""}).status_code == 403
    assert _settings().approval1_group_id is None


def test_auto_annual_grant_switch_still_saves() -> None:
    admin = _client(_in_group("Admin"))
    assert admin.post(reverse("leave:settings"), {"auto_annual_grant": "on"}).status_code == 302
    assert _settings().auto_annual_grant is True


def test_approval_save_does_not_touch_auto_grant() -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    _client(_in_group("Admin")).post(reverse("leave:settings"), {"step1": "manager", "step2": ""})
    assert _settings().auto_annual_grant is True


def test_type_form_saves_staff_may_request(annual: LeaveTypeRow) -> None:
    admin = _client(_in_group("Admin"))
    url = reverse("leave:type_edit", args=[annual.pk])
    assert b'name="staff_may_request"' in admin.get(url).content
    assert admin.post(url, {"name": annual.name, "order": "0", "is_active": "on"}).status_code == 204
    assert LeaveTypeExt.objects.get(leave_type=annual).staff_may_request is False
    on = {"name": annual.name, "order": "0", "is_active": "on", "staff_may_request": "on"}
    assert admin.post(url, on).status_code == 204
    assert LeaveTypeExt.objects.get(leave_type=annual).staff_may_request is True


def test_new_type_defaults_to_staff_may_request() -> None:
    admin = _client(_in_group("Admin"))
    values = {"name": "Шинэ", "order": "0", "is_active": "on", "staff_may_request": "on"}
    assert admin.post(reverse("leave:type_add"), values).status_code == 204
    assert LeaveTypeExt.objects.get(leave_type__name="Шинэ").staff_may_request is True


def test_saving_approval_form_clears_removed_flag() -> None:
    role = Group.objects.create(name="Салбар")
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval_role_removed": True})
    _client(_in_group("Admin")).post(reverse("leave:settings"), {"step1": f"group:{role.pk}", "step2": ""})
    assert _settings().approval_role_removed is False


def test_deleting_unrelated_role_sets_no_flag() -> None:
    selected = Group.objects.create(name="Сонгосон")
    other = Group.objects.create(name="Бусад")
    _set_step1(selected)
    other.delete()
    assert _settings().approval_role_removed is False
    assert _settings().approval1_group_id == selected.pk


def test_deleting_selected_role_turns_step_off(sick: LeaveTypeRow, employee: Employee, actor: User) -> None:
    role = Group.objects.create(name="Салбарын HR")
    _set_step1(role)
    req = requests.submit(employee, sick, date(2026, 11, 2), date(2026, 11, 3), "", actor, TODAY)

    role.delete()

    s = _settings()
    assert s.approval_on is False
    assert s.approval_role_removed is True
    assert REMOVED_TEXT in _attention_texts(_in_group("Admin"))
    req.refresh_from_db()
    assert approvers(req, TODAY).rule == Rule.FALLBACK


def test_deleting_selected_step2_role_keeps_step1() -> None:
    first = Group.objects.create(name="Нэг")
    second = Group.objects.create(name="Хоёр")
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_group": first, "approval2_group": second})
    second.delete()
    s = _settings()
    assert s.approval_on is True and s.approval1_group_id == first.pk
    assert s.approval2_group_id is None
    assert s.approval_role_removed is True


def test_attention_item_for_admin_only() -> None:
    role = Group.objects.create(name="Салбар")
    _set_step1(role)
    role.delete()
    assert REMOVED_TEXT in _attention_texts(_in_group("Admin"))
    assert REMOVED_TEXT not in _attention_texts(_in_group("HR"))


def test_attention_item_clears_after_save() -> None:
    role = Group.objects.create(name="Салбар")
    _set_step1(role)
    role.delete()
    admin = _in_group("Admin")
    _client(admin).post(reverse("leave:settings"), {"step1": "manager", "step2": ""})
    assert REMOVED_TEXT not in _attention_texts(admin)


def test_type_form_explains_order_and_checkboxes(annual: LeaveTypeRow) -> None:
    body = _client(_in_group("Admin")).get(reverse("leave:type_edit", args=[annual.pk])).content.decode()
    assert "Жагсаалтад гарах дараалал" in body
    assert "Тэмдэглэгээ: энэ төрлийн чөлөө цалинтай эсэхийг харуулна." in body
    assert "Авсан хоног ээлжийн амралтын эрх, үлдэгдлээс хасагдана." in body
    assert "Унтраавал чөлөө бүртгэх жагсаалтад энэ төрөл харагдахгүй." in body
    assert "Унтраавал ажилтан өөрөө хүсэлт гаргаж чадахгүй; HR шууд бүртгэнэ." in body
