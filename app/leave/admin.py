from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from leave import access
from leave.models import AnnualLeaveRule, Holiday, LeaveType


class SettingsAdmin(ModelAdmin):  # type: ignore[misc]
    """Editable by whoever has the leave-settings switch (models have no default permissions)."""

    def has_module_permission(self, request: HttpRequest) -> bool:
        return access.can_manage_settings(request.user)  # type: ignore[arg-type]

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)

    has_add_permission = has_module_permission

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # deactivate types / add a new rule row instead


@admin.register(LeaveType)
class LeaveTypeAdmin(SettingsAdmin):
    list_display = ("name", "code", "is_paid", "uses_annual_balance", "is_active", "order")


@admin.register(AnnualLeaveRule)
class AnnualLeaveRuleAdmin(SettingsAdmin):
    list_display = ("effective_from", "base_days", "min_continuous_part", "eligibility_months")


@admin.register(Holiday)
class HolidayAdmin(SettingsAdmin):
    list_display = ("date", "name")
