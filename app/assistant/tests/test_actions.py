import itertools
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.urls import reverse
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import _no_offboarding_templates, hire_values, link_login  # noqa: F401 (autouse)
from leave.models import LeaveTypeExt
from macs.models import Branch, LeaveTypeRow

from assistant.actions import field_answer, leave_address, leave_form_answer
from assistant.tests.helpers import left

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
TODAY = date(2026, 11, 5)
_REGISTER = itertools.count(1)


def _user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # re-read so the permissions are fresh


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("actions_actor", password=PASSWORD)


@pytest.fixture
def hr(db: None) -> User:
    return _user(roles.HR, "actions_hr")


def _person(actor: User, given: str = "Номин", family: str = "Туяа", phone: str = "") -> Employee:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {**hire_values(f"УБ{next(_REGISTER):08d}"), "given_name": given, "family_name": family}
    person = history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=None, by=actor)
    if phone:
        macs_writes.update_employee_columns(person, {"private_phone": phone})
    return person


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


def _leave_type(name: str, *, active: bool = True) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name=name)
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True, is_active=active)
    return row


# Field answers


def test_one_match_gives_the_value_and_the_address(actor: User, hr: User) -> None:
    person = _person(actor, phone="88112233")
    answer = field_answer(hr, "Номины утас", TODAY, "private_phone", own=False)
    assert answer.status == "value"
    assert answer.text == "88112233"
    assert [hit.employee.pk for hit in answer.people] == [person.pk]
    assert answer.field_label
    assert answer.url == reverse("employees:detail", args=[person.pk]) + "#personal-private_phone"


def test_empty_value_gives_empty_status(actor: User, hr: User) -> None:
    person = _person(actor)
    answer = field_answer(hr, "Номины утас", TODAY, "private_phone", own=False)
    assert answer.status == "empty"
    assert answer.text == ""
    assert answer.url == reverse("employees:detail", args=[person.pk]) + "#personal-private_phone"


def test_two_people_give_a_pick_without_url(actor: User, hr: User) -> None:
    _person(actor, "Номин", "Туяа")
    _person(actor, "Номин", "Оюун")
    answer = field_answer(hr, "Номины утас", TODAY, "private_phone", own=False)
    assert answer.status == "pick"
    assert len(answer.people) == 2
    assert answer.url == ""
    assert answer.text == ""
    assert answer.field_label == ""


def test_pick_of_a_field_the_asker_cannot_read_is_none(actor: User, hr: User) -> None:
    # HR sees the people and their personal fields, but not the salary tab: account_no is a salary field.
    _person(actor, "Номин", "Туяа")
    _person(actor, "Номин", "Оюун")
    _person(actor, "Болд", "Анар")
    pick = field_answer(hr, "Номины дансны дугаар", TODAY, "account_no", own=False)
    single = field_answer(hr, "Болдын дансны дугаар", TODAY, "account_no", own=False)
    assert pick.status == "none" and pick.people == ()
    assert single.status == "none" and single.people == ()


def test_pick_of_a_personal_field_the_asker_cannot_read_is_none(actor: User) -> None:
    # An accountant sees the people and salary, but not the personal tab: private_phone is a personal field.
    accountant = _user(roles.ACCOUNTANT, "actions_accountant")
    _person(actor, "Номин", "Туяа", phone="88112233")
    _person(actor, "Номин", "Оюун", phone="99112233")
    answer = field_answer(accountant, "Номины утас", TODAY, "private_phone", own=False)
    assert answer.status == "none"
    assert answer.people == ()
    assert answer.text == "" and answer.url == ""


def test_pick_of_a_field_the_asker_can_read_is_still_a_pick(actor: User, hr: User) -> None:
    _person(actor, "Номин", "Туяа")
    _person(actor, "Номин", "Оюун")
    answer = field_answer(hr, "Номины утас", TODAY, "private_phone", own=False)
    assert answer.status == "pick"
    assert len(answer.people) == 2


