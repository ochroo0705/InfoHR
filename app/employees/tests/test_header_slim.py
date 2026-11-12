"""The employee page header stops repeating the key facts at lg and up (plan 2026-11-09-employee-page-one-scroll, T5).

At lg and up the facts card in the rail is the permanent home of the key facts, so the header's four-fact strip is
hidden there (lg:hidden) and shown only below lg, where the rail does not exist. The contract end and the employee
type stay visible in the Work section for lg users.
"""

from pathlib import Path

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client

from employees.models import Employee

DETAIL_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "employees" / "detail.html"
STRIP_LABELS = ("Ажилд орсон", "Ажилтны төрөл", "Гэрээ дуусах", "Шууд удирдлага")


def login_as(client: Client, role: str, name: str = "viewer") -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def _page(client: Client, employee: Employee) -> str:
    login_as(client, "HR")
    return client.get(f"/employees/{employee.pk}/").content.decode()


def _header_strip(body: str) -> tuple[str, str]:
    """The opening tag of the four-fact strip, and the strip's text (up to the tab card that follows the header)."""
    start = body.index('<div class="mt-4 grid grid-cols-2')
    end = body.index('<div class="mt-6 rounded-xl border border-slate-200 bg-surface">', start)
    return body[start : body.index(">", start) + 1], body[start:end]


@pytest.mark.django_db
def test_header_strip_is_hidden_at_lg_and_up(client: Client, hired: Employee) -> None:
    tag, strip = _header_strip(_page(client, hired))
    assert "lg:hidden" in tag.split()
    for label in STRIP_LABELS:
        assert label in strip


@pytest.mark.django_db
def test_rail_card_is_not_hidden_on_first_view(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    start = body.index('<div id="rail-who"')
    tag = body[start : body.index(">", start) + 1]
    assert "hidden" not in tag.split()


def test_detail_has_no_rail_name_toggle() -> None:
    text = DETAIL_TEMPLATE.read_text(encoding="utf-8")
    assert "IntersectionObserver" not in text
    assert "rail-who" not in text


@pytest.mark.django_db
def test_work_section_shows_contract_end_and_employee_type(client: Client, hired: Employee) -> None:
    body = _page(client, hired)
    start = body.index('id="tab-work"')
    end = body.index('<section id="tab-', start + 1)
    work = body[start:end]
    assert "Гэрээ дуусах" in work
    assert "Ажилтны төрөл" in work
