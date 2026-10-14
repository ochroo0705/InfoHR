from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from .models import ActivityEntry, Department, Employee, JobRecord, Position, SalaryRecord


@admin.register(Department, Position)
class ReferenceAdmin(ModelAdmin):  # type: ignore[misc]
    list_display = ("name", "active")
    list_filter = ("active",)
    search_fields = ("name",)


class ReadOnlyAdmin(ModelAdmin):  # type: ignore[misc]
    """History is written only by services.history (spec §3)."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Employee)
class EmployeeAdmin(ReadOnlyAdmin):
    list_display = ("code", "family_name", "given_name", "erp_employee_id")
    search_fields = ("code", "family_name", "given_name", "register_no")


@admin.register(JobRecord, SalaryRecord)
class HistoryAdmin(ReadOnlyAdmin):
    list_display = ("employee", "period", "change_type", "created_at")


@admin.register(ActivityEntry)
class ActivityAdmin(ReadOnlyAdmin):
    list_display = ("employee", "at", "kind", "message", "personal", "sensitive")
