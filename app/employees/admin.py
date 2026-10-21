from typing import Any, cast

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Model
from django.http import HttpRequest
from lists.usage import usage_count
from unfold.admin import ModelAdmin

from .models import (
    ActivityEntry,
    CompanySettings,
    Department,
    DepartmentExt,
    Employee,
    JobRecord,
    Position,
    PositionExt,
    SalaryRecord,
)
from .services import macs_writes


class _RefForm(forms.ModelForm):  # type: ignore[type-arg]
    active = forms.BooleanField(label="Идэвхтэй", required=False, initial=True)


class ReferenceAdmin(ModelAdmin):  # type: ignore[misc]
    """Departments and positions are production rows (macs); the HR 'active' flag lives on their ext row.
    Saves and deletes go through macs_writes, the only production writer."""

    form = _RefForm
    fields = ["name", "active"]
    list_display = ("name", "is_active")
    list_filter = ("ext__active",)
    search_fields = ("name",)
    ext_model: type[Model]
    ext_link: str

    @admin.display(boolean=True, description="Идэвхтэй")
    def is_active(self, obj: Any) -> bool:
        ext = getattr(obj, "ext", None)
        return bool(ext and ext.active)

    def get_form(self, request: HttpRequest, obj: Any = None, **kwargs: Any) -> Any:
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["active"].initial = self.is_active(obj) if obj else True
        return form

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if obj is None or not super().has_delete_permission(request, obj):
            return False
        return usage_count(type(obj), obj.pk, exclude_tables=[self.ext_model._meta.db_table]) == 0

    @transaction.atomic
    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        saved = self.save_production(form.cleaned_data["name"], obj if change else None)
        cast(Any, self.ext_model).objects.update_or_create(
            **{self.ext_link: saved}, defaults={"active": form.cleaned_data["active"]}
        )
        obj.pk = saved.pk

    def delete_model(self, request: HttpRequest, obj: Any) -> None:
        try:
            self.delete_production(obj)
        except ValueError as error:
            self.message_user(request, str(error), level=messages.ERROR)

    def delete_queryset(self, request: HttpRequest, queryset: Any) -> None:
        for obj in queryset:
            self.delete_model(request, obj)


@admin.register(Department)
class DepartmentAdmin(ReferenceAdmin):
    ext_model = DepartmentExt
    ext_link = "department"

    def save_production(self, name: str, obj: Any) -> Any:
        return macs_writes.save_department(name, department=obj)

    def delete_production(self, obj: Any) -> None:
        macs_writes.delete_department(obj)


@admin.register(Position)
class PositionAdmin(ReferenceAdmin):
    ext_model = PositionExt
    ext_link = "position"

    def save_production(self, name: str, obj: Any) -> Any:
        return macs_writes.save_position(name, position=obj)

    def delete_production(self, obj: Any) -> None:
        macs_writes.delete_position(obj)


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
    list_display = ("code", "family_name", "given_name")
    search_fields = ("code", "family_name", "given_name", "register_no")


@admin.register(JobRecord, SalaryRecord)
class HistoryAdmin(ReadOnlyAdmin):
    list_display = ("employee", "period", "change_type", "created_at")


@admin.register(ActivityEntry)
class ActivityAdmin(ReadOnlyAdmin):
    list_display = ("employee", "at", "kind", "message", "personal", "sensitive")


@admin.register(CompanySettings)
class CompanySettingsAdmin(ModelAdmin):  # type: ignore[misc]
    """One row only (CompanySettings.get): it can be added once and never deleted."""

    fields = ["name", "director_name"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return not CompanySettings.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
