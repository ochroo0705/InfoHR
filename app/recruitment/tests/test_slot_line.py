"""The budget line on a vacancy: advisory, read from the slot rules, shown only with the slot switch on."""

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees.models import CompanySettings
from employees.services import slots
from macs.models import Branch, NazgRow, Position

from recruitment.models import Vacancy
from recruitment.services import slot_line

from .conftest import make_vacancy

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year


def _switch(on: bool = True) -> None:
    row = CompanySettings.get()
    row.enforce_position_slots = on
    row.save()


@pytest.fixture
def branch() -> Branch:
    return Branch.objects.create(name="Төв салбар")


@pytest.fixture
def position() -> Position:
    return Position.objects.create(name="Нягтлан")


def _posts(position: Position, branch: Branch, qty: int) -> None:
    NazgRow.objects.create(kind="Main", qty=qty, year=YEAR, position=position, branch=branch)


def _describe(position: Position, branch: Branch | None, headcount: int = 1, exclude: int | None = None):  # type: ignore[no-untyped-def]
    return slot_line.describe(
        position=position, branch=branch, start=None, headcount=headcount, exclude_vacancy=exclude
    )


def test_nothing_is_shown_while_the_switch_is_off(position: Position, branch: Branch) -> None:
    _posts(position, branch, 3)
    assert _describe(position, branch) is None


def test_free_post_shows_numbers_and_no_warning(position: Position, branch: Branch) -> None:
    _switch()
    _posts(position, branch, 3)
    line = _describe(position, branch)
    assert line is not None
    assert "орон тоо 3 · ажиллаж буй 0 · сул 3" in line.numbers
    assert line.warning == ""


def test_no_budget_row_says_no_posts_are_planned(position: Position, branch: Branch) -> None:
    _switch()  # posts == 0: not "no free post left" but "none planned", with the hint to add one
    line = _describe(position, branch)
    assert line is not None
    assert "төлөвлөөгүй" in line.warning and "Орон тооны төлөвлөгөө» хэсэгт" in line.warning
    assert "алга" not in line.warning


def test_full_posts_still_say_no_free_post_is_left(
    position: Position, branch: Branch, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch()
    _posts(position, branch, 1)  # a planned post that is already taken: posts 1, used 1, free 0
    full = slots.SlotResult(kind="Main", year=YEAR, posts=1, used=1, free=0)
    monkeypatch.setattr(slots, "check", lambda *args, **kwargs: full)
    line = _describe(position, branch)
    assert line is not None and line.warning == "Сул орон тоо алга."


def test_over_filled_posts_never_show_a_negative_free_count(
    position: Position, branch: Branch, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch()
    over = slots.SlotResult(kind="Main", year=YEAR, posts=0, used=1, free=-1)
    monkeypatch.setattr(slots, "check", lambda *args, **kwargs: over)
    line = _describe(position, branch)
    assert line is not None and "сул 0" in line.numbers and "-1" not in line.numbers


def test_headcount_above_free_posts_warns(position: Position, branch: Branch) -> None:
    _switch()
    _posts(position, branch, 2)
    line = _describe(position, branch, headcount=3)
    assert line is not None and "хүрэхгүй" in line.warning


def test_no_branch_asks_for_one(position: Position) -> None:
    _switch()
    line = _describe(position, None)
    assert line is not None and line.numbers == "" and "салбар сонгоно уу" in line.warning


def test_another_open_vacancy_reserves_the_post(position: Position, branch: Branch) -> None:
    _switch()
    _posts(position, branch, 1)
    other = make_vacancy("Нягтлан 2")
    other.branch = branch
    other.save()
    line = _describe(position, branch)
    assert line is not None and "өөр нээлттэй" in line.warning
    assert _describe(position, branch, exclude=other.pk).warning == ""  # type: ignore[union-attr]  # its own line ignores itself


def test_endpoint_needs_the_manage_right(client: Client, actor: User, hr_user: User) -> None:
    url = reverse("recruitment:vacancy_slot_line")
    client.force_login(actor)
    assert client.get(url).status_code == 403
    client.force_login(hr_user)
    assert client.get(url).status_code == 200


def test_popup_live_check_sends_only_the_four_fields(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)
    html = client.get(reverse("recruitment:vacancy_add")).content.decode()
    assert 'id="vacancy-form"' in html
    include = html.split('hx-include="')[1].split('"')[0]
    assert all(f"[name={name}]" in include for name in ("position", "branch", "desired_start", "headcount"))
    assert "csrf" not in include  # the token must not travel in the GET query string


def test_endpoint_and_page_show_the_line(client: Client, hr_user: User, position: Position, branch: Branch) -> None:
    _switch()
    _posts(position, branch, 1)
    vacancy: Vacancy = make_vacancy()
    vacancy.branch = branch
    vacancy.save()
    client.force_login(hr_user)
    params = {"position": position.pk, "branch": branch.pk, "headcount": 1}
    assert "сул 1" in client.get(reverse("recruitment:vacancy_slot_line"), params).content.decode()
    assert "сул 1" in client.get(reverse("recruitment:vacancy_detail", args=[vacancy.pk])).content.decode()
