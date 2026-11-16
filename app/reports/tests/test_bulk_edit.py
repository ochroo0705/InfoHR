"""Bulk cell edit service (reports.bulk_edit, decision D-080 phase 3): dry run, apply, text to value, refusals."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django import forms
from django.contrib.auth.models import Group
from employees.tests.helpers import next_order_number
from employees.forms import EmployeeForm
from employees.models import ActivityEntry, Employee
from employees.services import history
from employees.tests.conftest import hire_values, named
from macs.models import Bank
from macs.models import Employee as MacsEmployee

from reports import bulk_edit, cell_edit
from reports.bulk_edit import BulkCell, BulkOutcome

pytestmark = pytest.mark.django_db


def _user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def second(actor: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(
        hire_values(register_no="УБ99112255"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
        order_number=next_order_number(),
    )


def _entries(*employees: MacsEmployee | Employee) -> int:
    return ActivityEntry.objects.filter(employee__in=[e.pk for e in employees]).count()


def test_dry_run_of_two_phones_is_ok_and_stores_nothing(hired: MacsEmployee, second: Employee) -> None:
    manager = _user("HR", "bulk_hr_dry")
    before = _entries(hired, second)
    cells = [
        BulkCell(person=hired.pk, field="private_phone", text="99110001", old=""),
        BulkCell(person=second.pk, field="private_phone", text="99110002", old=""),
    ]
    outcomes = bulk_edit.run(manager, cells, apply=False)
    assert outcomes == [
        BulkOutcome(person=hired.pk, field="private_phone", ok=True, text="99110001"),
        BulkOutcome(person=second.pk, field="private_phone", ok=True, text="99110002"),
    ]
    hired.refresh_from_db()
    second.refresh_from_db()
    assert hired.private_phone != "99110001"
    assert second.private_phone != "99110002"
    assert _entries(hired, second) == before


def test_apply_saves_both_and_logs_each(hired: MacsEmployee, second: Employee) -> None:
    manager = _user("HR", "bulk_hr_apply")
    before = _entries(hired, second)
    cells = [
        BulkCell(person=hired.pk, field="private_phone", text="99110001", old=""),
        BulkCell(person=second.pk, field="private_phone", text="99110002", old=""),
    ]
    outcomes = bulk_edit.run(manager, cells, apply=True)
    assert [o.ok for o in outcomes] == [True, True]
    hired.refresh_from_db()
    second.refresh_from_db()
    assert hired.private_phone == "99110001"
    assert second.private_phone == "99110002"
    assert _entries(hired, second) == before + 2


def test_gender_label_maps_to_the_stored_key(hired: MacsEmployee) -> None:
    manager = _user("HR", "bulk_hr_gender")
    # hired is stored as F («Эмэгтэй»); the label is matched trimmed and case-insensitively
    cells = [BulkCell(person=hired.pk, field="gender", text="  эрэгтэй ", old="Эмэгтэй")]
    dry = bulk_edit.run(manager, cells, apply=False)
    assert dry == [BulkOutcome(person=hired.pk, field="gender", ok=True, text="Эрэгтэй")]
    applied = bulk_edit.run(manager, cells, apply=True)
    assert applied == [BulkOutcome(person=hired.pk, field="gender", ok=True, text="Эрэгтэй")]
    hired.refresh_from_db()
    assert hired.gender == "M"


def test_unknown_choice_label_is_refused(hired: MacsEmployee) -> None:
    manager = _user("HR", "bulk_hr_choice")
    cells = [BulkCell(person=hired.pk, field="gender", text="Тодорхойгүй", old="Эмэгтэй")]
    outcomes = bulk_edit.run(manager, cells, apply=True)
    assert outcomes == [
        BulkOutcome(person=hired.pk, field="gender", ok=False, error=bulk_edit.NO_CHOICE.format("Тодорхойгүй"))
    ]
    hired.refresh_from_db()
    assert hired.gender == "F"


def test_dotted_date_is_stored_as_iso(hired: MacsEmployee) -> None:
    manager = _user("HR", "bulk_hr_date")
    cells = [BulkCell(person=hired.pk, field="birth_date", text="2001.02.03", old="1999-11-22")]
    outcomes = bulk_edit.run(manager, cells, apply=True)
    assert outcomes == [BulkOutcome(person=hired.pk, field="birth_date", ok=True, text="2001-02-03")]
    hired.refresh_from_db()
    assert hired.birth_date == date(2001, 2, 3)


def test_stale_old_text_clashes_and_writes_nothing(hired: MacsEmployee) -> None:
    manager = _user("HR", "bulk_hr_clash")
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")  # changed meanwhile
    cells = [BulkCell(person=hired.pk, field="private_phone", text="99110001", old="")]
    outcomes = bulk_edit.run(manager, cells, apply=True)
    assert outcomes == [BulkOutcome(person=hired.pk, field="private_phone", ok=False, error=cell_edit.CLASH)]
    hired.refresh_from_db()
    assert hired.private_phone == "99001122"


def test_user_without_manage_right_is_not_allowed(hired: MacsEmployee) -> None:
    accountant = _user("Accountant", "bulk_acc")
    cells = [BulkCell(person=hired.pk, field="private_phone", text="99110001", old="")]
    outcomes = bulk_edit.run(accountant, cells, apply=True)
    assert outcomes == [BulkOutcome(person=hired.pk, field="private_phone", ok=False, error=bulk_edit.NOT_ALLOWED)]
    hired.refresh_from_db()
    assert hired.private_phone != "99110001"


def test_unchanged_text_is_ok_without_a_write(hired: MacsEmployee) -> None:
    manager = _user("HR", "bulk_hr_same")
    before = _entries(hired)
    cells = [BulkCell(person=hired.pk, field="gender", text="Эмэгтэй", old="Эмэгтэй")]
    outcomes = bulk_edit.run(manager, cells, apply=True)
    assert outcomes == [BulkOutcome(person=hired.pk, field="gender", ok=True, text="Эмэгтэй")]
    assert _entries(hired) == before


def test_more_than_500_cells_is_refused(hired: MacsEmployee) -> None:
    manager = _user("HR", "bulk_hr_many")
    cells = [BulkCell(person=hired.pk, field="private_phone", text="1", old="")] * (bulk_edit.MAX_CELLS + 1)
    with pytest.raises(ValueError, match=bulk_edit.TOO_MANY):
        bulk_edit.run(manager, cells, apply=False)


def test_to_posted_empty_text_is_the_empty_value() -> None:
    form = EmployeeForm(user=None)
    assert bulk_edit.to_posted(form, "private_phone", "   ") == ("", "")


class _GroupForm(forms.Form):
    group = forms.ModelChoiceField(Group.objects.all(), required=False)


class _PlainForm(forms.Form):
    kind = forms.ChoiceField(choices=[("a", "Нэг"), ("b", "нэг ")])


def test_model_choice_takes_the_label_and_not_the_pk() -> None:
    hr = Group.objects.get(name="HR")
    form = _GroupForm()
    assert bulk_edit.to_posted(form, "group", "HR") == (str(hr.pk), "")
    assert bulk_edit.to_posted(form, "group", str(hr.pk)) == ("", bulk_edit.NO_CHOICE.format(str(hr.pk)))


def test_plain_choice_still_takes_the_key() -> None:
    form = EmployeeForm(user=None)
    assert bulk_edit.to_posted(form, "gender", "M") == ("M", "")
    plain = _PlainForm()
    assert bulk_edit.to_posted(plain, "kind", "a") == ("a", "")


def test_two_choices_with_the_same_label_are_ambiguous() -> None:
    form = _PlainForm()
    assert bulk_edit.to_posted(form, "kind", "НЭГ ") == ("", bulk_edit.AMBIGUOUS.format("НЭГ"))


@pytest.mark.parametrize(
    "text, posted", [("2001-2-3", "2001-02-03"), ("2001/02/03", "2001-02-03"), ("2001.12.31", "2001-12-31")]
)
def test_date_in_a_year_first_form_is_accepted(text: str, posted: str) -> None:
    form = EmployeeForm(user=None)
    assert bulk_edit.to_posted(form, "birth_date", text) == (posted, "")


@pytest.mark.parametrize("text", ["03/02/2001", "2001-02", "2001-02.03", "2001-02-31", "2001-02-03 10:00", "гурван"])
def test_other_date_text_is_refused_with_the_format_message(text: str) -> None:
    form = EmployeeForm(user=None)
    assert bulk_edit.to_posted(form, "birth_date", text) == ("", bulk_edit.BAD_DATE)


def test_double_space_in_the_stored_text_is_not_a_clash(hired: MacsEmployee) -> None:
    manager = _user("HR", "bulk_hr_space")
    Employee.objects.filter(pk=hired.pk).update(clan_name="А  Б")  # two spaces stored; the cell shows them as one
    before = _entries(hired)
    cells = [BulkCell(person=hired.pk, field="clan_name", text="А Б", old="А Б")]
    outcomes = bulk_edit.run(manager, cells, apply=True)
    assert outcomes == [BulkOutcome(person=hired.pk, field="clan_name", ok=True, text="А  Б")]
    assert Employee.objects.get(pk=hired.pk).clan_name == "А  Б"  # unchanged text is not rewritten
    assert _entries(hired) == before


def test_dry_run_of_two_account_numbers_is_ok_and_stores_nothing(hired: MacsEmployee, second: Employee) -> None:
    admin = _user("Admin", "bulk_admin_dry")
    Employee.objects.filter(pk__in=[hired.pk, second.pk]).update(account_no=None)
    before = _entries(hired, second)
    cells = [
        BulkCell(person=hired.pk, field="account_no", text="5001", old=""),
        BulkCell(person=second.pk, field="account_no", text="5002", old=""),
    ]
    outcomes = bulk_edit.run(admin, cells, apply=False)
    assert [(o.person, o.field, o.ok, o.text) for o in outcomes] == [
        (hired.pk, "account_no", True, "5001"),
        (second.pk, "account_no", True, "5002"),
    ]
    assert Employee.objects.get(pk=hired.pk).account_no is None
    assert Employee.objects.get(pk=second.pk).account_no is None
    assert _entries(hired, second) == before


def test_bank_text_maps_to_the_bank_by_its_name(hired: MacsEmployee) -> None:
    admin = _user("Admin", "bulk_admin_bank")
    bank = named(Bank, "Голомт банк")
    Employee.objects.filter(pk=hired.pk).update(bank=None)
    outcomes = bulk_edit.run(
        admin, [BulkCell(person=hired.pk, field="bank", text="  ГОЛОМТ БАНК ", old="")], apply=True
    )
    assert outcomes == [BulkOutcome(person=hired.pk, field="bank", ok=True, text="Голомт банк")]
    assert Employee.objects.get(pk=hired.pk).bank_id == bank.pk
