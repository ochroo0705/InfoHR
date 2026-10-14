from typing import Any

from accounts.models import User
from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from employees.models import (
    Department,
    Education,
    Employee,
    FamilyMember,
    Gift,
    JobRecord,
    Position,
    SalaryInsurance,
    Talent,
)
from employees.validators import normalize_register_no

INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"


class StyledForm(forms.Form):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", INPUT)
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(attrs={"type": "date", "class": INPUT}, format="%Y-%m-%d")


class StyledModelForm(forms.ModelForm, StyledForm):  # type: ignore[type-arg]
    pass


EMPLOYEE_FIELDS = [
    "family_name",
    "given_name",
    "clan_name",
    "register_no",
    "birth_date",
    "gender",
    "photo",
    "work_phone",
    "private_phone",
    "email",
    "address",
    "emergency_name",
    "emergency_phone",
    "citizenship",
    "is_foreigner",
    "passport_no",
    "marital_status",
    "first_hire_date",
    "prior_service_years",
    "prior_service_months",
    "work_conditions",
    "work_schedule",
    "probation_end",
]

OTHER_FIELDS = [
    "blood_type",
    "social_origin",
    "military_service",
    "housing_condition",
    "living_standard",
    "car_ownership",
    "clothing_size",
    "shoe_size",
    "elected_position",
]


class EmployeeForm(StyledModelForm):
    class Meta:
        model = Employee
        fields = EMPLOYEE_FIELDS + OTHER_FIELDS
        error_messages = {
            "register_no": {"unique": "Энэ регистрийн дугаартай ажилтан аль хэдийн бүртгэлтэй."},
        }

    def clean_register_no(self) -> str:
        return normalize_register_no(self.cleaned_data["register_no"])


class HirePersonForm(EmployeeForm):
    class Meta(EmployeeForm.Meta):
        fields = EMPLOYEE_FIELDS


class SalaryInsuranceForm(StyledModelForm):
    class Meta:
        model = SalaryInsurance
        fields = [
            "bank",
            "account_no",
            "social_insurance_no",
            "health_insurance_no",
            "insured_category",
            "taxpayer_no",
            "has_disability",
        ]


class JobCorrectionForm(StyledModelForm):
    reason = forms.CharField(label="Засварын шалтгаан", widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = JobRecord
        fields = list(JobRecord.JOB_FIELDS)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["position"].queryset = Position.objects.filter(  # type: ignore[attr-defined]
            Q(active=True) | Q(pk=self.instance.position_id)
        )
        self.fields["department"].queryset = Department.objects.filter(  # type: ignore[attr-defined]
            Q(active=True) | Q(pk=self.instance.department_id)
        )
        self.fields["manager"].queryset = Employee.objects.exclude(  # type: ignore[attr-defined]
            pk=self.instance.employee_id
        )


class SalaryCorrectionForm(StyledForm):
    amount = forms.DecimalField(label="Үндсэн цалин", max_digits=14, decimal_places=2, min_value=0)
    reason = forms.CharField(label="Засварын шалтгаан", widget=forms.Textarea(attrs={"rows": 2}))


class SetSalaryForm(StyledForm):
    effective = forms.DateField(label="Хэдээс")
    amount = forms.DecimalField(label="Үндсэн цалин", max_digits=14, decimal_places=2, min_value=0)


FamilyFormSet: Any = inlineformset_factory(
    Employee, FamilyMember, fields=["name", "relation", "birth_year"], form=StyledModelForm, extra=1, can_delete=True
)
EducationFormSet: Any = inlineformset_factory(
    Employee,
    Education,
    fields=["school", "degree", "field", "graduation_year"],
    form=StyledModelForm,
    extra=1,
    can_delete=True,
)

TalentFormSet: Any = inlineformset_factory(
    Employee, Talent, fields=["name", "trained_year", "description"], form=StyledModelForm, extra=1, can_delete=True
)
GiftFormSet: Any = inlineformset_factory(
    Employee,
    Gift,
    fields=["gift_type", "given_date", "child_count", "amount", "note"],
    form=StyledModelForm,
    extra=1,
    can_delete=True,
)


class HireJobForm(StyledModelForm):
    start = forms.DateField(label="Ажилд орох огноо")

    class Meta:
        model = JobRecord
        fields = list(JobRecord.JOB_FIELDS)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["position"].queryset = Position.objects.filter(active=True)  # type: ignore[attr-defined]
        self.fields["department"].queryset = Department.objects.filter(active=True)  # type: ignore[attr-defined]
        self.fields["status"].initial = "active"


class HireExtrasForm(StyledForm):
    base_salary = forms.DecimalField(label="Үндсэн цалин", max_digits=14, decimal_places=2, min_value=0, required=False)
    create_login = forms.BooleanField(label="Нэвтрэх эрх үүсгэх", required=False)
    username = forms.CharField(label="Нэвтрэх нэр", required=False, max_length=150)

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if data.get("create_login"):
            username = (data.get("username") or "").strip()
            if not username:
                self.add_error("username", "Нэвтрэх нэрийг бичнэ үү.")
            elif User.objects.filter(username=username).exists():
                self.add_error("username", "Ийм нэвтрэх нэр аль хэдийн байна.")
        return data
