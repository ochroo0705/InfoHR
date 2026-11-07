from typing import Any, cast

from django import forms
from django.apps import apps
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db.models import ManyToManyField
from django.forms.models import BaseInlineFormSet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext as _
from employees.forms import StyledModelForm
from macs.models import Branch, Department
from unfold.admin import ModelAdmin, StackedInline
from unfold.forms import UserChangeForm
from unfold.widgets import UnfoldAdminCheckboxSelectMultiple, UnfoldAdminTextInputWidget

from .audit import Category, record_safe
from .models import AccessScope, User
from .passwords import set_temp_password

admin.site.unregister(Group)

# Apps whose permissions never appear in the role editor (Django internals).
HIDDEN_PERMISSION_APPS = ("admin", "auth", "contenttypes", "sessions")


class GroupedCheckboxes(UnfoldAdminCheckboxSelectMultiple):  # type: ignore[misc]
    """Checkboxes in titled cards. Set .choices to [(group label, [(value, label), ...]), ...]."""

    template_name = "accounts/widgets/grouped_checkboxes.html"


class UserPermissionCheckboxes(GroupedCheckboxes):
    """Also carries each role's permissions, so the page can show what the ticked roles give
    (static/js/admin_effective_perms.js): those boxes show ticked and greyed, display only."""

    def get_context(self, name: str, value: Any, attrs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context(name, value, attrs)
        context["widget"]["role_permissions"] = {
            str(group.pk): {"name": group.name, "perms": [p.pk for p in group.permissions.all()]}
            for group in Group.objects.prefetch_related("permissions")
        }
        return context


def _card_app_label(permission: Permission) -> str:
    # The employee switches sit on the production table model (macs.Employee), so they show under Ажилтан.
    app_label = permission.content_type.app_label
    return {"macs": "employees"}.get(app_label, app_label)


# The order of the module cards after the Switches card. Fixed here, because the database's content type ids
# (which the permission rows arrive in) differ between databases: the Firebird template orders them otherwise.
CARD_ORDER = ("accounts", "employees", "checklists", "leave", "lists", "recruitment", "reports")


def permission_group(permission: Permission) -> str:
    """Card title: one card per module (app). The accounts app holds the cross-module switches."""
    app_label = _card_app_label(permission)
    if app_label == "accounts":
        return _("Switches")
    return str(apps.get_app_config(app_label).verbose_name)


def _card_rank(permission: Permission) -> int:
    app_label = _card_app_label(permission)
    return CARD_ORDER.index(app_label) if app_label in CARD_ORDER else len(CARD_ORDER)


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
        for permission in sorted(self.queryset or [], key=_card_rank):  # stable: keeps the order inside a card
            grouped.setdefault(permission_group(permission), []).append((permission.pk, permission_label(permission)))
        return [(group, options) for group, options in grouped.items() if options]

    choices = property(_get_grouped_choices, vars(forms.ChoiceField)["choices"].fset)


def permission_queryset() -> Any:
    """Business-action permissions only (COWORK T-002): Django's default add/change/delete/view
    per model and internal apps are hidden, and so are leftovers of a removed app or model (payroll, D-038),
    whose rows stay in the database but have no card to go in."""
    candidates = Permission.objects.exclude(content_type__app_label__in=HIDDEN_PERMISSION_APPS).select_related(
        "content_type"
    )
    keep = [p.pk for p in candidates if p.content_type.model_class() is not None and not is_default_permission(p)]
    return Permission.objects.filter(pk__in=keep).select_related("content_type").order_by("content_type", "id")


def permission_formfield(widget: type[GroupedCheckboxes] = GroupedCheckboxes, **kwargs: Any) -> PermissionField:
    return PermissionField(queryset=permission_queryset(), widget=widget, required=False, **kwargs)


class TempPasswordUserCreationForm(forms.ModelForm):  # type: ignore[type-arg]
    """New user: only the name. The password is a temporary one made on save (D-014)."""

    class Meta:
        model = User
        fields = ("username",)
        widgets = {"username": UnfoldAdminTextInputWidget}


class TempPasswordWidget(forms.Widget):
    """Instead of the hash details: one button to the «Түр нууц үг үүсгэх» page."""

    def render(self, name: str, value: Any, attrs: Any = None, renderer: Any = None) -> SafeString:
        return mark_safe(  # noqa: S308 (fixed text, nothing from input)
            '<a href="../password/" class="bg-primary-600 font-medium inline-block px-3 py-2 rounded-default'
            ' text-sm text-white">Түр нууц үг үүсгэх</a>'
            '<p class="mt-2 text-sm text-base-500">Нууц үгийг хэн ч сонгохгүй: шинэ түр нууц үг нэг удаа харагдана,'
            " ажилтан анх нэвтрэхдээ солино.</p>"
        )


SWITCH_LABELS = {
    "is_active": (
        "Идэвхтэй",
        "Унтраавал нэвтэрч чадахгүй, мэдээлэл нь устахгүй. Ажлаас гарсан хүнд унтраана.",
    ),
    "is_staff": (
        "Удирдлагын хэсэгт нэвтрэх",
        "Энэ удирдлагын хэсэгт (/admin) нэвтэрнэ. Юу хийж болох нь доорх эрхээс хамаарна. "
        "Хүний нөөцийн үндсэн дэлгэцүүдэд хэрэггүй.",
    ),
    "is_superuser": (
        "Бүх эрхтэй (супер админ)",
        "Доорх бүлэг, эрхээс үл хамааран бүх зүйлийг харж, засна (цалин, хувийн мэдээлэл ч мөн). "
        "Зөвхөн техникийн админд.",
    ),
}


LAST_ADMIN_MESSAGE = "Сүүлийн супер админы эрхийг хасах боломжгүй: дор хаяж нэг идэвхтэй супер админ үлдэнэ."


def _admins() -> Any:
    """Users who can still run the back office: active, admin console access and every permission."""
    return User.objects.filter(is_active=True, is_staff=True, is_superuser=True)


def is_last_admin(user: User) -> bool:
    return user.pk is not None and not _admins().exclude(pk=user.pk).exists() and _admins().filter(pk=user.pk).exists()


class TempPasswordUserChangeForm(UserChangeForm):  # type: ignore[misc]
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "password" in self.fields:
            self.fields["password"].widget = TempPasswordWidget()
            self.fields["password"].help_text = ""
        for name, (label, help_text) in SWITCH_LABELS.items():  # Django's own Mongolian wording is unclear
            if name in self.fields:
                self.fields[name].label = label
                self.fields[name].help_text = help_text
        if self.instance.pk is not None and is_last_admin(self.instance):  # locked up front: no failed save
            for name in ("is_active", "is_staff", "is_superuser"):
                if name in self.fields:
                    self.fields[name].disabled = True
                    self.fields[
                        name
                    ].help_text = "Сүүлийн супер админ тул унтраах боломжгүй. Эхлээд өөр супер админ нэмнэ үү."

    def clean(self) -> Any:
        data = super().clean()
        stays_admin = all(
            data.get(name, getattr(self.instance, name)) for name in ("is_active", "is_staff", "is_superuser")
        )
        if not stays_admin and is_last_admin(User.objects.get(pk=self.instance.pk)):
            raise forms.ValidationError(LAST_ADMIN_MESSAGE)
        return data


def _show_once(request: HttpRequest, user: User, password: str) -> None:
    messages.warning(
        request,
        format_html(
            "<b>{}</b> — түр нууц үг: <code>{}</code>. Зөвхөн одоо харагдана; ажилтанд өгнө, анх нэвтрэхдээ солино.",
            user.get_username(),
            password,
        ),
    )


def _log_reset(user: User, by: User) -> None:
    from employees.models import ActivityEntry, ActivityKind, Employee

    employee = Employee.objects.filter(ext__user=user).first()
    if employee is not None:
        ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.CHANGED, message="Нууц үг шинэчилсэн")


