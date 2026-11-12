"""The optional modules (accounts/modules.py): admin switches, permission switch-off, the 404 gate, data kept."""

import json

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import CompanySettings

from accounts import modules
from accounts.models import User
from accounts.roles import ADMIN, HR

pytestmark = pytest.mark.django_db


def _user(name: str, role: str, **extra: object) -> User:
    user = User.objects.create_user(name, password="x", is_active=True, **extra)
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def _login(role: str, name: str) -> tuple[Client, User]:
    client = Client()
    user = _user(name, role)
    client.force_login(user)
    return client, user


def test_every_module_is_on_by_default() -> None:
    assert modules.state() == {"slots": True, "recruitment": True}
    assert modules.enabled("slots") and modules.enabled("anything-unknown")


def test_set_state_keeps_the_other_modules_and_ignores_unknown_keys() -> None:
    modules.set_state({"slots": False, "nonsense": False})
    assert modules.state() == {"slots": False, "recruitment": True}
    assert json.loads(CompanySettings.get().modules) == {"slots": False}
    modules.set_state({"recruitment": False})
    assert modules.state() == {"slots": False, "recruitment": False}


def test_a_bad_stored_text_reads_as_everything_on() -> None:
    CompanySettings.objects.update_or_create(pk=1, defaults={"modules": "not json"})
    modules.clear_cache()
    assert modules.state() == {"slots": True, "recruitment": True}


def test_off_modules_withdraw_their_rights_even_from_a_superuser() -> None:
    boss = _user("mod_super", ADMIN, is_superuser=True)
    assert boss.has_perm("employees.manage_position_slots") and boss.has_perm("recruitment.manage_recruitment")
    modules.set_state({"slots": False, "recruitment": False})
    for perm in (
        "employees.manage_position_slots",
        "employees.override_position_slots",
        "recruitment.manage_recruitment",
    ):
        assert not User.objects.get(pk=boss.pk).has_perm(perm), perm
    assert User.objects.get(pk=boss.pk).has_perm("macs.view_employees")  # an unrelated right is untouched
    assert not boss.has_module_perms("recruitment")


def test_pages_of_an_off_module_answer_404_and_come_back_when_it_is_on_again() -> None:
    client, _ = _login(ADMIN, "mod_admin")
    assert client.get(reverse("employees:slots")).status_code == 200
    assert client.get(reverse("recruitment:vacancies")).status_code == 200
    modules.set_state({"slots": False, "recruitment": False})
    assert client.get(reverse("employees:slots")).status_code == 404
    assert client.get(reverse("recruitment:vacancies")).status_code == 404
    assert client.get(reverse("employees:list")).status_code == 302  # the core stays (opens the staff report)
    modules.set_state({"slots": True, "recruitment": True})
    assert client.get(reverse("employees:slots")).status_code == 200


def test_menu_drops_the_links_of_an_off_module() -> None:
    client, _ = _login(ADMIN, "mod_menu")
    page = client.get(reverse("employees:today")).content.decode()
    assert "Орон тооны төлөвлөгөө" in page and reverse("recruitment:vacancies") in page
    modules.set_state({"slots": False, "recruitment": False})
    page = client.get(reverse("employees:today")).content.decode()
    assert "Орон тооны төлөвлөгөө" not in page and reverse("recruitment:vacancies") not in page


def test_engineers_report_follows_the_slots_module() -> None:
    client, _ = _login(HR, "mod_hr")
    assert client.get("/reports/engineers/").status_code == 200
    modules.set_state({"slots": False})
    assert client.get("/reports/engineers/").status_code == 403


def test_old_modules_address_is_gone() -> None:
    client, _ = _login(ADMIN, "mod_old")
    assert client.get("/modules/").status_code == 404


def _settings_form(row: CompanySettings, **extra: str) -> dict[str, object]:
    return {
        "name": row.name,
        "director_name": row.director_name,
        "selfform_base_url": row.selfform_base_url,
        "selfform_notice": row.selfform_notice,
        "selfform_retention_days": row.selfform_retention_days,
        "selfform_default_hours": row.selfform_default_hours,
        **extra,
    }


def test_admin_switches_modules_on_the_company_settings_page() -> None:
    row = CompanySettings.get()
    client = Client()
    client.force_login(User.objects.create_superuser("mod_super", password="x"))  # noqa: S106 (test user)
    url = reverse("admin:employees_companysettings_change", args=[row.pk])
    page = client.get(url).content.decode()
    assert "module_slots" in page and "module_recruitment" in page
    response = client.post(url, _settings_form(row, module_recruitment="on"))  # slots left unticked = off
    assert response.status_code == 302
    assert modules.state() == {"slots": False, "recruitment": True}