def test_leaver_and_current_employee_with_same_name_give_a_pick(actor: User, hr: User) -> None:
    leaver = _person(actor, "Номин", "Туяа")
    left(actor, leaver)
    _person(actor, "Номин", "Оюун")
    answer = field_answer(hr, "Номины утас", TODAY, "private_phone", own=False)
    assert answer.status == "pick"
    assert len(answer.people) == 2
    assert answer.url == ""


def test_person_outside_scope_is_the_same_no_answer_as_unknown(actor: User, hr: User) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    person = _person(actor)
    Employee.objects.filter(pk=person.pk).update(branch_id=north.pk)
    AccessScope.objects.update_or_create(user=hr, defaults={"limited": True, "branch_ids": [south.pk]})
    limited = User.objects.get(pk=hr.pk)
    outside = field_answer(limited, "Номины утас", TODAY, "private_phone", own=False)
    unknown = field_answer(limited, "Батын утас", TODAY, "private_phone", own=False)
    assert outside.status == unknown.status == "none"
    assert outside.url == unknown.url == ""
    assert outside.people == unknown.people == ()


def test_own_field_with_a_linked_login(actor: User) -> None:
    me = _user(roles.EMPLOYEE, "actions_me")
    person = _person(actor, phone="99887766")
    link_login(person, me)
    answer = field_answer(me, "миний утас", TODAY, "private_phone", own=True)
    assert answer.status == "value"
    assert answer.text == "99887766"
    assert answer.url == reverse("employees:detail", args=[person.pk]) + "#personal-private_phone"


def test_own_field_with_an_unlinked_login_is_no_answer(actor: User) -> None:
    me = _user(roles.EMPLOYEE, "actions_unlinked")
    _person(actor, phone="99887766")
    answer = field_answer(me, "миний утас", TODAY, "private_phone", own=True)
    assert answer.status == "none"
    assert answer.url == ""


def test_own_flag_without_the_own_word_names_the_person(actor: User, hr: User) -> None:
    # The model may set own=True; only a question that says «миний» (or «минь», «өөрийн») makes it the asker's record.
    mine = _person(actor, "Номин", "Туяа", phone="99887766")
    link_login(mine, hr)
    named = _person(actor, "Болд", "Анар", phone="88112233")
    answer = field_answer(hr, "Болдын утас", TODAY, "private_phone", own=True)
    assert answer.status == "value"
    assert answer.text == "88112233"
    assert [hit.employee.pk for hit in answer.people] == [named.pk]
    assert answer.url == reverse("employees:detail", args=[named.pk]) + "#personal-private_phone"


def test_question_without_a_name_asks_whose() -> None:
    hr = _user(roles.HR, "actions_who")
    answer = field_answer(hr, "Хэний утас вэ", TODAY, "private_phone", own=False)
    assert answer.status == "who"
    assert answer.url == ""


def test_unknown_name_is_none_not_who(actor: User, hr: User) -> None:
    _person(actor)
    answer = field_answer(hr, "Батын утас", TODAY, "private_phone", own=False)
    assert answer.status == "none"


def test_unknown_key_is_none(actor: User, hr: User) -> None:
    _person(actor)
    assert field_answer(hr, "Номины нууц", TODAY, "no_such_field", own=False).status == "none"


def test_field_the_asker_may_not_read_is_none(actor: User, hr: User) -> None:
    _person(actor)  # HR has no salary right
    answer = field_answer(hr, "Номины цалин", TODAY, "base_salary", own=False)
    assert answer.status == "none"
    assert answer.url == ""


# Leave form answers


@pytest.fixture
def annual(db: None) -> LeaveTypeRow:
    return _leave_type("Ээлжийн амралт")


@pytest.fixture
def sick(db: None) -> LeaveTypeRow:
    return _leave_type("Өвчний амралт")


def test_leave_form_without_right_is_none(actor: User, annual: LeaveTypeRow) -> None:
    _person(actor)
    accountant = _user(roles.ACCOUNTANT, "actions_acc")
    answer = leave_form_answer(accountant, "Номин", TODAY, False, "", "2026-11-10", "2026-11-12")
    assert answer.status == "none"
    assert answer.url == ""


