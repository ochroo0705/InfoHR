from typing import Any, cast

from accounts.audit import record_export
from django import forms
from django.contrib import admin, messages
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Model
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe
from lists.usage import usage_count
from unfold.admin import ModelAdmin

from .models import (
    ActivityEntry,
    CompanySettings,
    Department,
    DepartmentExt,
    Employee,
    JobRecord,
    OrderTemplate,
    OrderType,
    Position,
    PositionExt,
    SalaryRecord,
)
from .services import macs_writes, order_docs


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
    exclude = ("loginpass",)  # the old program's login password: never shown (employee-field-map.md)

    def get_queryset(self, request: HttpRequest) -> Any:
        return super().get_queryset(request).defer("loginpass")  # not even read


@admin.register(JobRecord, SalaryRecord)
class HistoryAdmin(ReadOnlyAdmin):
    list_display = ("employee", "period", "change_type", "created_at")


@admin.register(ActivityEntry)
class ActivityAdmin(ReadOnlyAdmin):
    list_display = ("employee", "at", "kind", "message", "personal", "sensitive")


@admin.register(CompanySettings)
class CompanySettingsAdmin(ModelAdmin):  # type: ignore[misc]
    """One row only (CompanySettings.get): it can be added once and never deleted."""

    fieldsets = (
        (None, {"fields": ("name", "director_name")}),
        (
            "Тушаал шаардах өөрчлөлтүүд",
            {
                "description": (
                    "Сонгоогүй төрлийн өөрчлөлтийг тушаалгүйгээр хадгалж, хүчинтэй өдрөөс нь мөрдөнө "
                    "(тушаалыг цаасаар хөтөлнө). Өмнө гарсан тушаал, гарын үсэг хүлээж буй өөрчлөлт хэвээр үлдэнэ."
                ),
                "fields": tuple(CompanySettings.ORDER_FLAGS.values()),
            },
        ),
        ("Орон тоо", {"fields": ("enforce_position_slots",)}),
    )

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        """There is one row, so the list is skipped: the menu opens the row, or the add form while there is none."""
        row = CompanySettings.objects.first()
        if row is None:
            return HttpResponseRedirect(reverse("admin:employees_companysettings_add"))
        return HttpResponseRedirect(reverse("admin:employees_companysettings_change", args=[row.pk]))

    def has_add_permission(self, request: HttpRequest) -> bool:
        return not CompanySettings.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


MAX_TEMPLATE_BYTES = 5 * 1024 * 1024


def _placeholder_help(order_type: int) -> SafeString:
    """The field's help: one short line, and a small button that opens a pop-up with what each placeholder of this
    order type means."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for group, name, meaning in order_docs.placeholder_help_for(order_type):
        groups.setdefault(group, []).append((name, meaning))
    return mark_safe(render_to_string("employees/_order_fields_help.html", {"groups": groups}))  # noqa: S308


class OrderTemplateForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = OrderTemplate
        fields = ["file"]

    class Media:
        css = {"all": ("css/admin_order_fields.css",)}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["file"].help_text = _placeholder_help(self.instance.order_type)

    def clean_file(self) -> Any:
        value = self.cleaned_data.get("file")
        if not isinstance(value, UploadedFile):  # unchanged, or «Clear» ticked: back to the starter
            return value
        if not (value.name or "").lower().endswith(".docx"):
            raise forms.ValidationError("Зөвхөн Word (.docx) файл оруулна уу.")
        if (value.size or 0) > MAX_TEMPLATE_BYTES:
            raise forms.ValidationError("Файл 5 MB-аас хэтрэхгүй байх ёстой.")
        problems = order_docs.check_template(value.read())
        value.seek(0)
        if problems:
            raise forms.ValidationError(problems)
        return value


@admin.register(OrderTemplate)
class OrderTemplateAdmin(ModelAdmin):  # type: ignore[misc]
    """The install's own Word template of each order type (D-053). The six rows exist from the first visit; no file
    means the bundled starter template. «Clear» ticked on a row puts the starter back."""

    form = OrderTemplateForm
    list_display = ("order_type_label", "source", "needed", "updated_at", "downloads")
    fields = ("order_type_label", "file", "downloads")
    readonly_fields = ("order_type_label", "downloads")

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        OrderTemplate.ensure_all()
        return cast(HttpResponse, super().changelist_view(request, extra_context))

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: OrderTemplate, form: Any, change: bool) -> None:
        obj.updated_by = request.user  # type: ignore[assignment]
        super().save_model(request, obj, form, change)

    @admin.display(description="Төрөл")
    def order_type_label(self, obj: OrderTemplate) -> str:
        return str(obj)

    @admin.display(description="Загвар")
    def source(self, obj: OrderTemplate) -> str:
        return "Өөрийн файл" if obj.file else "Анхдагч (стандарт)"

    @admin.display(description="Тушаал шаардах эсэх", boolean=True)
    def needed(self, obj: OrderTemplate) -> bool:
        return CompanySettings.get().requires_order(obj.order_type)

    @admin.display(description="Татах")
    def downloads(self, obj: OrderTemplate) -> Any:
        if obj.pk is None:
            return ""
        base = reverse("admin:employees_ordertemplate_download", args=[obj.pk])
        return format_html(
            '<a href="{}?which=current">Одоогийнхыг татах</a> · <a href="{}?which=starter">Анхдагчийг татах</a>',
            base,
            base,
        )

    def get_urls(self) -> list[Any]:
        return [
            path(
                "<int:pk>/download/",
                self.admin_site.admin_view(self.download),
                name="employees_ordertemplate_download",
            ),
            *super().get_urls(),
        ]

    def download(self, request: HttpRequest, pk: int) -> FileResponse:
        if not self.has_view_permission(request):
            raise Http404
        row = OrderTemplate.objects.filter(pk=pk).first()
        if row is None:
            raise Http404
        if row.file and request.GET.get("which") != "starter":
            handle = row.file.open("rb")
        else:
            handle = order_docs.starter_path(row.order_type).open("rb")
        name = order_docs.TEMPLATE_FILES[OrderType(row.order_type)]
        record_export(request, "order_template_download", f"Тушаалын загвар: {OrderType(row.order_type).label}")
        return FileResponse(handle, as_attachment=True, filename=name, content_type=order_docs.DOCX_TYPE)
