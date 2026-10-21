from datetime import date
from typing import Any

from django import forms
from django.db.models import Q, QuerySet
from django.http import QueryDict
from employees.forms import StyledForm
from employees.models import Employee
from macs.models import LeaveTypeRow

from leave.models import LeaveTypeExt
from leave.services.records import Draft
from leave.services.writes import AssignSnapshot

DATE = forms.DateInput(attrs={"type": "date"})


def active_types(current: LeaveTypeRow | None = None) -> QuerySet[LeaveTypeRow]:
    """Leave types a user may pick: every type not marked inactive, plus the one a leave already has."""
    visible = ~Q(pk__in=LeaveTypeExt.objects.filter(is_active=False).values("pk"))
    if current is not None:
        visible |= Q(pk=current.pk)
    return LeaveTypeRow.objects.filter(visible)


class LeaveForm(StyledForm):
    employee = forms.ModelChoiceField(label="Ажилтан", queryset=Employee.objects.none())
    leave_type = forms.ModelChoiceField(label="Төрөл", queryset=LeaveTypeRow.objects.none())
    start_date = forms.DateField(label="Эхлэх", widget=DATE)
    end_date = forms.DateField(label="Дуусах", widget=DATE)
    note = forms.CharField(label="Тайлбар", required=False, max_length=200, widget=forms.Textarea(attrs={"rows": 2}))
    override_reason = forms.CharField(label="Үлдэгдэл хүрэлцэхгүй бол шалтгаан", required=False, max_length=200)

    def __init__(
        self, *args: Any, employees: QuerySet[Employee], current_type: LeaveTypeRow | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["leave_type"].queryset = active_types(current_type)  # type: ignore[attr-defined]
        self.fields["employee"].queryset = employees  # type: ignore[attr-defined]

    def draft(self, leave_id: int | None = None, loaded: AssignSnapshot | None = None) -> Draft:
        d = self.cleaned_data
        return Draft(
            employee=d["employee"],
            leave_type=d["leave_type"],
            start_date=d["start_date"],
            end_date=d["end_date"],
            note=d["note"],
            override_reason=d["override_reason"],
            leave_id=leave_id,
            loaded=loaded,
        )


def _optional_int(value: str) -> int | None:
    return int(value) if value else None


def _posted(data: QueryDict, key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def loaded_from_post(data: QueryDict) -> AssignSnapshot | None:
    """The row as the form loaded it (hidden fields, see leave/_loaded.html); None when a field is missing or bad.

    An absent `loaded_comment` means the row's comment was NULL, and a present one is the text (maybe empty).
    """
    raw_type = _posted(data, "loaded_type")
    raw_date1 = _posted(data, "loaded_date1")
    raw_date2 = _posted(data, "loaded_date2")
    if raw_type is None or raw_date1 is None or raw_date2 is None:
        return None
    try:
        return AssignSnapshot(
            leave_type_id=int(raw_type),
            date1=date.fromisoformat(raw_date1),
            date2=date.fromisoformat(raw_date2),
            status=_optional_int(_posted(data, "loaded_status") or ""),
            adays=_optional_int(_posted(data, "loaded_adays") or ""),
            comment=_posted(data, "loaded_comment"),
        )
    except ValueError:
        return None


class CancelForm(StyledForm):
    reason = forms.CharField(label="Шалтгаан", max_length=200)


class AdjustForm(StyledForm):
    days = forms.IntegerField(label="Хоног (+/−)", min_value=-1000, max_value=1000)
    reason = forms.CharField(label="Шалтгаан", max_length=200)


class CarryOverForm(StyledForm):
    days = forms.IntegerField(label="Шилжүүлэх хоног", min_value=1, max_value=1000)
    reason = forms.CharField(label="Шалтгаан", max_length=200)


class GrantForm(StyledForm):
    start = forms.DateField(label="Эхлэх", widget=DATE)
    end = forms.DateField(label="Дуусах", widget=DATE)
    days = forms.IntegerField(label="Хоног", min_value=-1000, max_value=1000)
    reason = forms.CharField(label="Шалтгаан", max_length=200)


class LeaveTypeForm(StyledForm):
    name = forms.CharField(label="Нэр", max_length=200)
    is_paid = forms.BooleanField(label="Цалинтай", required=False)
    uses_annual_balance = forms.BooleanField(label="Ээлжийн амралтаас хасна", required=False)
    is_active = forms.BooleanField(label="Идэвхтэй", required=False, initial=True)
    order = forms.IntegerField(label="Дараалал", min_value=0, max_value=32767, initial=0)


def initial_dates(today: date) -> dict[str, date]:
    return {"start_date": today, "end_date": today}
