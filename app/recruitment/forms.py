"""Recruitment forms. All inherit the shared styled forms (UI_RULES section 2)."""

from typing import Any

from accounts.models import User
from django import forms
from employees.access import manager_choices
from employees.forms import StyledForm, StyledModelForm
from macs.models import Employee

from recruitment.models import Vacancy, VacancyStatus

SOURCE_SUGGESTIONS = ("Танилын санал", "Вэбсайт", "Ажлын зар", "Биечлэн ирсэн", "Бусад")
SOURCE_LIST_ID = "candidate-source-options"


class _EmployeeChoice(forms.ModelChoiceField):  # type: ignore[type-arg]
    def label_from_instance(self, obj: Any) -> str:
        return str(obj.full_name)


class VacancyForm(StyledModelForm):
    hiring_manager = _EmployeeChoice(
        queryset=Employee.objects.none(),
        required=False,
        label=Vacancy._meta.get_field("hiring_manager").verbose_name,
        help_text="Ажил хүсэгчийг харж, сэтгэгдэл бичих удирдлага.",
    )

    class Meta:
        model = Vacancy
        fields = [
            "title",
            "position",
            "department",
            "branch",
            "headcount",
            "hiring_manager",
            "deadline",
            "desired_start",
            "status",
            "description",
        ]
        labels = {"title": "Ажлын байрны нэр"}
        help_texts = {
            "branch": "Орон тооны төлөвлөгөөг салбараар шалгана.",
            "desired_start": "Шинэ ажилтан ажилд орохыг хүсэж буй өдөр.",
        }

    def __init__(self, *args: Any, user: User, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        current = self.instance.hiring_manager if self.instance.pk else None
        manager = self.fields["hiring_manager"]
        assert isinstance(manager, forms.ModelChoiceField)  # noqa: S101
        manager.queryset = manager_choices(user, current).order_by("family_name", "given_name")
        if not self.instance.pk:
            del self.fields["status"]  # a new vacancy is always open
        else:
            status = self.fields["status"]
            assert isinstance(status, forms.ChoiceField)  # noqa: S101
            status.choices = [
                (value, label) for value, label in VacancyStatus.choices if value in self._status_choices()
            ]

    def _status_choices(self) -> set[str]:
        """HR picks open or closed; `filled` is set by the app, and shown only while the vacancy has it."""
        allowed = {VacancyStatus.OPEN.value, VacancyStatus.CLOSED.value}
        if self.instance.status == VacancyStatus.FILLED:
            allowed.add(VacancyStatus.FILLED.value)
        return allowed

    def clean_status(self) -> str:
        status: str = self.cleaned_data["status"]
        if status == VacancyStatus.FILLED and self.instance.status != VacancyStatus.FILLED:
            raise forms.ValidationError("«Бөглөгдсөн» төлөвийг систем автоматаар тавина.")
        return status


class CandidateForm(StyledForm):
    surname = forms.CharField(label="Овог", max_length=100)
    given_name = forms.CharField(label="Нэр", max_length=100)
    phone = forms.CharField(label="Утас", max_length=50, required=False)
    email = forms.EmailField(label="И-мэйл", required=False)
    source = forms.CharField(label="Эх сурвалж", max_length=100, required=False)
    notes = forms.CharField(label="Тэмдэглэл", required=False, widget=forms.Textarea)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["source"].widget.attrs["list"] = SOURCE_LIST_ID
        self.fields["source"].widget.attrs["autocomplete"] = "off"


class RejectForm(StyledForm):
    reason = forms.CharField(
        label="Татгалзсан шалтгаан",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Жишээ: туршлага хүрэлцэхгүй байна"}),
    )
    withdrawn = forms.BooleanField(label="Ажил хүсэгч өөрөө татгалзсан", required=False)

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        if not data.get("withdrawn") and not (data.get("reason") or "").strip():
            self.add_error("reason", "Татгалзсан шалтгаанаа бичнэ үү.")
        return data
