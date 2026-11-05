import itertools
from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import _no_offboarding_templates, hire_values, link_login  # noqa: F401 (autouse)

from assistant.fields import FieldValue, field_by_key, field_value

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
TODAY = date(2026, 11, 5)
_REGISTER = itertools.count(1)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("value_actor", password=PASSWORD)


def _label(key: str) -> str:
    found = field_by_key(key)
    assert found is not None, key
    return found.label


def _text_of(user: User, employee: Employee, key: str) -> str:
    value = field_value(user, employee, key, TODAY)
    assert value is not None, key
    return value.text


def _user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # re-read so the permissions are fresh


def _person(actor: User, salary: Decimal | None = Decimal("2500000"), manager: Employee | None = None) -> Employee:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
        "manager": manager,
    }
    values = {**hire_values(f"УБ{next(_REGISTER):08d}"), "given_name": "Номин", "family_name": "Тест"}
    return history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=salary, by=actor)


def test_hr_reads_private_phone(actor: User) -> None:
    person = _person(actor)
    macs_writes.update_employee_columns(person, {"private_phone": "88112233"})
    hr = _user("HR", "value_hr")
    assert field_value(hr, person, "private_phone", TODAY) == FieldValue(label=_label("private_phone"), text="88112233")


def test_personal_field_needs_view_personal_or_own_page(actor: User) -> None:
    person = _person(actor)
    macs_writes.update_employee_columns(person, {"private_phone": "88112233"})
    accountant = _user("Accountant", "value_acc")  # no view_personal
    assert field_value(accountant, person, "private_phone", TODAY) is None
    me = _user("Employee", "value_me")
    link_login(person, me)
    me = User.objects.get(pk=me.pk)
    assert _text_of(me, person, "private_phone") == "88112233"


def test_staff_column_permission_is_also_needed(actor: User) -> None:
    # nationality sits on the work tab (no tab permission needed) but is a staff-table column that needs view_personal.
    person = _person(actor)
    accountant = _user("Accountant", "value_acc_col")  # passes the tab rule, lacks the column permission, not own
    assert field_value(accountant, person, "nationality", TODAY) is None
    hr = _user("HR", "value_hr_col")  # has view_personal
    assert field_value(hr, person, "nationality", TODAY) is not None


def test_salary_fields_need_view_salary(actor: User) -> None:
    person = _person(actor)
    macs_writes.update_employee_columns(person, {"account_no": "1234567890"})
    hr = _user("HR", "value_hr_pay")  # no view_salary
    assert field_value(hr, person, "account_no", TODAY) is None
    assert field_value(hr, person, "base_salary", TODAY) is None
    accountant = _user("Accountant", "value_acc_pay")  # view_salary
    assert _text_of(accountant, person, "account_no") == "1234567890"
    assert field_value(accountant, person, "base_salary", TODAY) == FieldValue(
        label=_label("base_salary"), text="2,500,000"
    )


def test_choice_shows_label_and_empty_is_blank(actor: User) -> None:
    person = _person(actor)  # hire_values sets gender "F"
    hr = _user("HR", "value_hr_choice")
    assert _text_of(hr, person, "gender") == "Эмэгтэй"
    assert _text_of(hr, person, "email") == ""


def test_date_is_iso(actor: User) -> None:
    person = _person(actor)  # birth_date 1999-11-22 from hire_values
    hr = _user("HR", "value_hr_date")
    assert _text_of(hr, person, "birth_date") == "1999-11-22"


def test_job_field_reads_the_record_on_the_day(actor: User) -> None:
    person = _person(actor)
    hr = _user("HR", "value_hr_job")
    assert _text_of(hr, person, "position") == "Нягтлан"


def test_manager_shown_to_one_who_sees_the_manager(actor: User) -> None:
    boss = _person(actor)
    person = _person(actor, manager=boss)
    hr = _user("HR", "value_hr_mgr")  # sees every employee
    assert _text_of(hr, person, "manager") == str(boss)


def test_manager_outside_data_scope_reads_empty(actor: User) -> None:
    boss = _person(actor)
    person = _person(actor, manager=boss)
    me = _user("Employee", "value_me_mgr")  # sees only their own record, not the manager
    link_login(person, me)
    me = User.objects.get(pk=me.pk)
    text = _text_of(me, person, "manager")
    assert text == ""
    assert str(boss) not in text


def test_long_value_is_cut_to_200(actor: User) -> None:
    person = _person(actor)
    person.work_phone = "9" * 500  # not saved: the reader reads the instance it is given
    hr = _user("HR", "value_hr_long")
    assert _text_of(hr, person, "work_phone") == "9" * 200


def test_unknown_key_is_none(actor: User) -> None:
    person = _person(actor)
    hr = _user("HR", "value_hr_unknown")
    assert field_value(hr, person, "nonsense", TODAY) is None