def test_leave_form_with_one_person_type_and_dates(actor: User, hr: User, annual: LeaveTypeRow) -> None:
    person = _person(actor)
    answer = leave_form_answer(hr, "Номинд", TODAY, False, "Ээлжийн амралт", "2026-11-10", "2026-11-12")
    assert answer.status == "form"
    assert answer.open_parts == ()
    assert answer.people[0].employee.pk == person.pk
    query = _query(answer.url)
    assert query == {
        "employee": [str(person.pk)],
        "type": [str(annual.pk)],
        "start": ["2026-11-10"],
        "end": ["2026-11-12"],
        "from": ["assistant"],
    }
    assert answer.filled == (
        f"Ажилтан: {person.full_name}",
        "Төрөл: Ээлжийн амралт",
        "Эхлэх: 2026-11-10",
        "Дуусах: 2026-11-12",
    )


def test_leave_form_with_no_person_opens_empty_employee(actor: User, hr: User, annual: LeaveTypeRow) -> None:
    _person(actor)
    answer = leave_form_answer(hr, "Ээлжийн амралт авмаар", TODAY, False, "Ээлжийн амралт", "", "")
    assert answer.status == "form"
    assert answer.people == ()
    assert "employee" not in _query(answer.url)
    assert _query(answer.url)["from"] == ["assistant"]


def test_leave_form_two_people_is_a_pick_without_url(actor: User, hr: User) -> None:
    _person(actor, "Номин", "Туяа")
    _person(actor, "Номин", "Оюун")
    answer = leave_form_answer(hr, "Номин", TODAY, False, "", "", "")
    assert answer.status == "pick"
    assert len(answer.people) == 2
    assert answer.url == ""


def test_leave_form_pick_rows_carry_the_same_type_and_dates(actor: User, hr: User, annual: LeaveTypeRow) -> None:
    _person(actor, "Номин", "Туяа")
    _person(actor, "Номин", "Оюун")
    answer = leave_form_answer(hr, "Номин", TODAY, False, annual.name, "2026-11-03", "2026-11-07")
    assert answer.status == "pick"
    assert answer.url == "" and answer.filled == () and answer.open_parts == ()
    shared = {"type": str(annual.pk), "start": "2026-11-03", "end": "2026-11-07", "from": "assistant"}
    assert dict(answer.shared) == shared
    for person in answer.people:
        pk = str(person.employee.pk)
        assert _query(leave_address(person.employee.pk, answer.shared)) == {
            "employee": [pk],
            **{k: [v] for k, v in shared.items()},
        }


def test_leave_form_own_with_a_linked_login(actor: User, hr: User, annual: LeaveTypeRow) -> None:
    person = _person(actor)
    link_login(person, hr)
    answer = leave_form_answer(hr, "миний чөлөө", TODAY, True, "", "", "")
    assert answer.status == "form"
    assert _query(answer.url)["employee"] == [str(person.pk)]


def test_leave_form_own_flag_without_the_own_word_names_the_person(actor: User, hr: User, annual: LeaveTypeRow) -> None:
    mine = _person(actor, "Номин", "Туяа")
    link_login(mine, hr)
    named = _person(actor, "Болд", "Анар")
    answer = leave_form_answer(hr, "Болдод чөлөө", TODAY, True, "", "", "")
    assert answer.status == "form"
    assert _query(answer.url)["employee"] == [str(named.pk)]


def test_leave_form_own_with_an_unlinked_login_is_none(hr: User, annual: LeaveTypeRow) -> None:
    answer = leave_form_answer(hr, "миний чөлөө", TODAY, True, "", "", "")
    assert answer.status == "none"
    assert answer.url == ""


def test_ambiguous_type_is_left_empty_and_named(
    actor: User, hr: User, annual: LeaveTypeRow, sick: LeaveTypeRow
) -> None:
    _person(actor)
    answer = leave_form_answer(hr, "Номин", TODAY, False, "амралт", "2026-11-10", "2026-11-12")
    assert "type" not in _query(answer.url)
    assert "Төрлийг сонгоно уу" in answer.open_parts


