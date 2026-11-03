"""Convert to employee: the redirect and its prefill, who may use it, and the button (Review Focus 2, 3)."""

from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from macs.models import Branch, Employee

from recruitment.models import Candidate, Stage, Vacancy
from recruitment.services import convert, pipeline

from .conftest import make_manager, make_vacancy


def _login(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def hr(hr_user: User) -> User:
    hr_user.groups.add(Group.objects.get(name="HR"))  # the hire form needs the employee right too
    return hr_user


def _url(candidate: Candidate) -> str:
    return reverse("recruitment:candidate_convert", args=[candidate.pk])


def test_convert_redirects_to_hire_form_with_prefill(hr: User, vacancy: Vacancy, actor: User) -> None:
    vacancy.desired_start = timezone.localdate() + timedelta(days=10)
    vacancy.deadline = timezone.localdate() + timedelta(days=3)
    vacancy.branch = Branch.objects.first() or Branch.objects.create(name="Төв")
    vacancy.save()
    cand = pipeline.add_candidate(
        vacancy, by=actor, surname="Дорж", given_name="Бат", phone="99112233", email="bat@example.mn"
    )
    response = _login(hr).get(_url(cand))
    assert response.status_code == 302
    target = urlparse(response["Location"])
    assert target.path == reverse("employees:add")
    q = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert q["family_name"] == "Дорж" and q["given_name"] == "Бат"
    assert q["private_phone"] == "99112233" and q["email"] == "bat@example.mn"
    assert q["position"] == str(vacancy.position_id) and q["department"] == str(vacancy.department_id)
    assert q["branch"] == str(vacancy.branch_id)
    assert q["start"] == vacancy.desired_start.isoformat()
    assert q["candidate"] == str(cand.pk)


def test_start_suggestion_is_today_unless_desired_start_is_future(candidate: Candidate, vacancy: Vacancy) -> None:
    today = date(2026, 11, 2)
    vacancy.deadline = date(2026, 12, 15)  # the deadline is never used for the start date
    assert convert.prefill_params(candidate, today)["start"] == "2026-11-02"  # no desired start
    vacancy.desired_start = date(2026, 10, 1)
    assert convert.prefill_params(candidate, today)["start"] == "2026-11-02"  # in the past
    vacancy.desired_start = today
    assert convert.prefill_params(candidate, today)["start"] == "2026-11-02"  # today is not "in the future"
    vacancy.desired_start = date(2026, 12, 1)
    assert convert.prefill_params(candidate, today)["start"] == "2026-12-01"


def test_hire_form_shows_the_prefill_and_carries_the_candidate(hr: User, candidate: Candidate) -> None:
    candidate.phone, candidate.email = "99112233", "bat@example.mn"
    candidate.save()
    page = _login(hr).get(_url(candidate), follow=True)
    body = page.content.decode()
    assert page.status_code == 200
    assert 'value="Дорж"' in body and 'value="Бат"' in body
    assert 'value="99112233"' in body and 'value="bat@example.mn"' in body
    assert f'name="candidate" value="{candidate.pk}"' in body
    assert page.context["person"]["family_name"].value() == "Дорж"
    assert page.context["job"]["position"].value() == candidate.vacancy.position_id


def test_hiring_manager_cannot_convert(actor: User) -> None:
    manager_user, manager_emp = make_manager(actor, "mgr_c", "УБ10000003")
    cand = pipeline.add_candidate(make_vacancy("Вакансий", manager=manager_emp), by=actor, surname="А", given_name="Б")
    assert _login(manager_user).get(_url(cand)).status_code == 403  # sees it, may not convert


def test_stranger_gets_404_on_convert(candidate: Candidate) -> None:
    other = User.objects.create_user("stranger", password="x-long-pass-123")  # noqa: S106
    assert _login(other).get(_url(candidate)).status_code == 404


@pytest.mark.parametrize("closing", ["reject", "withdraw", "hired"])
def test_closed_or_hired_candidate_cannot_be_converted(
    hr: User, candidate: Candidate, actor: User, new_employee: Employee, closing: str
) -> None:
    if closing == "reject":
        pipeline.reject(candidate, by=actor, reason="Тохирохгүй")
    elif closing == "withdraw":
        pipeline.reject(candidate, by=actor, reason="", withdrawn=True)
    else:
        pipeline.mark_hired(candidate, new_employee, by=actor)
    response = _login(hr).get(_url(candidate), follow=True)
    assert response.redirect_chain[0][0] == reverse("recruitment:candidate_detail", args=[candidate.pk])
    assert "Энэ ажил хүсэгчийг ажилтан болгох боломжгүй" in response.content.decode()


@pytest.mark.parametrize("status", ["closed", "filled"])
def test_candidate_of_non_open_vacancy_cannot_be_converted(
    hr: User, candidate: Candidate, actor: User, status: str
) -> None:
    Vacancy.objects.filter(pk=candidate.vacancy_id).update(status=status)
    candidate.refresh_from_db()
    assert not convert.can_convert(candidate)
    assert convert.convertible(hr, str(candidate.pk)) is None
    page = reverse("recruitment:candidate_detail", args=[candidate.pk])
    assert _url(candidate) not in _login(hr).get(page).content.decode()
    response = _login(hr).get(_url(candidate), follow=True)
    body = response.content.decode()
    assert response.redirect_chain[0][0] == page
    assert "нээлттэй биш" in body
    # moves and rejection stay allowed on a closed vacancy
    pipeline.move(candidate, Stage.SCREENING, by=actor)
    pipeline.reject(candidate, by=actor, reason="Тохирохгүй")


def test_convert_is_get_only(hr: User, candidate: Candidate) -> None:
    assert _login(hr).post(_url(candidate)).status_code == 405


def test_convertible_rules(hr: User, candidate: Candidate, actor: User) -> None:
    assert convert.convertible(hr, str(candidate.pk)) == candidate
    for bad in ("", "abc", "0", "-1", "99999999", None, "1e3"):
        assert convert.convertible(hr, bad) is None
    other = User.objects.create_user("nobody", password="x-long-pass-123")  # noqa: S106
    assert convert.convertible(other, str(candidate.pk)) is None  # cannot see it, cannot manage
    pipeline.move(candidate, Stage.OFFER, by=actor)
    assert convert.convertible(hr, str(candidate.pk)) is not None  # any non-closed stage


def test_hiring_manager_is_not_a_converter(actor: User) -> None:
    manager_user, manager_emp = make_manager(actor, "mgr_d", "УБ10000004")
    cand = pipeline.add_candidate(make_vacancy("В", manager=manager_emp), by=actor, surname="А", given_name="Б")
    assert convert.convertible(manager_user, str(cand.pk)) is None


def test_candidate_page_button_for_managers_only(hr: User, candidate: Candidate, actor: User) -> None:
    manager_user, manager_emp = make_manager(actor, "mgr_e", "УБ10000005")
    candidate.vacancy.hiring_manager = manager_emp
    candidate.vacancy.save()
    page = reverse("recruitment:candidate_detail", args=[candidate.pk])
    hr_body = _login(hr).get(page).content.decode()
    assert _url(candidate) in hr_body and "Ажилд авах" in hr_body
    assert _url(candidate) not in _login(manager_user).get(page).content.decode()


@pytest.mark.parametrize("closing", ["reject", "hired"])
def test_candidate_page_has_no_button_when_closed_or_hired(
    hr: User, candidate: Candidate, actor: User, new_employee: Employee, closing: str
) -> None:
    if closing == "reject":
        pipeline.reject(candidate, by=actor, reason="Тохирохгүй")
    else:
        pipeline.mark_hired(candidate, new_employee, by=actor)
    page = reverse("recruitment:candidate_detail", args=[candidate.pk])
    assert _url(candidate) not in _login(hr).get(page).content.decode()
