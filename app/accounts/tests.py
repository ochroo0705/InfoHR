import copy
import re

import pytest
from django.contrib.auth.models import Group
from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import path

from accounts.models import User
from accounts.roles import DEFAULT_SWITCHES, EMPLOYEE, HR, ROLE_LABELS


@pytest.mark.django_db
def test_role_groups_exist_with_default_switches() -> None:
    for name, codes_expected in DEFAULT_SWITCHES.items():
        group = Group.objects.get(name=name)
        codes = group.permissions.filter(content_type__app_label="accounts").values_list("codename", flat=True)
        assert set(codes) == set(codes_expected)


@pytest.mark.django_db
def test_new_user_gets_employee_role_only() -> None:
    user = User.objects.create_user("bat", password="x-long-pass-123")
    assert list(user.groups.values_list("name", flat=True)) == [EMPLOYEE]
    assert not user.has_perm("macs.view_salary")


@pytest.mark.django_db
def test_hr_cannot_see_salary_until_switched_on() -> None:
    user = User.objects.create_user("hr1", password="x-long-pass-123")
    user.groups.add(Group.objects.get(name=HR))
    assert user.has_perm("accounts.approve_leave")
    assert not User.objects.get(pk=user.pk).has_perm("macs.view_salary")


@pytest.mark.django_db
def test_permission_labels_are_mongolian() -> None:
    from django.contrib.auth.models import Permission
    from django.utils import translation

    from accounts.admin import permission_label

    with translation.override("mn"):
        add_user = permission_label(Permission.objects.get(codename="add_user"))
        approve = permission_label(Permission.objects.get(codename="approve_leave"))
    assert add_user == "Нэмэх"
    assert approve == "Чөлөө, амралт батлах"


@pytest.mark.django_db
def test_role_editor_groups_permissions_into_cards() -> None:
    from django.utils import translation

    from accounts.admin import permission_formfield

    with translation.override("mn"):
        field = copy.deepcopy(permission_formfield())  # forms copy their fields; grouping must survive
        groups = [group for group, _options in field.widget.choices]
    assert groups == [
        "Үйл ажиллагааны эрх",
        "Ажилтан",
        "Даалгаврын жагсаалт",
        "Чөлөө, амралт",
        "Жагсаалтууд",
        "Ажилд авах",
        "Тайлан",
    ]
    switches = {label for _value, label in field.widget.choices[0][1]}
    assert switches == {
        "Чөлөө, амралт батлах",
        "Тушаал гаргах / баталгаажуулах",
        "Жагсаалтыг Excel рүү гаргах",
        "Үйл ажиллагааны бүртгэл харах",
    }
    employee_card = {label for _value, label in field.widget.choices[1][1]}
    assert "Цалин, даатгалын мэдээллийг харах" in employee_card
    checklist_card = {label for _value, label in field.widget.choices[2][1]}
    assert checklist_card == {"Жагсаалтын загвар засах", "Жагсаалт дуусаагүй байхад ажлаас гаргах"}
    leave_card = {label for _value, label in field.widget.choices[3][1]}
    assert leave_card == {"Чөлөө харах", "Чөлөө бүртгэх", "Чөлөөний тохиргоо", "Өөрийн чөлөө хүсэх"}
    lists_card = {label for _value, label in field.widget.choices[4][1]}
    assert lists_card == {"Жагсаалт засах"}
    recruitment_card = {label for _value, label in field.widget.choices[5][1]}
    assert recruitment_card == {"Ажилд авах ажил удирдах"}


@pytest.mark.django_db
def test_role_editor_skips_permissions_of_removed_apps() -> None:
    """A removed app (payroll, D-038) leaves its permission rows behind; the role editor must not crash on them."""
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from accounts.admin import permission_formfield, permission_queryset

    gone = ContentType.objects.create(app_label="payroll", model="payrollrule")
    stale = Permission.objects.create(content_type=gone, codename="manage_payroll_settings", name="Цалингийн тохиргоо")
    assert stale not in permission_queryset()
    assert permission_formfield().widget.choices  # building the cards does not raise


def test_full_name_is_family_name_first() -> None:
    assert User(first_name="Сарантуяа", last_name="Ганбатын").get_full_name() == "Ганбатын Сарантуяа"
    assert User(first_name="Систем").get_full_name() == "Систем"


@pytest.mark.django_db
def test_403_page_is_mongolian_with_a_link_home() -> None:
    """An employee without the reports right sees the friendly 403 page, not Django's bare one."""
    from django.test import Client

    user = User.objects.create_user("staff403", password="x-long-pass-123")
    client = Client()
    client.force_login(user)
    response = client.get("/reports/")
    body = response.content.decode()
    assert response.status_code == 403
    assert "Хандах эрх байхгүй" in body
    assert re.search(r'href="/"[^>]*>\s*Нүүр хуудас руу буцах', body)
    assert "PermissionDenied" not in body  # the exception text is never printed


@pytest.mark.django_db
def test_404_page_is_mongolian() -> None:
    from django.test import Client

    user = User.objects.create_user("staff404", password="x-long-pass-123")
    client = Client()
    client.force_login(user)
    response = client.get("/no-such-page-here/")
    body = response.content.decode()
    assert response.status_code == 404
    assert "Хуудас олдсонгүй" in body
    assert re.search(r'href="/"[^>]*>\s*Нүүр хуудас руу буцах', body)


def _boom(request: HttpRequest) -> HttpResponse:
    raise RuntimeError("boom for the 500 page test")


urlpatterns = [path("boom-for-500-test/", _boom)]  # used only through override_settings below


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="accounts.tests")
def test_500_page_is_static_mongolian() -> None:
    from django.test import Client

    response = Client(raise_request_exception=False).get("/boom-for-500-test/")
    body = response.content.decode()
    assert response.status_code == 500
    assert "Системд алдаа гарлаа" in body
    assert 'href="/"' in body
    assert "boom for the 500 page test" not in body  # the error text is never shown
    assert "{%" not in body and "{{" not in body  # static: no template tags were left unrendered


def test_role_labels_are_mongolian() -> None:
    assert ROLE_LABELS == {
        "Accountant": "Нягтлан",
        "Admin": "Админ",
        "Auditor": "Аудитор",
        "Employee": "Ажилтан",
        "HR": "Хүний нөөц",
    }


@pytest.mark.django_db
def test_login_inputs_have_labels() -> None:
    from django.test import Client
    from django.urls import reverse

    body = Client().get(reverse("login")).content.decode()
    assert 'for="id_username"' in body and 'id="id_username"' in body
    assert 'for="id_password"' in body and 'id="id_password"' in body
