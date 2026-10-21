"""QC 3c: the "died" reason needs the Lists meaning "fired_reason.death" to be configured."""

from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from lists.models import DEATH, MeaningfulEntry
from macs.models import FiredReason

from employees import attention
from employees.listing import employee_rows
from employees.models import Employee, Event, EventType

from .conftest import named
from .test_views import login_as

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)
WARNING = (
    "«Нас барсан» шалтгааныг Жагсаалт → Утгатай бичлэг хэсэгт тохируулаагүй байна. "
    "Тохируулах хүртэл ажлаас гарсныг «нас барсан» гэж бүртгэхгүй."
)


def url(emp: Employee, type: str) -> str:
    return f"/employees/{emp.pk}/event/{type}/"


def user_in(role: str, name: str = "u1") -> User:
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return u


def death_items(user: User) -> list[attention.Attention]:
    found = attention.items(user, employee_rows(Employee.objects.none(), TODAY), TODAY)
    return [a for a in found if a.kind == "lists_death"]


def set_death(value: int | None) -> None:
    if value is None:
        MeaningfulEntry.objects.filter(key=DEATH).delete()
    else:
        MeaningfulEntry.objects.update_or_create(key=DEATH, defaults={"value": value})


# --- termination form warning -------------------------------------------------


def test_termination_form_warns_when_death_meaning_unset(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    set_death(None)
    body = client.get(url(hired, "termination")).content.decode()
    assert WARNING in body


def test_termination_form_no_warning_when_death_meaning_set(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    set_death(named(FiredReason, "Нас барсан").pk)
    body = client.get(url(hired, "termination")).content.decode()
    assert WARNING not in body


def test_other_event_form_has_no_death_warning(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    set_death(None)
    body = client.get(url(hired, "promotion")).content.decode()
    assert WARNING not in body


def test_termination_save_still_allowed_when_unset(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    set_death(None)
    reason = named(FiredReason, "Өөрийн хүсэлтээр")
    response = client.post(
        url(hired, "termination"),
        {"effective": date(2026, 10, 20).isoformat(), "fired_reason": reason.pk, "note": ""},
    )
    assert response.status_code == 204  # _done(): saved
    assert Event.objects.filter(employee=hired, type=EventType.TERMINATION).exists()


# --- attention item -----------------------------------------------------------


def test_attention_item_for_lists_manager_when_unset() -> None:
    set_death(None)
    items = death_items(user_in("HR"))
    assert len(items) == 1
    assert items[0].employee is None
    assert items[0].url == reverse("lists:meaning")


def test_attention_item_absent_when_set() -> None:
    set_death(named(FiredReason, "Нас барсан").pk)
    assert death_items(user_in("HR")) == []


def test_attention_item_absent_without_lists_permission() -> None:
    set_death(None)
    assert death_items(user_in("Accountant")) == []


def test_attention_box_shows_link_to_lists_meaning(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    set_death(None)
    body = client.get(reverse("employees:list")).content.decode()
    assert "Жагсаалтын утга дутуу" in body
    assert f'href="{reverse("lists:meaning")}"' in body


def test_system_item_cannot_be_dismissed_and_has_no_dismiss_button(client: Client, hired: Employee) -> None:
    from employees.models import AttentionDismissal

    set_death(None)
    user = user_in("HR")
    attention.dismiss(user, death_items(user)[0])  # no crash, nothing stored
    assert not AttentionDismissal.objects.filter(user=user).exists()
    client.force_login(user)
    response = client.post(reverse("employees:attention"), {"key": death_items(user)[0].key, "action": "dismiss"})
    assert response.status_code == 200
