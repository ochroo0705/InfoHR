import itertools
from datetime import date

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import _no_offboarding_templates, hire_values  # noqa: F401 (autouse)
from macs.models import Branch

from assistant.people import PEOPLE_SHOWN, match_people

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
TODAY = date(2026, 11, 5)
_REGISTER = itertools.count(1)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("people_actor", password=PASSWORD)


@pytest.fixture
def hr(db: None) -> User:
    user = User.objects.create_user("people_hr", password=PASSWORD)
    user.groups.add(Group.objects.get(name=roles.HR))
    return User.objects.get(pk=user.pk)  # re-read so the permissions are fresh


def _person(actor: User, given: str, family: str = "Тест", position: str = "Нягтлан") -> Employee:
    job = {
        "position": macs_writes.save_position(position),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {**hire_values(f"УБ{next(_REGISTER):08d}"), "given_name": given, "family_name": family}
    return history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=None, by=actor)


def _pks(user: User, text: str) -> list[int]:
    return [hit.employee.pk for hit in match_people(user, text, TODAY)]


def test_exact_name(actor: User, hr: User) -> None:
    person = _person(actor, "Номин", "Туяа")
    assert _pks(hr, "Номин") == [person.pk]


def test_hit_carries_position(actor: User, hr: User) -> None:
    person = _person(actor, "Номин", "Туяа", position="Нягтлан")
    hits = match_people(hr, "Номин", TODAY)
    assert hits[0].employee.pk == person.pk
    assert hits[0].position == "Нягтлан"


@pytest.mark.parametrize("text", ["Номины", "Номинд", "Номинтой"])
def test_case_endings(actor: User, hr: User, text: str) -> None:
    person = _person(actor, "Номин", "Туяа")
    assert _pks(hr, text) == [person.pk]


def test_ordinary_word_is_not_a_name(actor: User, hr: User) -> None:
    _person(actor, "Бат", "Төмөр")
    assert match_people(hr, "хүсэлт батлах", TODAY) == []


def test_two_people_same_name(actor: User, hr: User) -> None:
    first = _person(actor, "Номин", "Туяа")
    second = _person(actor, "Номин", "Оюун")
    assert set(_pks(hr, "Номин")) == {first.pk, second.pk}


def test_family_and_given_narrow(actor: User, hr: User) -> None:
    wanted = _person(actor, "Номин", "Болд")
    _person(actor, "Номин", "Туяа")
    assert _pks(hr, "Болдын Номины гэрээ") == [wanted.pk]


def test_out_of_scope_is_no_match(actor: User, hr: User) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    person = _person(actor, "Номин", "Туяа")
    Employee.objects.filter(pk=person.pk).update(branch_id=north.pk)
    assert _pks(hr, "Номин") == [person.pk]  # unlimited: visible
    AccessScope.objects.update_or_create(user=hr, defaults={"limited": True, "branch_ids": [south.pk]})
    limited = User.objects.get(pk=hr.pk)
    assert match_people(limited, "Номин", TODAY) == []


def test_short_names_ignored(actor: User, hr: User) -> None:
    _person(actor, "Ба", "Төмөр")
    assert match_people(hr, "Ба", TODAY) == []
    assert match_people(hr, "баад", TODAY) == []


def test_cap(actor: User, hr: User) -> None:
    for n in range(7):
        _person(actor, "Бат", f"Овог{n}")
    assert len(match_people(hr, "Бат", TODAY)) == PEOPLE_SHOWN + 1 == 6
