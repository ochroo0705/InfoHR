from django import forms
from employees.forms import StyledForm

VISIBILITY_CHOICES = [("shared", "Хамтын"), ("private", "Хувийн")]


class SavedViewForm(StyledForm):
    """A saved view's name, who sees it and whether it opens first. `query` carries the report's address on the
    «Хадгалах» pop-up; the server cleans it. A blank visibility means shared."""

    name = forms.CharField(label="Нэр", max_length=60)
    visibility = forms.ChoiceField(
        label="Хэнд харагдах",
        choices=VISIBILITY_CHOICES,
        initial="shared",
        required=False,
        widget=forms.RadioSelect(attrs={"class": "accent-violet-600"}),
    )
    is_default = forms.BooleanField(
        label="Нээхэд үндсэн харагдац болгох",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "rounded border-slate-300"}),
    )
    query = forms.CharField(required=False, widget=forms.HiddenInput)
