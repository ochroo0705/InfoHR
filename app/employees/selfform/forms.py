"""The HR form that creates one employee self-form invitation (the list screen's create form)."""

from typing import Any

from accounts.models import User
from django import forms
from macs.models import Branch

from employees.access import branch_choices, branch_required
from employees.forms import StyledForm
from employees.models import CompanySettings

MAX_HOURS = 8760  # one year, the same limit the service enforces


class SelfFormInvitationForm(StyledForm):
    label = forms.CharField(
        label="Нэр (зөвхөн HR-д харагдана)",
        max_length=100,
        help_text="Ажилтны нэр эсвэл ямар ажлын байранд авахыг бичнэ. Ажилтанд харагдахгүй.",
    )
    branch = forms.ModelChoiceField(queryset=Branch.objects.none(), label="Салбар", required=False)
    hours = forms.IntegerField(
        label="Хүчинтэй хугацаа (цаг)",
        required=False,
        min_value=1,
        max_value=MAX_HOURS,
    )

    def __init__(self, *args: Any, user: User, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        branch = self.fields["branch"]
        assert isinstance(branch, forms.ModelChoiceField)
        branch.queryset = branch_choices(user).order_by("name")
        branch.required = branch_required(user)
        default = CompanySettings.get().selfform_default_hours
        self.fields["hours"].help_text = f"Хоосон бол өгөгдмөл {default} цаг. Хамгийн ихдээ {MAX_HOURS} цаг."
