"""The request-free cell and row editor service (reports.services.cell_editors) behind the React report editors."""

from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from django import forms
from django.core.exceptions import PermissionDenied
from django.http import Http404
from employees import access, stale
from employees.forms import EmployeeForm, SalaryInsuranceForm
from employees.models import Employee
from employees.services.display import shown
from employees.tests.conftest import named
from macs.models import ContactRow, ContactType, FamilyRelation, FamilyRow

from reports.services import cell_editors as svc

pytestmark = pytest.mark.django_db


def _child(employee: Employee, given: str = "Бат", birth: date | None = date(2015, 1, 2)) -> FamilyRow:
    relation = FamilyRelation.objects.create(name=f"Хүү {given}", fm_type="son")
    return FamilyRow.objects.create(employee=employee, relation=relation, given_name=given, birth_date=birth)


def _contact(employee: Employee, value: str = "99112233") -> ContactRow:
    return ContactRow.objects.create(
        employee=employee, contact_type=named(ContactType, "Утас"), value=value, name="Эх", relative="Ээж"
    )


def test_model_of_gender_is_a_choice_with_the_empty_option(hr_user: User, hired: Employee) -> None:
    form = EmployeeForm(employee=hired, user=hr_user)
    model = svc.model_of(form["gender"])
    assert model.kind == "choice"
    assert model.name == "gender"
    assert svc.EditorChoice(value="", label=model.choices[0].label) in model.choices
    assert model.choices[0].value == ""
    assert len(model.choices) > 1


def test_model_of_birth_date_is_a_date(hr_user: User, hired: Employee) -> None:
    form = EmployeeForm(employee=hired, user=hr_user)
    form.initial["birth_date"] = date(1990, 5, 6)
    model = svc.model_of(form["birth_date"])
    assert model.kind == "date"
    assert model.value == "1990-05-06"
    assert model.choices == []


def test_model_of_email_is_text_with_maxlength(hr_user: User, hired: Employee) -> None:
    form = EmployeeForm(employee=hired, user=hr_user)
    model = svc.model_of(form["email"])
    assert model.kind == "text"
    assert model.maxlength == form.fields["email"].max_length
    assert model.maxlength is not None


def test_model_of_salary_field_is_text(hr_user: User, hired: Employee) -> None:
    form = SalaryInsuranceForm(employee=hired)
    model = svc.model_of(form["account_no"])
    assert model.kind == "text"
    assert model.name == "account_no"


