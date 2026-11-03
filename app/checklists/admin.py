from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin, TabularInline

from checklists.forms import ChecklistTemplateForm, ChecklistTemplateTaskForm
from checklists.models import ChecklistTemplate, ChecklistTemplateTask


class ManageChecklistsMixin:
    """The models have no default permissions: the editor is open to the manage_checklists right only."""

    def has_module_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("checklists.manage_checklists")

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)


class ChecklistTemplateTaskInline(ManageChecklistsMixin, TabularInline):  # type: ignore[misc]
    model = ChecklistTemplateTask
    form = ChecklistTemplateTaskForm
    extra = 0
    fields = ("position", "title", "owner", "due_offset_days", "required")


@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(ManageChecklistsMixin, ModelAdmin):  # type: ignore[misc]
    form = ChecklistTemplateForm
    list_display = ("name", "kind", "is_default", "active")
    list_filter = ("kind", "active")
    inlines = [ChecklistTemplateTaskInline]
