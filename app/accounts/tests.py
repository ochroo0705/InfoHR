import copy

import pytest
from django.contrib.auth.models import Group

from accounts.models import User
from accounts.roles import DEFAULT_SWITCHES, EMPLOYEE, HR


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
    assert not user.has_perm("employees.view_salary")


@pytest.mark.django_db
def test_hr_cannot_see_salary_until_switched_on() -> None:
    user = User.objects.create_user("hr1", password="x-long-pass-123")
    user.groups.add(Group.objects.get(name=HR))
    assert user.has_perm("accounts.approve_leave")
    assert not User.objects.get(pk=user.pk).has_perm("employees.view_salary")


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
    assert groups == ["Үйл ажиллагааны эрх", "Ажилтан"]
    switches = {label for _value, label in field.widget.choices[0][1]}
    assert switches == {"Чөлөө, амралт батлах", "Тушаал гаргах / баталгаажуулах", "Жагсаалтыг Excel рүү гаргах"}
    employee_card = {label for _value, label in field.widget.choices[1][1]}
    assert "Цалин, даатгалын мэдээллийг харах" in employee_card


def test_full_name_is_family_name_first() -> None:
    assert User(first_name="Сарантуяа", last_name="Ганбатын").get_full_name() == "Ганбатын Сарантуяа"
    assert User(first_name="Систем").get_full_name() == "Систем"
