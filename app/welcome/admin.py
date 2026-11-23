from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from welcome.models import DemoRequest


@admin.register(DemoRequest)
# unfold ships no type stubs (ignore_missing_imports), so ModelAdmin is Any here; same ignore as app/leave/admin.py.
class DemoRequestAdmin(ModelAdmin):  # type: ignore[misc]
    """Read-only list of demo requests. They arrive from the public form; nobody edits them here."""

    list_display = ("created_at", "organisation", "name", "email", "phone", "size_band", "mail_status")
    list_filter = ("mail_status",)
    search_fields = ("organisation", "name", "email")
    readonly_fields = [field.name for field in DemoRequest._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
