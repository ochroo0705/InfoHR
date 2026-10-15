from datetime import date
from typing import Any

from django import forms
from django.db.models import Q, QuerySet
from employees.forms import StyledForm
from employees.models import Employee

from leave.models import LeaveType
from leave.services.records import Draft

DATE = forms.DateInput(attrs={"type": "date"})


class LeaveForm(StyledForm):
    employee = forms.ModelChoiceField(label="Ажилтан", queryset=Employee.objects.none())
    leave_type = forms.ModelChoiceField(label="Төрөл", queryset=LeaveType.objects.filter(is_active=True))
    start_date = forms.DateField(label="Эхлэх", widget=DATE)
    end_date = forms.DateField(label="Дуусах", widget=DATE)
    start_half = forms.BooleanField(label="Эхний өдөр хагас", required=False)
    end_half = forms.BooleanField(label="Сүүлийн өдөр хагас", required=False)
    note = forms.CharField(label="Тайлбар", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    override_reason = forms.CharField(label="Үлдэгдэл хүрэлцэхгүй бол шалтгаан", required=False)

    def __init__(
        self, *args: Any, employees: QuerySet[Employee], current_type: LeaveType | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        if current_type is not None:
            self.fields["leave_type"].queryset = LeaveType.objects.filter(  # type: ignore[attr-defined]
                Q(is_active=True) | Q(pk=current_type.pk)
            )
        self.fields["employee"].queryset = employees  # type: ignore[attr-defined]

    def draft(self, leave_id: int | None = None) -> Draft:
        d = self.cleaned_data
        return Draft(
            employee=d["employee"],
            leave_type=d["leave_type"],
            start_date=d["start_date"],
            end_date=d["end_date"],
            start_half=d["start_half"],
            end_half=d["end_half"],
            note=d["note"],
            override_reason=d["override_reason"],
            leave_id=leave_id,
        )


class CancelForm(StyledForm):
    reason = forms.CharField(label="Шалтгаан", max_length=200)


class AdjustForm(StyledForm):
    days = forms.DecimalField(label="Хоног (+/−)", max_digits=5, decimal_places=1)
    reason = forms.CharField(label="Шалтгаан", max_length=200)


class CarryOverForm(StyledForm):
    days = forms.DecimalField(label="Шилжүүлэх хоног", max_digits=5, decimal_places=1, min_value=0)
    reason = forms.CharField(label="Шалтгаан", max_length=200)


def initial_dates(today: date) -> dict[str, date]:
    return {"start_date": today, "end_date": today}
