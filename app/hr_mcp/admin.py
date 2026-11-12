from typing import Any, cast

from accounts.models import User
from django import forms
from django.contrib import admin, messages
from django.http import HttpRequest
from django.utils.html import format_html
from employees.forms import StyledModelForm
from unfold.admin import ModelAdmin

from hr_mcp.models import McpCall, McpToken
from hr_mcp.tokens import issue_token, revoke


class SuperuserOnlyMixin:
    """The MCP screens are for the technical super admin only, whatever other rights a user holds."""

    def has_module_permission(self, request: HttpRequest) -> bool:
        return bool(request.user.is_superuser)

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return self.has_module_permission(request)

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_module_permission(request)


class McpTokenAddForm(StyledModelForm):
    class Meta:
        model = McpToken
        fields = ("user", "name")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "user" in self.fields:  # the read-only change page has no form fields
            user_field = cast("forms.ModelChoiceField[Any]", self.fields["user"])
            user_field.queryset = User.objects.filter(is_active=True).order_by("username")


@admin.register(McpToken)
class McpTokenAdmin(SuperuserOnlyMixin, ModelAdmin):  # type: ignore[misc]
    """Tokens are issued here and revoked, never edited. The hash is never shown; the raw token once, on issue.
    Rows are not deleted: a deleted token takes its call log with it (McpCall cascades), so revoke instead."""

    form = McpTokenAddForm
    list_display = ("name", "user", "prefix", "created_at", "last_used_at", "revoked_at")
    list_select_related = ("user",)
    search_fields = ("name", "prefix")
    actions = ("revoke_selected",)

    def get_fields(self, request: HttpRequest, obj: Any = None) -> list[str]:
        if obj is None:
            return ["user", "name"]
        return ["user", "name", "prefix", "created_at", "last_used_at", "revoked_at"]

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> list[str]:
        if obj is None:
            return []
        return self.get_fields(request, obj)

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # the change page is a read-only view; only revoke changes a token

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # deleting a token would cascade-delete its call log; revoke instead

    def save_model(self, request: HttpRequest, obj: McpToken, form: forms.Form, change: bool) -> None:
        """Issue through hr_mcp.tokens (the hash is made there). The raw token leaves in one warning only."""
        if change:
            return
        row, raw = issue_token(obj.user, obj.name)
        obj.pk = row.pk
        obj.prefix = row.prefix
        obj.token_hash = row.token_hash
        obj.created_at = row.created_at
        obj._state.adding = False
        messages.warning(
            request,
            format_html(
                "Токен: <code>{}</code> — энэ токеныг одоо хуулж аваарай. "
                "Зөвхөн одоо харагдана; дараа нь дахин харагдахгүй.",
                raw,
            ),
        )

    @admin.action(description="Цуцлах")
    def revoke_selected(self, request: HttpRequest, queryset: Any) -> None:
        count = 0
        for token in queryset.filter(revoked_at__isnull=True):
            revoke(token)
            count += 1
        messages.success(request, f"{count} токеныг цуцаллаа")


@admin.register(McpCall)
class McpCallAdmin(SuperuserOnlyMixin, ModelAdmin):  # type: ignore[misc]
    """The call log is a record: read-only, nothing added, changed or deleted here."""

    list_display = ("at", "token", "tool", "ok", "reason", "row_count", "duration_ms")
    list_select_related = ("token",)
    list_filter = ("ok", "tool")
    ordering = ("-at",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