def test_open_cell_returns_the_stored_value_and_a_token(hr_user: User, hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")
    model = svc.open_cell(hr_user, hired.pk, "private_phone")
    assert model.value == "99001122"
    assert model.loaded != ""
    assert model.loaded == stale.snapshot(EmployeeForm(employee=Employee.objects.get(pk=hired.pk), user=hr_user))


def test_open_cell_unknown_field_is_404(hr_user: User, hired: Employee) -> None:
    with pytest.raises(Http404):
        svc.open_cell(hr_user, hired.pk, "salary")


def test_open_cell_unknown_person_is_404(hr_user: User, hired: Employee) -> None:
    with pytest.raises(Http404):
        svc.open_cell(hr_user, 999_999, "private_phone")


def test_open_cell_salary_field_without_salary_right_is_403(hr_user: User, hired: Employee) -> None:
    assert not access.can_manage_salary(hr_user)  # HR manages employees, not the salary columns
    with pytest.raises(PermissionDenied):
        svc.open_cell(hr_user, hired.pk, "account_no")


def test_save_cell_ok_returns_the_value_as_shown(hr_user: User, hired: Employee) -> None:
    loaded = svc.open_cell(hr_user, hired.pk, "private_phone").loaded
    result = svc.save_cell(hr_user, hired.pk, "private_phone", "99887766", loaded)
    assert result.ok is True
    assert result.text == "99887766"
    assert result.editor is None
    hired.refresh_from_db()
    assert hired.private_phone == "99887766"


def test_save_cell_clash_shows_the_current_value_with_a_fresh_token(hr_user: User, hired: Employee) -> None:
    loaded = svc.open_cell(hr_user, hired.pk, "private_phone").loaded
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")  # changed meanwhile by someone else
    result = svc.save_cell(hr_user, hired.pk, "private_phone", "99887766", loaded)
    assert result.ok is False
    assert result.error == svc.CLASH
    assert result.editor is not None
    assert result.editor.value == "99001122"
    assert result.editor.loaded != loaded
    assert "99001122" in result.editor.loaded
    retry = svc.save_cell(hr_user, hired.pk, "private_phone", "99887766", result.editor.loaded)
    assert retry.ok is True
    hired.refresh_from_db()
    assert hired.private_phone == "99887766"


def test_save_cell_other_error_keeps_the_typed_text_and_the_posted_token(hr_user: User, hired: Employee) -> None:
    loaded = svc.open_cell(hr_user, hired.pk, "email").loaded
    result = svc.save_cell(hr_user, hired.pk, "email", "not-an-email", loaded)
    assert result.ok is False
    assert result.error != ""
    assert result.error != svc.CLASH
    assert result.editor is not None
    assert result.editor.value == "not-an-email"
    assert result.editor.loaded == loaded
    assert result.editor.error == result.error
    hired.refresh_from_db()
    assert hired.email != "not-an-email"


def test_save_cell_forged_field_writes_nothing(hr_user: User, hired: Employee) -> None:
    before = hired.work_phone
    with pytest.raises(Http404):
        svc.save_cell(hr_user, hired.pk, "salary", "1", "")
    with pytest.raises(PermissionDenied):
        svc.save_cell(hr_user, hired.pk, "account_no", "999", "")
    hired.refresh_from_db()
    assert hired.work_phone == before
    assert hired.account_no != "999"


def test_open_row_returns_the_visible_field_and_the_loaded_tokens(hr_user: User, hired: Employee) -> None:
    child = _child(hired)
    model = svc.open_row(hr_user, hired.pk, "family", child.pk, "given_name")
    assert model.name == "given_name"
    assert model.value == "Бат"
    assert model.loaded == ""
    assert "given_name" not in model.hidden
    assert any(name.startswith("loaded_") for name in model.hidden)
    assert model.hidden["birth_date"] == "2015-01-02"


def test_save_row_ok_writes_the_field(hr_user: User, hired: Employee) -> None:
    child = _child(hired)
    model = svc.open_row(hr_user, hired.pk, "family", child.pk, "given_name")
    values = {**model.hidden, "given_name": "Болд"}
    result = svc.save_row(hr_user, hired.pk, "family", child.pk, "given_name", values)
    assert result.ok is True
    assert result.text == "Болд"
    child.refresh_from_db()
    assert child.given_name == "Болд"


def test_save_row_changed_meanwhile_is_a_conflict_with_a_fresh_editor(hr_user: User, hired: Employee) -> None:
    child = _child(hired)
    model = svc.open_row(hr_user, hired.pk, "family", child.pk, "given_name")
    FamilyRow.objects.filter(pk=child.pk).update(given_name="Өөр")  # another user changed it after the editor opened
    values = {**model.hidden, "given_name": "Болд"}
    result = svc.save_row(hr_user, hired.pk, "family", child.pk, "given_name", values)
    assert result.ok is False
    assert result.conflict is True
    assert result.error != ""
    assert result.editor is not None
    assert result.editor.value == "Өөр"
    assert result.editor.error == result.error
    retry_values = {**result.editor.hidden, "given_name": "Болд"}
    retry = svc.save_row(hr_user, hired.pk, "family", child.pk, "given_name", retry_values)
    assert retry.ok is True
    child.refresh_from_db()
    assert child.given_name == "Болд"


def test_save_row_other_error_keeps_the_typed_text(hr_user: User, hired: Employee) -> None:
    child = _child(hired)
    model = svc.open_row(hr_user, hired.pk, "family", child.pk, "birth_date")
    values = {**model.hidden, "birth_date": "2015-13-45"}
    result = svc.save_row(hr_user, hired.pk, "family", child.pk, "birth_date", values)
    assert result.ok is False
    assert result.conflict is False
    assert result.editor is not None
    assert result.editor.value == "2015-13-45"
    child.refresh_from_db()
    assert child.birth_date == date(2015, 1, 2)


def test_contact_row_value_is_saved(hr_user: User, hired: Employee) -> None:
    contact = _contact(hired)
    model = svc.open_row(hr_user, hired.pk, "contact", contact.pk, "value")
    values = {**model.hidden, "value": "99887766"}
    result = svc.save_row(hr_user, hired.pk, "contact", contact.pk, "value", values)
    assert result.ok is True
    assert result.text == "99887766"


def test_row_of_another_employee_is_404(hr_user: User, hired: Employee, left_employee: Employee) -> None:
    other_child = _child(left_employee, given="Сарнай")
    with pytest.raises(Http404):
        svc.open_row(hr_user, hired.pk, "family", other_child.pk, "given_name")
    with pytest.raises(Http404):
        svc.save_row(hr_user, hired.pk, "family", other_child.pk, "given_name", {"given_name": "x"})


def test_row_unknown_kind_or_field_is_404(hr_user: User, hired: Employee) -> None:
    child = _child(hired)
    with pytest.raises(Http404):
        svc.open_row(hr_user, hired.pk, "family", child.pk, "surname")
    with pytest.raises(Http404):
        svc.open_row(hr_user, hired.pk, "unknown", child.pk, "value")


def test_model_of_a_number_field_is_a_number_editor() -> None:
    class Amounts(forms.Form):
        count = forms.IntegerField(required=False)
        rate = forms.DecimalField(required=False, max_digits=8, decimal_places=2)

    form = Amounts(initial={"count": 7, "rate": Decimal("12.50")})
    count = svc.model_of(form["count"])
    assert count.kind == "number"
    assert count.value == "7"
    assert count.choices == []
    assert count.maxlength is None
    assert svc.model_of(form["rate"]).kind == "number"


def test_model_of_a_stored_gender_shows_the_key_and_its_label(hr_user: User, hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(gender="F")
    model = svc.open_cell(hr_user, hired.pk, "gender")
    assert model.kind == "choice"
    assert model.value == "F"  # the stored key is what the save posts back
    assert model.label == "Эмэгтэй"  # the label the screens show for F
    assert model.label == shown(Employee._meta.get_field("gender"), "F")
