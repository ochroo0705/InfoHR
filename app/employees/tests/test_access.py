import pytest
from accounts.models import User
from django.contrib.auth.models import AnonymousUser, Group, Permission

from employees import access
from employees.models import ActivityEntry, Employee

pytestmark = pytest.mark.django_db


def user_in(role: str, name: str = "u") -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def test_hr_sees_all_but_not_salary(hired: Employee) -> None:
    hr = user_in("HR")
    assert list(access.visible_employees(hr)) == [hired]
    assert access.can_manage(hr) and access.can_view_personal(hr, hired)
    assert not access.can_view_salary(hr)
    assert not access.visible_activity(hr, hired).filter(sensitive=True).exists()


def test_hr_with_switch_sees_salary(hired: Employee) -> None:
    group = Group.objects.get(name="HR")
    group.permissions.add(Permission.objects.get(codename="view_salary"))
    assert access.can_view_salary(user_in("HR"))


def test_accountant(hired: Employee) -> None:
    acc = user_in("Accountant")
    assert access.can_view_salary(acc) and access.can_manage_salary(acc)
    assert not access.can_manage(acc) and not access.can_view_personal(acc, hired)


def test_employee_sees_only_self_without_notes_or_salary(hired: Employee) -> None:
    me = user_in("Employee", "me")
    hired.user = me
    hired.save()
    ActivityEntry.objects.create(employee=hired, kind="note", message="internal")
    me = User.objects.get(pk=me.pk)
    assert list(access.visible_employees(me)) == [hired]
    assert access.can_view_personal(me, hired) and not access.can_view_salary(me)
    kinds = set(access.visible_activity(me, hired).values_list("kind", flat=True))
    assert "note" not in kinds and not access.visible_activity(me, hired).filter(sensitive=True).exists()


def test_employee_role_without_linked_record(hired: Employee) -> None:
    lonely = user_in("Employee", "lonely")
    assert not access.visible_employees(lonely).exists()
    assert not access.is_own(lonely, hired)


def test_inactive_employee_loses_own_record(hired: Employee) -> None:
    me = user_in("Employee", "gone")
    hired.user = me
    hired.save()
    me = User.objects.get(pk=me.pk)
    me.is_active = False
    me.save()
    assert not access.visible_employees(me).exists()
    assert not access.is_own(me, hired)
    assert not access.can_view_personal(me, hired)


def test_inactive_superuser_sees_nothing(hired: Employee) -> None:
    su = User.objects.create_superuser("su_off", "su_off@example.com", "x-long-pass-123", is_active=False)  # noqa: S106
    assert not access.visible_employees(su).exists()
    assert not access.can_view_salary(su)
    assert not access.visible_activity(su, hired).exists()


def test_active_superuser_sees_all_and_salary(hired: Employee) -> None:
    su = User.objects.create_superuser("su_on", "su_on@example.com", "x-long-pass-123")  # noqa: S106
    assert list(access.visible_employees(su)) == [hired]
    assert access.can_view_salary(su)


def test_direct_view_salary_permission(hired: Employee) -> None:
    user = User.objects.create_user("direct", password="x-long-pass-123")  # noqa: S106
    user.user_permissions.add(Permission.objects.get(codename="view_salary"))
    user = User.objects.get(pk=user.pk)
    assert access.can_view_salary(user)


def test_anonymous_user_sees_nothing(hired: Employee) -> None:
    anon = AnonymousUser()
    assert not access.visible_employees(anon).exists()  # type: ignore[arg-type]
    assert not access.is_own(anon, hired)  # type: ignore[arg-type]


def test_accountant_sees_salary_and_notes_in_activity(hired: Employee) -> None:
    ActivityEntry.objects.create(employee=hired, kind="note", message="internal")
    acc = user_in("Accountant", "acc_log")
    kinds = set(access.visible_activity(acc, hired).values_list("kind", flat=True))
    assert "note" in kinds
    assert access.visible_activity(acc, hired).filter(sensitive=True).exists()


def test_can_manage_salary_requires_view_salary(hired: Employee) -> None:
    direct = User.objects.create_user("manage_only", password="x-long-pass-123")  # noqa: S106
    direct.user_permissions.add(Permission.objects.get(codename="manage_salary"))
    direct = User.objects.get(pk=direct.pk)
    assert not access.can_manage_salary(direct)
    assert not access.can_manage_salary(user_in("HR", "hr_ms"))
    assert not access.can_manage_salary(user_in("Employee", "emp_ms"))


def test_personal_activity_filter(hired: Employee) -> None:
    from employees.models import ActivityKind

    ActivityEntry.objects.create(employee=hired, kind=ActivityKind.CHANGED, message="p", personal=True)
    assert not access.visible_activity(user_in("Accountant", "acc"), hired).filter(personal=True).exists()
    assert access.visible_activity(user_in("HR", "hr"), hired).filter(personal=True).exists()
