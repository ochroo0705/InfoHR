from typing import Any, cast
from urllib.parse import urlsplit

from accounts import modules
from accounts.audit import Category, record_export, record_safe
from accounts.models import User
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
from PIL import Image
from unfold.admin import ModelAdmin

from . import order_template_editor_views
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


def _module_field(module: modules.Module) -> forms.BooleanField:
    help_text = module.description + " Унтраахад алга болох: " + "; ".join(module.effects) + "."
    return forms.BooleanField(label=module.label, required=False, help_text=help_text)


MODULE_FIELDS = {f"module_{m.key}": _module_field(m) for m in modules.MODULES}


LETTERHEAD_MAX_BYTES = 2 * 1024 * 1024
LETTERHEAD_FORMATS = ("PNG", "JPEG")
LETTERHEAD_MAX_LINES = 8  # the letterhead must fit the top of the page (see order_docs.LETTERHEAD_MAX_SHARE)
LETTERHEAD_MAX_CHARS = 120  # per line


class CompanySettingsForm(forms.ModelForm):  # type: ignore[type-arg]
    """The limits and help of the self-form settings. They live in the form, not on the model fields, so the
    migrations do not change. The module switches are form-only checkboxes (module_<key>); the admin saves them
    through accounts.modules.set_state."""

    vars().update(MODULE_FIELDS)  # declared fields: one checkbox per module in accounts.modules.MODULES

    class Meta:
        model = CompanySettings
        fields = [
            "soon_days",
            "governed_sql_enabled",
            "report_corrections",
            "selfform_base_url",
            "selfform_notice",
            "selfform_retention_days",
            "selfform_default_hours",
            "letterhead_logo",
            "letterhead_lines",
            "letterhead_logo_place",
            "letterhead_text_align",
            "letterhead_logo_size",
            "letterhead_rule",
            "letterhead_every_page",
        ]
        help_texts = {
            "selfform_base_url": (
                "Ажилтанд илгээх холбоосын эхлэл хэсэг, жишээ нь https://hr.example.mn. "
                "Хоосон бол маягтыг үүсгэж буй хөтчийн хаягийг ашиглана."
            ),
            "selfform_retention_days": (
                "Ажилтны хувийн мэдээлэл (хариулт, зураг) баталгаажуулсан, татгалзсан, цуцалсан эсвэл "
                "хугацаа дууссанаас хойш энэ хоногийн дараа автоматаар устгана. Нэр, огноо, үр дүн хадгалагдана. "
                "1-3650 хоног."
            ),
            "selfform_default_hours": ("Холбоос үүсгэхэд анхдагчаар хүчинтэй байх цаг. 1-8760 цаг (нэг жил) хооронд."),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        current = modules.state()
        for module in modules.MODULES:
            self.fields[f"module_{module.key}"].initial = current[module.key]
        notice = self.fields["selfform_notice"]
        notice.help_text = (
            "Ажилтан маягт илгээхдээ хүлээн зөвшөөрөх мэдэгдэл. {company} гэж бичвэл байгууллагын нэр, "
            "{days} гэж бичвэл хадгалах хоног орно."
        )
        if not self.instance.selfform_notice.strip():
            notice.help_text += (
                " Одоо хоосон тул загвар текст ашиглагдана. Энэ загварын үгийг байгууллага хэрэглэхээс өмнө "
                "өөрөө уншиж, хууль зүйн хувьд баталгаажуулсан байх ёстой."
            )

    def clean_soon_days(self) -> int:
        days: int = self.cleaned_data["soon_days"]
        if not 1 <= days <= 365:
            raise forms.ValidationError("«Дөхсөн» гэж тооцох хоног 1-365 хоногийн хооронд байх ёстой.")
        return days

    def clean_selfform_default_hours(self) -> int:
        hours: int = self.cleaned_data["selfform_default_hours"]
        if not 1 <= hours <= 8760:
            raise forms.ValidationError("Холбоосын хугацаа 1-8760 цагийн хооронд байх ёстой.")
        return hours

    def clean_selfform_retention_days(self) -> int:
        days: int = self.cleaned_data["selfform_retention_days"]
        if not 1 <= days <= 3650:
            raise forms.ValidationError("Хадгалах хугацаа 1-3650 хоногийн хооронд байх ёстой.")
        return days

    def clean_selfform_base_url(self) -> str:
        url: str = self.cleaned_data["selfform_base_url"].strip()
        if not url:
            return url
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise forms.ValidationError("Хаяг http:// эсвэл https:// -ээр эхэлсэн, домэйнтэй байх ёстой.")
        if len(url) > 200:
            raise forms.ValidationError("Хаяг 200 тэмдэгтээс хэтрэхгүй байх ёстой.")
        return url

    def clean_letterhead_lines(self) -> str:
        """At most LETTERHEAD_MAX_LINES non-empty lines of at most LETTERHEAD_MAX_CHARS characters: a longer letterhead
        would not fit the top of the order's page. Blank lines do not count."""
        text: str = self.cleaned_data.get("letterhead_lines") or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) > LETTERHEAD_MAX_LINES:
            raise forms.ValidationError(f"Бланкны текст {LETTERHEAD_MAX_LINES} мөрөөс хэтрэхгүй байх ёстой.")
        if any(len(line) > LETTERHEAD_MAX_CHARS for line in lines):
            raise forms.ValidationError(f"Бланкны мөр {LETTERHEAD_MAX_CHARS} тэмдэгтээс хэтрэхгүй байх ёстой.")
        return text

    def clean_letterhead_logo(self) -> Any:
        """Only a newly uploaded file is checked; a logo already stored (or a cleared one) passes unchanged."""
        upload = self.cleaned_data.get("letterhead_logo")
        if not isinstance(upload, UploadedFile):
            return upload
        if (upload.size or 0) > LETTERHEAD_MAX_BYTES:
            raise forms.ValidationError("Лого 2 МБ-аас ихгүй байх ёстой.")
        try:
            with Image.open(upload) as image:
                fmt = image.format
                pixels = image.width * image.height  # known from the header, before the picture is decoded
                image.verify()
        except Exception:  # Pillow raises several error types for a broken or truncated picture
            raise forms.ValidationError("Лого зургийг уншиж чадсангүй. PNG эсвэл JPG файл оруулна уу.") from None
        finally:
            upload.seek(0)
        if fmt not in LETTERHEAD_FORMATS:
            raise forms.ValidationError("Лого зөвхөн PNG эсвэл JPG форматтай байх ёстой.")
        if pixels > order_docs.LETTERHEAD_MAX_PIXELS:
            raise forms.ValidationError("Лого зургийн хэмжээ 25 мегапикселээс хэтрэхгүй байх ёстой.")
        return upload