def test_inactive_type_is_left_empty_and_named(actor: User, hr: User) -> None:
    _person(actor)
    _leave_type("Хүүхдийн амралт", active=False)
    answer = leave_form_answer(hr, "Номин", TODAY, False, "Хүүхдийн амралт", "", "")
    assert "type" not in _query(answer.url)
    assert "Төрлийг сонгоно уу" in answer.open_parts


def test_end_before_start_drops_the_end_and_keeps_the_start(actor: User, hr: User) -> None:
    _person(actor)
    answer = leave_form_answer(hr, "Номин", TODAY, False, "", "2026-11-12", "2026-11-10")
    query = _query(answer.url)
    assert query["start"] == ["2026-11-12"]
    assert "end" not in query
    assert "Дуусах огноог оруулна уу" in answer.open_parts
    assert "Эхлэх: 2026-11-12" in answer.filled


def test_malformed_start_is_left_empty_and_named(actor: User, hr: User) -> None:
    _person(actor)
    answer = leave_form_answer(hr, "Номин", TODAY, False, "", "2026-13-45", "2026-11-12")
    query = _query(answer.url)
    assert "start" not in query
    assert "Эхлэх огноог оруулна уу" in answer.open_parts


def test_end_without_start_is_dropped(actor: User, hr: User) -> None:
    _person(actor)
    answer = leave_form_answer(hr, "Номин", TODAY, False, "", "", "2026-11-12")
    query = _query(answer.url)
    assert "end" not in query
    assert "Эхлэх огноог оруулна уу" in answer.open_parts
    assert "Дуусах огноог оруулна уу" in answer.open_parts


def test_far_away_year_is_left_empty_and_named(actor: User, hr: User) -> None:
    _person(actor)
    answer = leave_form_answer(hr, "Номин", TODAY, False, "", "1999-05-01", "1999-05-03")
    query = _query(answer.url)
    assert "start" not in query
    assert "end" not in query
    assert "Эхлэх огноог оруулна уу" in answer.open_parts


def test_address_holds_only_codes_and_dates_never_question_text(actor: User, hr: User, annual: LeaveTypeRow) -> None:
    person = _person(actor)
    question = "Номинд Ээлжийн амралт 10-нд өгөөч"
    answer = leave_form_answer(hr, question, TODAY, False, "Ээлжийн амралт", "2026-11-10", "2026-11-12")
    query = _query(answer.url)
    assert query["employee"] == [str(person.pk)]
    assert query["type"] == [str(annual.pk)]
    assert query["start"] == ["2026-11-10"]
    assert query["end"] == ["2026-11-12"]
    assert query["from"] == ["assistant"]
    decoded = " ".join(value for values in query.values() for value in values)  # parse_qs decodes the percent-escapes
    for word in ("Номин", "амралт", "өгөөч"):
        assert word not in decoded


def test_missing_dates_are_left_empty_and_named(actor: User, hr: User) -> None:
    _person(actor)
    answer = leave_form_answer(hr, "Номин", TODAY, False, "", "", "")  # a plan leaves a date out as "" (parse_plan)
    query = _query(answer.url)
    assert answer.status == "form"
    assert "start" not in query
    assert "end" not in query
    assert "Эхлэх огноог оруулна уу" in answer.open_parts
    assert "Дуусах огноог оруулна уу" in answer.open_parts


def test_missing_leave_type_is_left_empty_and_named(actor: User, hr: User, annual: LeaveTypeRow) -> None:
    _person(actor)
    answer = leave_form_answer(hr, "Номин", TODAY, False, "", "2026-11-10", "2026-11-12")  # a plan leaves it out as ""
    query = _query(answer.url)
    assert "type" not in query
    assert query["start"] == ["2026-11-10"]
    assert "Төрлийг сонгоно уу" in answer.open_parts
