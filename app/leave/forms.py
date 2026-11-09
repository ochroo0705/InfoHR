from datetime import date
from typing import Any

from accounts.roles import ROLE_LABELS
from django import forms
from django.contrib.auth.models import Group
from django.db.models import Q, QuerySet
from django.http import QueryDict
from employees.forms import StyledForm
from employees.models import Employee
from macs.models import LeaveTypeRow

from leave.models import LeaveTypeExt
from leave.services.records import Draft
from leave.services.requests import requestable_types
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
        self.fields["leave_type"].widget.attrs["aria-label"] = "Чөлөөний төрөл"

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


REQUEST_TOO_LONG = "Тайлбар 200 тэмдэгтээс урт байж болохгүй."
REQUEST_BACKWARDS = "Дуусах огноо эхлэх огнооноос өмнө байж болохгүй."


class RequestForm(StyledForm):
    """The staff leave request (spec 5.3). No employee field: the view always uses the logged-in user's own record."""

    leave_type = forms.ModelChoiceField(label="Төрөл", queryset=LeaveTypeRow.objects.none())
    start_date = forms.DateField(label="Эхлэх", widget=DATE)
    end_date = forms.DateField(label="Дуусах", widget=DATE)
    note = forms.CharField(
        label="Тайлбар",
        required=False,
        max_length=200,
        widget=forms.Textarea(attrs={"rows": 2}),
        error_messages={"max_length": REQUEST_TOO_LONG},
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["leave_type"].queryset = requestable_types()  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError(REQUEST_BACKWARDS)
        return cleaned


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


TOO_LONG_REASON = "Шалтгаан 200 тэмдэгтээс урт байж болохгүй."


class ApproveForm(StyledForm):
    """Approver's optional reason, asked only when the balance would go negative (spec 5.3)."""

    override_reason = forms.CharField(
        label="Үлдэгдэл хүрэлцэхгүй бол шалтгаан",
        required=False,
        max_length=200,
        error_messages={"max_length": TOO_LONG_REASON},
    )


class RejectForm(StyledForm):
    reason = forms.CharField(
        label="Татгалзсан шалтгаан",
        max_length=200,
        widget=forms.Textarea(attrs={"rows": 2}),
        error_messages={"required": "Татгалзсан шалтгаан бичнэ үү.", "max_length": TOO_LONG_REASON},
    )


class LeaveTypeForm(StyledForm):
    name = forms.CharField(label="Нэр", max_length=200)
    is_paid = forms.BooleanField(
        label="Цалинтай", required=False, help_text="Тэмдэглэгээ: энэ төрлийн чөлөө цалинтай эсэхийг харуулна."
    )
    uses_annual_balance = forms.BooleanField(
        label="Ээлжийн амралтаас хасна",
        required=False,
        help_text="Авсан хоног ээлжийн амралтын эрх, үлдэгдлээс хасагдана.",
    )
    is_active = forms.BooleanField(
        label="Идэвхтэй",
        required=False,
        initial=True,
        help_text="Унтраавал чөлөө бүртгэх жагсаалтад энэ төрөл харагдахгүй. Өмнөх бүртгэл хэвээр үлдэнэ.",
    )
    order = forms.IntegerField(
        label="Жагсаалтад гарах дараалал", min_value=0, max_value=32767, initial=0
    )
    staff_may_request = forms.BooleanField(
        label="Ажилтан хүсэлт гаргана",
        required=False,
        initial=True,
        help_text="Унтраавал ажилтан өөрөө хүсэлт гаргаж чадахгүй; шууд бүртгэнэ.",
    )


MANAGER_CHOICE = "manager"
GROUP_PREFIX = "group:"


def _parse_step(value: str) -> tuple[int | None, bool]:
    """Stored form of one approval step: (group id, manager flag). Empty means no step."""
    if value == MANAGER_CHOICE:
        return None, True
    if value.startswith(GROUP_PREFIX):
        return int(value.removeprefix(GROUP_PREFIX)), False
    return None, False


def encode_step(group_id: int | None, manager: bool) -> str:
    """The dropdown value that shows a stored step."""
    if group_id is not None:
        return f"{GROUP_PREFIX}{group_id}"
    return MANAGER_CHOICE if manager else ""


class ApprovalSettingsForm(StyledForm):
    """Who approves leave requests, step by step (spec 5.1). Role choices are read when the form is made."""

    step1 = forms.ChoiceField(
        label="Чөлөө батлах",
        required=False,
        error_messages={"invalid_choice": "Жагсаалтаас сонгоно уу."},
    )
    step2 = forms.ChoiceField(
        label="Дараа нь батлах",
        required=False,
        error_messages={"invalid_choice": "Жагсаалтаас сонгоно уу."},
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        roles = [(f"{GROUP_PREFIX}{g.pk}", ROLE_LABELS.get(g.name, g.name)) for g in Group.objects.order_by("name")]
        manager = [(MANAGER_CHOICE, "Шууд удирдлага")]
        step1 = self.fields["step1"]
        step2 = self.fields["step2"]
        if isinstance(step1, forms.ChoiceField) and isinstance(step2, forms.ChoiceField):
            step1.choices = [("", "Батлахгүй"), *manager, *roles]
            step2.choices = [("", "—"), *manager, *roles]

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        if not cleaned.get("step1"):
            cleaned["step2"] = ""  # step 2 only exists when step 1 is set
        return cleaned

    def settings_values(self) -> dict[str, Any]:
        """Field values for LeaveSettings, from the cleaned choices."""
        group1, manager1 = _parse_step(self.cleaned_data["step1"])
        group2, manager2 = _parse_step(self.cleaned_data["step2"])
        return {
            "approval1_group_id": group1,
            "approval1_manager": manager1,
            "approval2_group_id": group2,
            "approval2_manager": manager2,
        }


def initial_dates(today: date) -> dict[str, date]:
    return {"start_date": today, "end_date": today}