@admin.register(CompanySettings)
class CompanySettingsAdmin(ModelAdmin):  # type: ignore[misc]
    """One row only (CompanySettings.get): it can be added once and never deleted."""

    form = CompanySettingsForm
    readonly_fields = ("letterhead_mock",)

    class Media:
        css = {"all": ("css/order_template_editor.css",)}  # the .lh-* rules that draw the letterhead mock
        js = ("js/letterhead_preview.js",)  # redraws the letterhead mock while the presets change

    fieldsets = (
        (None, {"fields": ("name", "director_name")}),
        (
            "Бланк (толгой хэсэг)",
            {
                "description": (
                    "Тушаалын PDF-ийн дээд хэсгийн бланк: лого, байгууллагын мэдээлэл. Бланк нь Word загварт "
                    "орохгүй, PDF хэвлэх үед автоматаар нэмэгдэнэ."
                ),
                "fields": (
                    "letterhead_logo",
                    "letterhead_lines",
                    "letterhead_logo_place",
                    "letterhead_text_align",
                    "letterhead_logo_size",
                    "letterhead_rule",
                    "letterhead_every_page",
                    "letterhead_mock",
                ),
            },
        ),
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
        ("Гэрээ, туршилтын хугацаа", {"fields": ("soon_days",)}),
        ("Туслах: SQL хариулт", {"fields": ("governed_sql_enabled",)}),  # needs native read
        ("Тайлан", {"fields": ("report_corrections",)}),
        (
            "Модулиуд",
            {
                "description": (
                    "Байгууллагадаа хэрэггүй хэсгийг унтрааж болно. Унтраахад цэс, хайлт, туслах, хуудаснаас алга "
                    "болно. Өгөгдөл устахгүй: дахин асаахад бүгд эргэж гарна."
                ),
                "fields": tuple(MODULE_FIELDS),
            },
        ),
        (
            "Өөрөө бөглөх анкет",
            {
                "description": (
                    "Ажилтан өөрөө маягтаа бөглөх холбоосын тохиргоо. Хувийн мэдээллийг хадгалах хугацаа "
                    "энд тохируулагдана; хугацаа өнгөрөхөд хариулт, зургийг автоматаар устгана."
                ),
                "fields": (
                    "selfform_base_url",
                    "selfform_notice",
                    "selfform_retention_days",
                    "selfform_default_hours",
                ),
            },
        ),
    )

    def save_model(self, request: HttpRequest, obj: CompanySettings, form: Any, change: bool) -> None:
        super().save_model(request, obj, form, change)  # only reached with the change permission
        before = modules.state()
        after = {m.key: bool(form.cleaned_data.get(f"module_{m.key}")) for m in modules.MODULES}
        modules.set_state(after)
        for key, now in after.items():
            if before[key] != now:
                label = modules.BY_KEY[key].label
                record_safe(
                    Category.ACCESS,
                    "module_switched",
                    actor=request.user if isinstance(request.user, User) else None,
                    message=f"{label}: {'асаасан' if now else 'унтраасан'}",
                    target_type="module",
                    target_label=label,
                )

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        """There is one row, so the list is skipped: the menu opens the row, or the add form while there is none."""
        row = CompanySettings.objects.first()
        if row is None:
            return HttpResponseRedirect(reverse("admin:employees_companysettings_add"))
        return HttpResponseRedirect(reverse("admin:employees_companysettings_change", args=[row.pk]))

    def has_add_permission(self, request: HttpRequest) -> bool:
        return not CompanySettings.objects.exists() and super().has_add_permission(request)

    @admin.display(description="Урьдчилсан харагдац")
    def letterhead_mock(self, obj: CompanySettings) -> str:
        """A small picture of the presets; static/js/letterhead_preview.js draws it inside this form."""
        return mark_safe(  # noqa: S308  # a constant string with no variables in it
            "<div data-letterhead-mock></div>"
            '<p class="help">Лого зурагт харагдахгүй, оронд нь «Лого» гэж харагдана. Тохиргоо өөрчлөгдөх бүрт '
            "урьдчилсан харагдах хэсэг шинэчлэгдэнэ.</p>"
        )

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
        fields = ["file", "show_letterhead"]

    class Media:
        css = {"all": ("css/admin_order_fields.css",)}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["file"].help_text = _placeholder_help(self.instance.order_type)
        letterhead_help = "Энэ сонголт зөвхөн оруулсан Word (.docx) файлд хамаарна."
        letterhead_help += " Анхдагч (стандарт) загварт бланк үргэлж гарна."
        self.fields["show_letterhead"].help_text = letterhead_help

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        # No file after this save (starter, or «Clear» ticked): the letterhead always prints.
        if not cleaned.get("file"):
            cleaned["show_letterhead"] = True
        return cleaned

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
    list_display = ("order_type_label", "source", "needed", "letterhead", "updated_at", "downloads", "edit_link")
    fields = ("order_type_label", "file", "show_letterhead", "downloads")
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

    @admin.display(description="Бланк", boolean=True)
    def letterhead(self, obj: OrderTemplate) -> bool:
        return OrderTemplate.letterhead_on(obj.order_type)  # the same rule the PDF renderer uses

    @admin.display(description="Засах")
    def edit_link(self, obj: OrderTemplate) -> str:
        if obj.pk is None:
            return ""
        return format_html('<a href="{}">Засах</a>', reverse("admin:employees_ordertemplate_edit", args=[obj.pk]))

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
            path(
                "<int:pk>/edit/",
                self.admin_site.admin_view(self.edit_view),
                name="employees_ordertemplate_edit",
            ),
            path(
                "<int:pk>/edit/save/",
                self.admin_site.admin_view(self.save_view),
                name="employees_ordertemplate_save",
            ),
            path(
                "<int:pk>/edit/reset/",
                self.admin_site.admin_view(self.reset_view),
                name="employees_ordertemplate_reset",
            ),
            path(
                "<int:pk>/preview/",
                self.admin_site.admin_view(self.preview_view),
                name="employees_ordertemplate_preview",
            ),
            *super().get_urls(),
        ]

    def edit_view(self, request: HttpRequest, pk: int) -> HttpResponse:
        return order_template_editor_views.edit_page(self, request, pk)

    def save_view(self, request: HttpRequest, pk: int) -> HttpResponse:
        return order_template_editor_views.save_view(self, request, pk)

    def preview_view(self, request: HttpRequest, pk: int) -> HttpResponse:
        return order_template_editor_views.preview_view(self, request, pk)

    def reset_view(self, request: HttpRequest, pk: int) -> HttpResponse:
        return order_template_editor_views.reset_view(self, request, pk)

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
