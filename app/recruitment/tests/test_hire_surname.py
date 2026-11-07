"""Recruitment hire: a candidate with no surname cannot be turned into an employee. The hire form (opened from the
candidate) refuses the blank surname, and the candidate stays open, not linked to anyone."""

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.forms import Field
from django.test import Client
from django.urls import reverse
from employees.models import Employee

from recruitment.models import Candidate, Vacancy
from recruitment.services import pipeline

pytestmark = pytest.mark.django_db

SURNAME_REQUIRED = str(Field.default_error_messages["required"])


@pytest.fixture
def hr(hr_user: User) -> User:
    hr_user.groups.add(Group.objects.get(name="HR"))  # the hire form needs the employee right too
    return hr_user


def test_recruitment_hire_without_candidate_surname_is_refused_and_candidate_stays_open(
    hr: User, vacancy: Vacancy, actor: User
) -> None:
    candidate = pipeline.add_candidate(vacancy, by=actor, surname="", given_name="Бат")
    client = Client()
    client.force_login(hr)
    response = client.post(
        reverse("employees:add") + f"?candidate={candidate.pk}",
        {
            "family_name": "",
            "given_name": "Бат",
            "register_no": "уб 99112233",
            "birth_date": "1999-11-22",
            "gender": "F",
            "work_phone": "99112233",
            "first_hire_date": "2026-01-05",
            "work_conditions": "1",
            "prior_service_years": "0",
            "prior_service_months": "0",
            "start": "2026-01-05",
            "position": str(vacancy.position_id),
            "department": str(vacancy.department_id),
            "employee_type": "full_time",
            "status": "active",
            "contract_type": "open_ended",
            "candidate": str(candidate.pk),
        },
    )
    assert response.status_code == 200
    assert response.context["person"].errors["family_name"] == [SURNAME_REQUIRED]
    assert not Employee.objects.exists()
    assert Candidate.objects.get(pk=candidate.pk).employee_id is None
