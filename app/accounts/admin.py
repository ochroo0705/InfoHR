from typing import Any

from django import forms
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission
from django.db.models import ManyToManyField
from django.http import HttpRequest
from django.utils.translation import gettext as _
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminCheckboxSelectMultiple

from .models import User

admin.site.unregister(Group)

# Apps whose permissions never appear in the role editor (Django internals).
HIDDEN_PERMISSION_APPS = ("admin", "auth", "contenttypes", "sessions")


class GroupedCheckboxes(UnfoldAdminCheckboxSelectMultiple):  # type: ignore[misc]
    """Checkboxes in titled cards. Set .choices to [(group label, [(value, label), ...]), ...]."""

    template_name = "accounts/widgets/grouped_checkboxes.html"


def permission_group(permission: Permission) -> str:
    """Card title: one card per module (app). The accounts app holds the cross-module switches."""
    app_label = permission.content_type.app_label
    if app_label == "accounts":
        return _("Switches")
    return str(apps.get_app_config(app_label).verbose_name)


def is_default_permission(permission: Permission) -> bool:
    """Django's own add/change/delete/view_<model>; custom switches like view_salary are not."""
    model_class = permission.content_type.model_class()
    action, _sep, model = permission.codename.partition("_")
    return (
        model_class is not None
        and action in model_class._meta.default_permissions
        and model == model_class._meta.model_name
    )


def permission_label(permission: Permission) -> str:
    """Translated label. Django stores default names ("Can add user") in English; those show
    just the verb, because the card title already names the model."""
    if is_default_permission(permission):
        verbs = {"add": _("Add"), "change": _("Change"), "delete": _("Delete"), "view": _("View")}
        return verbs[permission.codename.partition("_")[0]]
    return permission.name


class PermissionField(forms.ModelMultipleChoiceField):  # type: ignore[type-arg]
    """Permissions grouped into cards: switches first, then one card per model.

    Grouping lives in the choices getter because Django rebuilds widget.choices from the
    queryset whenever the form is copied.
    """

    def label_from_instance(self, obj: Any) -> str:
        return permission_label(obj)

    def _get_grouped_choices(self) -> list[tuple[str, list[tuple[int, str]]]]:
        grouped: dict[str, list[tuple[int, str]]] = {_("Switches"): []}
        for permission in self.queryset or []:
            grouped.setdefault(permission_group(permission), []).append((permission.pk, permission_label(permission)))
        return [(group, options) for group, options in grouped.items() if options]

    choices = property(_get_grouped_choices, vars(forms.ChoiceField)["choices"].fset)


def permission_queryset() -> Any:
    """Business-action permissions only (COWORK T-002): Django's default add/change/delete/view
    per model and internal apps are hidden."""
    candidates = Permission.objects.exclude(content_type__app_label__in=HIDDEN_PERMISSION_APPS).select_related(
        "content_type"
    )
    keep = [p.pk for p in candidates if not is_default_permission(p)]
    return Permission.objects.filter(pk__in=keep).select_related("content_type").order_by("content_type", "id")


def permission_formfield(**kwargs: Any) -> PermissionField:
    return PermissionField(queryset=permission_queryset(), widget=GroupedCheckboxes, required=False, **kwargs)


@admin.register(User)
class UserAdmin(BaseUserAdmin[User], ModelAdmin):  # type: ignore[misc]
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_display = ("username", "first_name", "last_name", "is_active", "last_login")

    def formfield_for_manytomany(self, db_field: ManyToManyField[Any, Any], request: HttpRequest, **kwargs: Any) -> Any:
        if db_field.name == "user_permissions":
            return permission_formfield(label=db_field.verbose_name.capitalize(), help_text="")
        if db_field.name == "groups":
            kwargs.update(widget=UnfoldAdminCheckboxSelectMultiple, help_text="")
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):  # type: ignore[misc]
    def formfield_for_manytomany(self, db_field: ManyToManyField[Any, Any], request: HttpRequest, **kwargs: Any) -> Any:
        if db_field.name == "permissions":
            return permission_formfield(label=db_field.verbose_name.capitalize())
        return super().formfield_for_manytomany(db_field, request, **kwargs)
