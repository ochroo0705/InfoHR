from typing import Any

from accounts.roles import ADMIN
from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from recruitment.models import RecruitmentSettings


@admin.register(RecruitmentSettings)
class RecruitmentSettingsAdmin(ModelAdmin):  # type: ignore[misc]
    """One row, edited by Admin only (superuser or the Admin role group); never deleted."""

    list_display = ("__str__", "retention_months")

    def _is_admin(self, request: HttpRequest) -> bool:
        user = request.user
        return bool(user.is_superuser or user.groups.filter(name=ADMIN).exists())

    def has_module_permission(self, request: HttpRequest) -> bool:
        return self._is_admin(request)

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self._is_admin(request)

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self._is_admin(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return self._is_admin(request) and not RecruitmentSettings.objects.exists()

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
