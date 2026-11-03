"""The hire form carries a recruitment `candidate` through POST; a successful hire links it, nothing else does."""

from typing import Any

import pytest
from accounts.models import User
from checklists.models import Checklist, ChecklistKind, ChecklistTemplate
from django.test import Client
from recruitment.models import Candidate, Stage, Vacancy, VacancyStatus
from recruitment.services import pipeline
from recruitment.tests.conftest import make_vacancy

from employees.models import Employee

from .test_views import add_payload, login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def candidate(actor: User) -> Candidate:
    return pipeline.add_candidate(make_vacancy(), by=actor, surname="Дорж", given_name="Бат")


def _post(client: Client, job_values: dict[str, Any], candidate_id: object, **extra: str) -> Any:
    payload = add_payload(job_values, **extra)
    if candidate_id is not None:
        payload["candidate"] = str(candidate_id)
    return client.post("/employees/new/", payload)


def test_hire_links_candidate_and_fills_vacancy(
    client: Client, job_values: dict[str, Any], candidate: Candidate
) -> None:
    login_as(client, "HR")
    assert _post(client, job_values, candidate.pk).status_code == 302
    candidate.refresh_from_db()
    employee = Employee.objects.get(register_no="УК88010122")
    assert candidate.stage == Stage.HIRED and candidate.employee_id == employee.pk
    assert Vacancy.objects.get(pk=candidate.vacancy_id).status == VacancyStatus.FILLED  # headcount 1 reached


def test_onboarding_checklist_still_starts(client: Client, job_values: dict[str, Any], candidate: Candidate) -> None:
    ChecklistTemplate.objects.filter(kind=ChecklistKind.ONBOARDING).update(active=True)
    login_as(client, "HR")
    _post(client, job_values, candidate.pk)
    employee = Employee.objects.get(register_no="УК88010122")
    assert Checklist.objects.filter(employee=employee, kind=ChecklistKind.ONBOARDING).count() == 1
    candidate.refresh_from_db()
    assert candidate.stage == Stage.HIRED


def test_vacancy_with_more_headcount_stays_open(client: Client, job_values: dict[str, Any], actor: User) -> None:
    vacancy = make_vacancy("Хоёр хүн", headcount=2)
    cand = pipeline.add_candidate(vacancy, by=actor, surname="А", given_name="Б")
    login_as(client, "HR")
    _post(client, job_values, cand.pk)
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.OPEN


def test_invalid_hire_leaves_candidate_unchanged(
    client: Client, job_values: dict[str, Any], candidate: Candidate
) -> None:
    login_as(client, "HR")
    response = _post(client, job_values, candidate.pk, family_name="")  # required field missing
    assert response.status_code == 200 and not Employee.objects.filter(register_no="УК88010122").exists()
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW and candidate.employee_id is None
    assert Vacancy.objects.get(pk=candidate.vacancy_id).status == VacancyStatus.OPEN
    # the re-rendered form still carries the candidate so a second try can link it
    assert f'name="candidate" value="{candidate.pk}"' in response.content.decode()


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "999999", "", "1.5"])
def test_bad_candidate_value_is_ignored(
    client: Client, job_values: dict[str, Any], candidate: Candidate, bad: str
) -> None:
    login_as(client, "HR")
    assert _post(client, job_values, bad).status_code == 302  # the hire itself still succeeds
    assert Employee.objects.filter(register_no="УК88010122").exists()
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW and candidate.employee_id is None


def test_missing_candidate_value_changes_nothing(
    client: Client, job_values: dict[str, Any], candidate: Candidate
) -> None:
    login_as(client, "HR")
    assert _post(client, job_values, None).status_code == 302
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW


def test_user_without_recruitment_right_cannot_link(
    client: Client, job_values: dict[str, Any], candidate: Candidate
) -> None:
    user = login_as(client, "HR")
    user.groups.clear()
    # A hirer with the employee right but not the recruitment right: build one from the HR group minus recruitment.
    from django.contrib.auth.models import Group, Permission

    group = Group.objects.create(name="HireOnly")
    group.permissions.set(Group.objects.get(name="HR").permissions.exclude(codename="manage_recruitment"))
    user.groups.add(group)
    assert _post(client, job_values, candidate.pk).status_code == 302
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW and candidate.employee_id is None
    assert Permission.objects.filter(codename="manage_recruitment").exists()


