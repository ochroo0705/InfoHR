from django import forms
from employees.forms import StyledForm


class SavedViewForm(StyledForm):
    """A saved view's name. `query` carries the report's address on the «Хадгалах» pop-up; the server cleans it."""

    name = forms.CharField(label="Нэр", max_length=60)
    query = forms.CharField(required=False, widget=forms.HiddenInput)
