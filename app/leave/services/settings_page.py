"""The settings page's rules: the leave type list, the type form's starting values, the approval choices and the saves.

Called by the Django views in app/leave/views.py. Rules only; drawing is the caller's job.
"""

from typing import Any, cast

from django import forms
from django.db import transaction
from macs.models import LeaveTypeRow

from leave.forms import ApprovalSettingsForm, encode_step
from leave.models import LeaveSettings, LeaveTypeExt, type_ext


def type_rows() -> list[tuple[LeaveTypeRow, LeaveTypeExt]]:
    found = [(row, type_ext(row)) for row in LeaveTypeRow.objects.all()]
    return sorted(found, key=lambda pair: (pair[1].order, pair[0].name))


def type_initial(row: LeaveTypeRow) -> dict[str, object]:
    ext = type_ext(row)
    return {
        "name": row.name,
        "is_paid": ext.is_paid,
        "uses_annual_balance": ext.uses_annual_balance,
        "is_active": ext.is_active,
        "order": ext.order,
        "staff_may_request": ext.staff_may_request,
    }


def ext_values(cleaned: dict[str, object]) -> dict[str, object]:
    return {
        "is_paid": cleaned["is_paid"],
        "uses_annual_balance": cleaned["uses_annual_balance"],
        "is_active": cleaned["is_active"],
        "order": cleaned["order"],
        "staff_may_request": cleaned["staff_may_request"],
    }


def approval_choices() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    form = ApprovalSettingsForm()
    step1 = cast(forms.ChoiceField, form.fields["step1"])
    step2 = cast(forms.ChoiceField, form.fields["step2"])
    return list(step1.choices), list(step2.choices)


def approval_initial(setting: LeaveSettings) -> dict[str, str]:
    return {
        "step1": encode_step(setting.approval1_group_id, setting.approval1_manager),
        "step2": encode_step(setting.approval2_group_id, setting.approval2_manager),
    }


def save_approval(setting: LeaveSettings, values: dict[str, Any]) -> None:
    values["approval_role_removed"] = False  # the admin has now chosen again
    for field, value in values.items():
        setattr(setting, field, value)
    with transaction.atomic():  # the audit line is written after the save, so both must commit together
        setting.save(update_fields=list(values))


def save_auto_grant(setting: LeaveSettings, on: bool) -> None:
    setting.auto_annual_grant = on
    with transaction.atomic():  # the audit line is written after the save, so both must commit together
        setting.save(update_fields=["auto_annual_grant"])