class AccessScopeForm(StyledModelForm):
    """«Үзэх хүрээ» block of the user page. The ids are stored as plain int lists (AccessScope)."""

    branch_ids = forms.MultipleChoiceField(
        label="Салбар",
        required=False,
        widget=UnfoldAdminCheckboxSelectMultiple,
        help_text="Сонгосон салбарын ажилтнууд.",
    )
    department_ids = forms.MultipleChoiceField(
        label="Хэлтэс",
        required=False,
        widget=UnfoldAdminCheckboxSelectMultiple,
        help_text="Сонгосон хэлтсийн ажилтнууд.",
    )

    class Meta:
        model = AccessScope
        fields = ("limited", "branch_ids", "department_ids", "include_sub_departments", "own_team")
        labels = {
            "limited": "Хязгаарлах",
            "include_sub_departments": "Дэд хэлтсүүдийг оролцуулах",
            "own_team": "Миний удирдлаган дахь ажилтнууд",
        }
        help_texts = {
            "limited": (
                "Идэвхжүүлээд салбар, хэлтэс, баг сонгоогүй бол хэрэглэгч зөвхөн өөрийн бүртгэлийг харна. "
                "Админ эрхтэй хэрэглэгч хэзээ ч хязгаарлагдахгүй."
            ),
            "include_sub_departments": "Хэлтэс сонгосон бол түүний дэд хэлтсийн ажилтнуудыг ч харуулна.",
            "own_team": "Энэ хэрэглэгч удирдаж буй ажилтнуудыг харна.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        branch_field = cast(forms.MultipleChoiceField, self.fields["branch_ids"])
        department_field = cast(forms.MultipleChoiceField, self.fields["department_ids"])
        branch_field.choices = [(b.pk, b.name) for b in Branch.objects.order_by("name")]
        department_field.choices = [(d.pk, d.name or f"№{d.pk}") for d in Department.objects.order_by("name")]
        for name in ("branch_ids", "department_ids"):
            self.fields[name].widget.attrs.pop("class", None)  # checkbox list, not a text box
        if self.instance.pk is not None:
            self.initial["branch_ids"] = [str(pk) for pk in self.instance.branch_ids]
            self.initial["department_ids"] = [str(pk) for pk in self.instance.department_ids]

    def clean_branch_ids(self) -> list[int]:
        return [int(value) for value in self.cleaned_data.get("branch_ids", [])]

    def clean_department_ids(self) -> list[int]:
        return [int(value) for value in self.cleaned_data.get("department_ids", [])]


class AccessScopeFormSet(BaseInlineFormSet):  # type: ignore[type-arg]
    """A POST without the block (scripts, older forms) changes nothing: no rows are read or saved."""

    def __init__(self, data: Any = None, *args: Any, **kwargs: Any) -> None:
        prefix = kwargs.get("prefix") or self.get_default_prefix()
        if data is not None and f"{prefix}-TOTAL_FORMS" not in data:
            data = data.copy()
            data[f"{prefix}-TOTAL_FORMS"] = "0"
            data[f"{prefix}-INITIAL_FORMS"] = "0"
        super().__init__(data, *args, **kwargs)


class AccessScopeInline(StackedInline):  # type: ignore[misc]
    model = AccessScope
    form = AccessScopeForm
    formset = AccessScopeFormSet
    fields = ("limited", "branch_ids", "department_ids", "include_sub_departments", "own_team")
    max_num = 1
    extra = 1
    can_delete = False
    verbose_name = "Үзэх хүрээ"
    verbose_name_plural = "Үзэх хүрээ"


@admin.register(User)
class UserAdmin(BaseUserAdmin[User], ModelAdmin):  # type: ignore[misc]
    """Passwords are never typed here: a new user and «Түр нууц үг үүсгэх» both get a temporary one (D-014)."""

    form = TempPasswordUserChangeForm
    add_form = TempPasswordUserCreationForm
    inlines = [AccessScopeInline]
    add_fieldsets = ((None, {"fields": ("username",)}),)
    change_user_password_template = "admin/accounts/user/temp_password.html"  # noqa: S105 (a template path)
    list_display = ("username", "first_name", "last_name", "is_active", "last_login")

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if obj is not None and is_last_admin(obj):
            return False  # hides the delete button; the delete page answers 403
        return bool(super().has_delete_permission(request, obj))

    def delete_queryset(self, request: HttpRequest, queryset: Any) -> None:
        """Bulk delete: refused whole if it would remove every remaining super admin."""
        if _admins().exists() and not _admins().exclude(pk__in=queryset.values("pk")).exists():
            messages.error(request, LAST_ADMIN_MESSAGE)
            return
        super().delete_queryset(request, queryset)

    def save_model(self, request: HttpRequest, obj: User, form: Any, change: bool) -> None:
        password = None if change else set_temp_password(obj, save=False)
        super().save_model(request, obj, form, change)
        if password is not None:
            _show_once(request, obj, password)

    def user_change_password(self, request: HttpRequest, id: str, form_url: str = "") -> HttpResponse:
        user = get_object_or_404(self.get_queryset(request), pk=id)
        if not self.has_change_permission(request, user):
            raise PermissionDenied
        if request.method == "POST":
            password = set_temp_password(user)
            assert isinstance(request.user, User)
            _log_reset(user, request.user)
            record_safe(
                Category.ACCESS,
                "password_reset",
                actor=request.user,
                target_type="user",
                target_label=user.get_username(),
            )
            _show_once(request, user, password)
            return redirect(reverse(f"{self.admin_site.name}:accounts_user_change", args=[user.pk]))
        context = {
            **self.admin_site.each_context(request),
            "title": "Түр нууц үг үүсгэх",
            "opts": self.opts,
            "original": user,
            "intro": format_html(
                "<b>{}</b>-д шинэ түр нууц үг үүсгэнэ. Одоогийн нууц үг ажиллахаа больж,"
                " анх нэвтрэхдээ солих шаардлагатай болно.",
                user.get_username(),
            ),
        }
        return TemplateResponse(request, self.change_user_password_template, context)

    def formfield_for_manytomany(self, db_field: ManyToManyField[Any, Any], request: HttpRequest, **kwargs: Any) -> Any:
        if db_field.name == "user_permissions":
            return permission_formfield(
                widget=UserPermissionCheckboxes, label=db_field.verbose_name.capitalize(), help_text=""
            )
        if db_field.name == "groups":
            kwargs.update(widget=UnfoldAdminCheckboxSelectMultiple, help_text="")
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):  # type: ignore[misc]
    def formfield_for_manytomany(self, db_field: ManyToManyField[Any, Any], request: HttpRequest, **kwargs: Any) -> Any:
        if db_field.name == "permissions":
            return permission_formfield(label=db_field.verbose_name.capitalize())
        return super().formfield_for_manytomany(db_field, request, **kwargs)