@pytest.mark.parametrize("closing", ["reject", "hired"])
def test_closed_or_hired_candidate_is_not_linked(
    client: Client, job_values: dict[str, Any], candidate: Candidate, actor: User, hired: Employee, closing: str
) -> None:
    if closing == "reject":
        pipeline.reject(candidate, by=actor, reason="Тохирохгүй")
    else:
        pipeline.mark_hired(candidate, hired, by=actor)
    before = Candidate.objects.get(pk=candidate.pk)
    login_as(client, "HR")
    assert _post(client, job_values, candidate.pk).status_code == 400  # visible but no longer convertible: no hire
    assert not Employee.objects.filter(register_no="УК88010122").exists()
    after = Candidate.objects.get(pk=candidate.pk)
    assert (after.stage, after.employee_id) == (before.stage, before.employee_id)


def test_second_conversion_is_refused(client: Client, job_values: dict[str, Any], candidate: Candidate) -> None:
    login_as(client, "HR")
    _post(client, job_values, candidate.pk)
    first = Candidate.objects.get(pk=candidate.pk).employee_id
    count = Employee.objects.count()
    response = _post(client, job_values, candidate.pk, register_no="ук 88010199")
    assert response.status_code == 400  # a candidate already hired blocks a second hire
    assert "аль хэдийн ажилд авагдсан эсвэл хаагдсан" in response.content.decode()
    assert Employee.objects.count() == count and not Employee.objects.filter(register_no="УК88010199").exists()
    assert Candidate.objects.get(pk=candidate.pk).employee_id == first


def test_candidate_closed_before_posting_blocks_the_hire(
    client: Client, job_values: dict[str, Any], candidate: Candidate, actor: User
) -> None:
    pipeline.reject(candidate, by=actor, reason="Тохирохгүй")
    login_as(client, "HR")
    response = _post(client, job_values, candidate.pk)
    assert response.status_code == 400 and not Employee.objects.filter(register_no="УК88010122").exists()


def test_candidate_of_closed_vacancy_blocks_the_hire(
    client: Client, job_values: dict[str, Any], candidate: Candidate
) -> None:
    Vacancy.objects.filter(pk=candidate.vacancy_id).update(status=VacancyStatus.CLOSED)
    login_as(client, "HR")
    assert _post(client, job_values, candidate.pk).status_code == 400
    assert not Employee.objects.filter(register_no="УК88010122").exists()


def test_candidate_hired_between_check_and_lock_blocks_the_hire(
    client: Client,
    job_values: dict[str, Any],
    candidate: Candidate,
    actor: User,
    hired: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other tab hires the candidate after this request's first look but before its transaction locks the row."""
    from recruitment.services import convert

    real = convert.convertible
    calls = {"n": 0}

    def racing(user: User, raw: object) -> Any:
        found = real(user, raw)
        calls["n"] += 1
        if calls["n"] == 1:
            pipeline.mark_hired(candidate, hired, by=actor)
        return found

    monkeypatch.setattr(convert, "convertible", racing)
    login_as(client, "HR")
    response = _post(client, job_values, candidate.pk)
    assert response.status_code == 400 and not Employee.objects.filter(register_no="УК88010122").exists()
    assert Candidate.objects.get(pk=candidate.pk).employee_id == hired.pk


def test_failure_in_mark_hired_rolls_the_hire_back(
    client: Client, job_values: dict[str, Any], candidate: Candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise pipeline.PipelineError("boom")

    monkeypatch.setattr(pipeline, "mark_hired", refuse)
    login_as(client, "HR")
    assert _post(client, job_values, candidate.pk).status_code == 400
    assert not Employee.objects.filter(register_no="УК88010122").exists()  # never an employee without the link
    assert Candidate.objects.get(pk=candidate.pk).stage == Stage.NEW


def test_get_ignores_bad_candidate_and_prefills_nothing_hidden(client: Client, job_values: dict[str, Any]) -> None:
    login_as(client, "HR")
    body = client.get("/employees/new/?candidate=abc&family_name=Дорж").content.decode()
    assert 'name="candidate"' not in body
    assert 'value="Дорж"' in body  # a plain prefill value still reaches the form
