"""employees.services.form_schema: the form descriptions the API and the React screens read."""

import pytest
from accounts.models import User
from django import forms

from employees.forms import EmployeeForm, FamilyRowForm, RelativeRowForm
from employees.models import Employee
from employees.services.form_schema import describe_form, empty_lists, hidden_values

pytestmark = pytest.mark.django_db


def _by_name(described: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(item["name"]): item for item in described}


def test_employee_form_kinds_for_a_seeded_employee(hired: Employee, actor: User) -> None:
    by = _by_name(describe_form(EmployeeForm(employee=hired, user=actor)))
    assert by["first_hire_date"]["kind"] == "date"
    assert by["branch"]["kind"] == "select"
    branch_choices = by["branch"]["choices"]
    assert isinstance(branch_choices, list)
    assert branch_choices[0]["value"] == ""  # the blank entry comes first
    assert by["photo_clear"]["kind"] == "checkbox"


def test_adding_relative_row_marks_given_name_required_with_max_length() -> None:
    by = _by_name(describe_form(RelativeRowForm(adding=True)))
    assert by["given_name"]["required"] is True
    assert by["given_name"]["max_length"] == 20
    assert not any(str(name).startswith("loaded_") for name in by)  # the hidden loaded_* fields are skipped


def test_bound_form_error_is_listed_on_the_field() -> None:
    form = RelativeRowForm({"given_name": ""}, adding=True)
    assert not form.is_valid()
    by = _by_name(describe_form(form))
    assert by["given_name"]["errors"] == list(form.errors["given_name"])
    assert by["given_name"]["errors"]


def test_hidden_values_returns_the_loaded_snapshots_from_from_snapshot() -> None:
    snap: dict[str, object] = {attname: None for _, attname in FamilyRowForm.COLUMNS}
    snap |= {name: None for name in FamilyRowForm.LOADED}
    ext: dict[str, object] = {name: None for name in FamilyRowForm.EXT}
    form = FamilyRowForm(initial=FamilyRowForm.from_snapshot(snap, ext))
    values = hidden_values(form)
    assert set(values) == {f"loaded_{name}" for name in FamilyRowForm.LOADED}
    assert all(value == "null" for value in values.values())  # json.dumps(None), as from_snapshot writes it


def test_names_order_is_kept() -> None:
    out = describe_form(RelativeRowForm(adding=True), names=("father_name", "given_name"))
    assert [item["name"] for item in out] == ["father_name", "given_name"]


class _WithHidden(forms.Form):
    a = forms.CharField(required=False)
    b = forms.CharField(required=False, widget=forms.HiddenInput)


def test_hidden_widget_is_skipped() -> None:
    assert [item["name"] for item in describe_form(_WithHidden())] == ["a"]
    assert [item["name"] for item in describe_form(_WithHidden(), names=("a", "b"))] == ["a"]


def test_empty_lists_is_empty_for_a_form_without_the_method() -> None:
    assert empty_lists(_WithHidden()) == []


class _WithLists(_WithHidden):
    def empty_lists(self) -> list[tuple[str, str]]:
        return [("branch", "Салбар")]


def test_empty_lists_reports_each_missing_list_when_the_form_has_the_method() -> None:
    assert empty_lists(_WithLists()) == [{"slug": "branch", "label": "Салбар"}]
