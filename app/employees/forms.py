import json
from datetime import date
from decimal import Decimal
from typing import Any, Literal, cast

from accounts.models import User
from django import forms
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db.models import F, Func, Model, Q, Value
from django.db.models.functions import Upper
from django.forms.models import fields_for_model, model_to_dict
from django.urls import reverse
from lists.models import DEATH, MeaningfulEntry
from lists.quick import mark_addable
from macs.models import (
    AcademicDegree,
    BirthPlace,
    City,
    ContactType,
    Country,
    District,
    EducationLevel,
    FamilyRelation,
    FiredReason,
    ForeignLanguage,
    LanguageLevel,
    PresentType,
    ProfessionType,
    QualificationType,
    SpecEduType,
    TalentKind,
)

from employees.images import MAX_UPLOAD_BYTES, shrink_photo
from employees.models import (
    EXT_FIELDS,
    CompanySettings,
    ContractType,
    Department,
    Employee,
    EmployeeExt,
    EmployeeType,
    EventType,
    JobRecord,
    Position,
)
from employees.money import MoneyField
from employees.services.events import ALLOWED_FIELDS, REASON_CHOICES, SALARY_TYPES
from employees.services.orders import ISSUED_BY_MAX as ORDER_ISSUED_BY_MAX
from employees.services.orders import NUMBER_MAX as ORDER_NUMBER_MAX
from employees.services.orders import SUMMARY_MAX as ORDER_SUMMARY_MAX
from employees.services.personal_writes import PAY_TYPES, TR_TYPES
from employees.validators import normalize_register_no, validate_register_no

ORDER_FILE_MAGIC = (b"%PDF-", bytes([0xFF, 0xD8, 0xFF]), bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]))
INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"


DJANGO_EMPTY_LABEL = "---------"


def _blank_empty_label(field: forms.Field) -> None:
    """Show an empty entry, not Django's "---------" placeholder (docs/UI_RULES.md §2)."""
    if isinstance(field, forms.ModelChoiceField):
        if field.empty_label == DJANGO_EMPTY_LABEL:
            field.empty_label = ""
    elif isinstance(field, forms.ChoiceField):
        # Django builds these lazily (BlankChoiceIterator); a list is stored so the label is fixed.
        choices = cast("list[tuple[Any, Any]]", field.choices)
        field.choices = [(v, "" if v == "" and label == DJANGO_EMPTY_LABEL else label) for v, label in choices]


class StyledForm(forms.Form):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        mark_addable(self.fields)
        for field in self.fields.values():
            _blank_empty_label(field)
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", INPUT)
            if isinstance(field.widget, forms.Textarea) and field.widget.attrs.get("rows") == "10":
                # Django's default is 10 rows; start small and grow with the text.
                field.widget.attrs["rows"] = "2"
                field.widget.attrs.pop("cols", None)
                field.widget.attrs["class"] += " resize-none [field-sizing:content] min-h-[2.5rem]"
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(attrs={"type": "date", "class": INPUT}, format="%Y-%m-%d")


class StyledModelForm(forms.ModelForm, StyledForm):  # type: ignore[type-arg]
    pass


EMPLOYEE_FIELDS = [
    "family_name",
    "given_name",
    "clan_name",
    "register_no",
    "birth_date",
    "gender",
    "work_phone",
    "private_phone",
    "phone2",
    "email",
    "citizenship",
    "nationality",
    "passport_no",
    "marital_status",
    "first_hire_date",
    "prior_service_years",
    "prior_service_months",
    "work_conditions",
    "work_schedule",
    "probation_end",
    "job_type",
    "job_figure",
    "second_position",
    "office",
    "section",
]
OTHER_FIELDS = [
    "blood_type",
    "blood_rh",
    "social_origin",
    "military_service",
    "housing_condition",
    "living_standard",
    "car_ownership",
    "clothing_size",
    "shoe_size",
    "elected_position",
    "education_level",
    "academic_degree",
]
REQUIRED = {
    "family_name",
    "given_name",
    "register_no",
    "birth_date",
    "gender",
    "work_phone",
    "first_hire_date",
    "work_conditions",
}
# Birth place lives in its own production table (birth_place), not on the employee row.
BIRTH_FIELDS = ("birth_city", "birth_district", "birth_place_text")


class EmployeeForm(StyledForm):
    """Employee fields over the production columns and the HR extension (EmployeeExt)."""

    photo = forms.ImageField(label="Зураг", required=False)
    photo_clear = forms.BooleanField(label="Зураг устгах", required=False)

    def __init__(self, data: Any = None, files: Any = None, *, employee: Employee | None = None) -> None:
        self.employee = employee
        initial: dict[str, Any] = {}
        if employee is not None:
            initial = model_to_dict(employee, fields=[f for f in EMPLOYEE_FIELDS + OTHER_FIELDS if f not in EXT_FIELDS])
            ext = getattr(employee, "ext", None)
            if ext is not None:
                initial |= model_to_dict(ext, fields=list(EXT_FIELDS))
            # Legacy rows may hold no job form; production's own default is "Main" (үндсэн).
            initial["job_figure"] = initial.get("job_figure") or "Main"
            initial |= {
                "code": employee.code or "",
                "branch": employee.branch_id,
                "foreign_emp": employee.foreign_emp,
                "sector_years": employee.sector_years,
            }
            place = BirthPlace.objects.filter(employee=employee).order_by("id").first()
            if place is not None:
                initial |= {
                    "birth_city": place.city_id,
                    "birth_district": place.district_id,
                    "birth_place_text": place.description or "",
                }
        super().__init__(data, files, initial=initial)
        names = EMPLOYEE_FIELDS + OTHER_FIELDS
        column_fields = fields_for_model(Employee, fields=[n for n in names if n not in EXT_FIELDS])
        ext_fields = fields_for_model(EmployeeExt, fields=[n for n in names if n in EXT_FIELDS])
        built = {**column_fields, **ext_fields}
        photo, clear = self.fields.pop("photo"), self.fields.pop("photo_clear")
        for name in names:
            field = built[name]
            field.required = name in REQUIRED
            self.fields[name] = field
        self.fields["birth_city"] = forms.ModelChoiceField(
            City.objects.all(), label="Төрсөн аймаг, хот", required=False
        )
        self.fields["birth_city"].widget.attrs["data-placeholder"] = "Аймаг, хот…"
        self.fields["birth_district"] = forms.ModelChoiceField(
            District.objects.select_related("city"), label="Төрсөн сум, дүүрэг", required=False
        )
        self.fields["birth_district"].widget.attrs["data-placeholder"] = "Сум, дүүрэг…"
        self.fields["birth_place_text"] = forms.CharField(
            label="Төрсөн газар",
            max_length=50,
            required=False,
            widget=forms.TextInput(attrs={"placeholder": "Тодруулга"}),
        )
        self.fields["photo"], self.fields["photo_clear"] = photo, clear
        if employee is not None:  # the hire form sets the code itself and does not show these
            self._add_edit_fields()
        mark_addable(self.fields)
        for field in self.fields.values():
            _blank_empty_label(field)
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", INPUT)
            if isinstance(field.widget, forms.Textarea) and field.widget.attrs.get("rows") == "10":
                field.widget.attrs["rows"] = "2"
                field.widget.attrs.pop("cols", None)
                field.widget.attrs["class"] += " resize-none [field-sizing:content] min-h-[2.5rem]"
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(attrs={"type": "date", "class": INPUT}, format="%Y-%m-%d")

    def clean_register_no(self) -> str:
        value = normalize_register_no(self.cleaned_data["register_no"])
        validate_register_no(value)
        # Stored rows may hold unnormalised numbers (e.g. "уб 99112233"): compare normalised to normalised.
        stored = Employee.objects.annotate(
            register_norm=Func(Upper(F("register_no")), Value(r"\s+"), Value(""), Value("g"), function="regexp_replace")
        )
        clash = stored.filter(register_norm=value)
        if self.employee is not None:
            clash = clash.exclude(pk=self.employee.pk)
        if clash.exists():
            raise forms.ValidationError("Энэ регистрийн дугаартай ажилтан аль хэдийн бүртгэлтэй.")
        return value

    def _add_edit_fields(self) -> None:
        """QC 4b, 4c: the code, the foreign flag, the branch and the years in sector, edited on the employee page."""
        built = fields_for_model(Employee, fields=["code", "branch"])
        code = built["code"]
        code.error_messages["max_length"] = "Ажилтны код 10 тэмдэгтээс ихгүй байх ёстой."
        self.fields["code"] = code
        self.fields["branch"] = built["branch"]  # branch_ident has a FK in production: no dangling ids
        # Existing MACS values the inputs cannot express must survive an unrelated save (QC 4 review).
        employee = self.employee
        assert employee is not None
        foreign_choices = [("", "—"), ("1", "Тийм"), ("0", "Үгүй")]
        if employee.foreign_emp not in (None, 0, 1):  # an unknown old value stays selectable
            foreign_choices.append((str(employee.foreign_emp), str(employee.foreign_emp)))
        self.fields["foreign_emp"] = forms.TypedChoiceField(
            label="Гадаад иргэн", choices=foreign_choices, coerce=int, empty_value=None, required=False
        )
        self.fields["sector_years"] = forms.IntegerField(
            label="Салбарт ажилласан жил", min_value=min(0, employee.sector_years or 0), required=False
        )

    def clean_sector_years(self) -> int | None:
        # A field missing from the POST is not a change (same rule as the text fields); a blank one is refused.
        if self.employee is None or "sector_years" not in self.data:
            return self.employee.sector_years if self.employee is not None else None
        value: int | None = self.cleaned_data.get("sector_years")
        if value is None:
            raise forms.ValidationError("Салбарт ажилласан жилийг оруулна уу.")
        return value

    def clean_prior_service_years(self) -> int | None:
        # Production working_year is NOT NULL: on hire an empty or missing value means 0; on edit the sector_years
        # rule applies (missing = unchanged, blank = refused).
        value: int | None = self.cleaned_data.get("prior_service_years")
        if self.employee is None:
            return 0 if value is None else value
        if "prior_service_years" not in self.data:
            return self.employee.prior_service_years
        if value is None:
            raise forms.ValidationError("Өмнөх ажилласан жилийг оруулна уу.")
        return value

    def clean_code(self) -> str | None:
        if self.employee is not None and "code" not in self.data:
            return self.employee.code  # not posted: no change (a NULL code stays NULL)
        value = (self.cleaned_data.get("code") or "").strip()
        stored = (self.employee.code or "").strip() if self.employee is not None else ""
        # A code already on the row is kept as it is, even when another row shares it (old duplicates in MACS).
        if value == stored and self.employee is not None:
            return self.employee.code  # unchanged: keep the stored value exactly (spaces, NULL included)
        if value == stored:
            return value
        if not value:
            raise forms.ValidationError("Ажилтны кодыг хоосон орхиж болохгүй.")
        clash = Employee.objects.filter(code__iexact=value)
        if self.employee is not None:
            clash = clash.exclude(pk=self.employee.pk)
        if clash.exists():
            raise forms.ValidationError("Энэ ажилтны код аль хэдийн бүртгэлтэй байна.")
        return value

    def clean_job_figure(self) -> str:
        # Required on the old screen; the dropdown has no empty choice, so a missing value means the default.
        return self.cleaned_data.get("job_figure") or "Main"

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        city, district = data.get("birth_city"), data.get("birth_district")
        if (district or data.get("birth_place_text")) and city is None:
            self.add_error("birth_city", "Төрсөн аймаг, хотыг сонгоно уу.")
        elif city is not None and district is None:
            self.add_error("birth_district", "Сум, дүүрэг сонгоогүй байна.")  # old screen: a city needs a district
        elif city is not None and district is not None and district.city_id != city.pk:
            self.add_error("birth_district", "Энэ сум, дүүрэг сонгосон аймаг, хотод харьяалагдахгүй.")
        return data

    def birth_place(self) -> tuple[City | None, District | None, str] | None:
        """(city, district, text) when the birth place was changed, else None. A None city clears it."""
        if not any(n in self.changed_data and n in self.data for n in BIRTH_FIELDS):
            return None
        data = self.cleaned_data
        return data.get("birth_city"), data.get("birth_district"), data.get("birth_place_text") or ""

    def clean_photo(self) -> Any:
        photo = self.cleaned_data.get("photo")
        if not isinstance(photo, UploadedFile):
            return None
        if photo.size and photo.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError(f"Зургийн хэмжээ {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ-аас ихгүй байх ёстой.")
        return shrink_photo(photo)

    def photo_bytes(self) -> bytes | Literal[False] | None:
        """New JPEG bytes, None when the photo is unchanged, False when it is cleared."""
        if self.cleaned_data.get("photo_clear"):
            return False
        photo = self.cleaned_data.get("photo")
        return photo.read() if photo is not None else None

    def values(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """(production column values, ext values) for the changed fields."""
        # A text field missing from the POST is not a change (it would blank the stored value).
        changed = [
            n
            for n in self.changed_data
            if n not in ("photo", "photo_clear", *BIRTH_FIELDS)
            and (n in self.data or isinstance(self.fields[n].widget, forms.CheckboxInput))
        ]
        columns = {n: self.cleaned_data[n] for n in changed if n not in EXT_FIELDS}
        ext = {n: self.cleaned_data[n] for n in changed if n in EXT_FIELDS}
        return columns, ext


HirePersonForm = EmployeeForm


class SalaryInsuranceForm(StyledForm):
    """Salary and insurance fields. All are production columns on Employee (saved through macs_writes)."""

    def __init__(self, *args: Any, employee: Employee | None = None, **kwargs: Any) -> None:
        names = [
            "account_no",
            "bank",
            "social_insurance_no",
            "health_insurance_no",
            "insured_category",
            "taxpayer_no",
            "has_disability",
        ]
        if employee is not None:
            kwargs.setdefault("initial", model_to_dict(employee, fields=names))
        super().__init__(*args, **kwargs)
        # Labels and size limits come from the Employee columns; the form styling mirrors StyledForm.
        built = fields_for_model(Employee, fields=names)
        for name in names:
            built[name].required = False
            self.fields[name] = built[name]
        mark_addable(self.fields)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", INPUT)
        self.employee = employee


class JobCorrectionForm(StyledModelForm):
    reason = forms.CharField(label="Засварын шалтгаан", widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = JobRecord
        fields = list(JobRecord.JOB_FIELDS)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["position"].queryset = Position.objects.filter(  # type: ignore[attr-defined]
            ~Q(ext__active=False) | Q(pk=self.instance.position_id)
        )
        self.fields["department"].queryset = Department.objects.filter(  # type: ignore[attr-defined]
            ~Q(ext__active=False) | Q(pk=self.instance.department_id)
        )
        self.fields["manager"].queryset = Employee.objects.exclude(  # type: ignore[attr-defined]
            pk=self.instance.employee_id
        )


class SalaryCorrectionForm(StyledForm):
    amount = MoneyField(label="Үндсэн цалин")
    reason = forms.CharField(label="Засварын шалтгаан", widget=forms.Textarea(attrs={"rows": 2}))


class SetSalaryForm(StyledForm):
    effective = forms.DateField(label="Хэдээс")
    amount = MoneyField(label="Үндсэн цалин")


class HireJobForm(StyledModelForm):
    start = forms.DateField(label="Ажилд орох огноо")

    class Meta:
        model = JobRecord
        fields = list(JobRecord.JOB_FIELDS)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["position"].queryset = Position.objects.exclude(ext__active=False)  # type: ignore[attr-defined]
        self.fields["department"].queryset = Department.objects.exclude(ext__active=False)  # type: ignore[attr-defined]
        self.fields["status"].initial = "active"


class HireExtrasForm(StyledForm):
    base_salary = MoneyField(label="Үндсэн цалин", required=False)
    create_login = forms.BooleanField(label="Нэвтрэх эрх үүсгэх", required=False)
    username = forms.CharField(label="Нэвтрэх нэр", required=False, max_length=150)

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if data.get("create_login"):
            username = (data.get("username") or "").strip()
            if not username:
                self.add_error("username", "Нэвтрэх нэрийг бичнэ үү.")
            elif User.objects.filter(username=username).exists():
                self.add_error("username", "Ийм нэвтрэх нэр аль хэдийн байна.")
        return data


class CreateLoginForm(StyledForm):
    username = forms.CharField(
        label="Нэвтрэх нэр",
        max_length=150,
        error_messages={"required": "Нэвтрэх нэрийг бичнэ үү."},
    )


# Django has no Mongolian text for this check; the order service uses the same wording.
MAX_LENGTH_MESSAGE = "%(limit_value)d тэмдэгтээс хэтрэхгүй."


class CancelEventForm(StyledForm):
    reason = forms.CharField(label="Цуцлах шалтгаан", max_length=200, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args: Any, signed: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if signed:  # a signed order is only undone by another order, so its number is required
            self.fields["cancel_order_no"] = forms.CharField(
                label="Цуцалсан тушаалын дугаар",
                max_length=ORDER_NUMBER_MAX,
                widget=forms.TextInput(attrs={"class": INPUT}),
                error_messages={
                    "required": "Гарын үсэгтэй тушаалыг цуцлахад цуцалсан тушаалын дугаар заавал.",
                    "max_length": MAX_LENGTH_MESSAGE,
                },
            )


class OrderFieldsForm(StyledForm):
    """Number, date, text and issuer of an order. Embedded (prefix "order") in the change and hire forms, where
    all of it may stay empty (the order then waits for its number); `required=True` is the edit pop-up."""

    number = forms.CharField(label="Тушаалын дугаар", max_length=ORDER_NUMBER_MAX, required=False)
    date = forms.DateField(label="Тушаалын огноо", required=False)
    summary = forms.CharField(label="Агуулга", max_length=ORDER_SUMMARY_MAX, required=False)
    issued_by = forms.CharField(label="Гаргасан", max_length=ORDER_ISSUED_BY_MAX, required=False)

    def __init__(self, *args: Any, required: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if required:
            self.fields["number"].required = self.fields["date"].required = True
        for name in ("number", "summary", "issued_by"):
            self.fields[name].error_messages["max_length"] = MAX_LENGTH_MESSAGE
        self.fields["issued_by"].help_text = ""
        if not self.is_bound and not self.initial.get("issued_by"):
            self.initial["issued_by"] = CompanySettings.get().director_name[:ORDER_ISSUED_BY_MAX]

    def add_service_errors(self, errors: dict[str, str]) -> None:
        """Show service errors (keys `number`, `order_number`, `__all__`...) on this form's fields."""
        for key, message in errors.items():
            name = key.removeprefix("order_")
            self.add_error(name if name in self.fields else None, message)


class OrderUploadForm(StyledForm):
    """The signed scan: a PDF, JPEG or PNG checked by its first bytes (not its name) and by size."""

    file = forms.FileField(label="Гарын үсэгтэй файл (PDF, JPG, PNG)")

    def clean_file(self) -> UploadedFile:
        upload = self.cleaned_data["file"]
        limit = int(settings.ORDER_FILE_MAX_MB) * 1024 * 1024
        if upload.size is not None and upload.size > limit:
            raise forms.ValidationError(f"Файл хэт том байна (дээд хэмжээ {settings.ORDER_FILE_MAX_MB} MB).")
        head = upload.read(8)
        upload.seek(0)
        if not any(head.startswith(magic) for magic in ORDER_FILE_MAGIC):
            raise forms.ValidationError("Зөвхөн PDF, JPG эсвэл PNG файл оруулна уу.")
        return upload  # type: ignore[no-any-return]


def _job_field(name: str) -> forms.Field:
    if name == "position":
        return forms.ModelChoiceField(Position.objects.exclude(ext__active=False), label="Албан тушаал")
    if name == "department":
        return forms.ModelChoiceField(Department.objects.exclude(ext__active=False), label="Хэлтэс")
    if name == "manager":
        return forms.ModelChoiceField(Employee.objects.all(), label="Шууд удирдлага", required=False)
    if name == "employee_type":
        return forms.ChoiceField(choices=EmployeeType.choices, label="Ажилтны төрөл")
    if name == "emptype":
        return forms.TypedChoiceField(
            choices=[("", "—"), (1, "Үндсэн"), (5, "Гэрээт (хугацаатай)"), (9, "Туршилтын")],
            coerce=int,
            empty_value=None,
            required=False,
            label="Ажилтны төрлийн код",
        )
    if name == "contract_type":
        return forms.ChoiceField(choices=ContractType.choices, label="Гэрээний төрөл")
    if name == "contract_no":
        return forms.CharField(label="Гэрээний дугаар", max_length=50, required=False)
    if name == "contract_start":
        return forms.DateField(label="Гэрээ эхлэх", required=False)
    return forms.DateField(label="Гэрээ дуусах", required=False)


class EventForm(StyledForm):
    """One form per event type, built from the fields the type may change (services.events)."""

    def __init__(
        self, type: str, *args: Any, with_salary: bool = False, start_missing: tuple[str, ...] = (), **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.type = type
        # QC 3c: "died" is only recorded when the Lists meaning for death is set; warn on the form.
        self.death_unset = type == EventType.TERMINATION and MeaningfulEntry.get(DEATH) is None
        self.job_fields = ALLOWED_FIELDS[type]
        self.with_salary = with_salary and type in SALARY_TYPES
        fields: dict[str, forms.Field] = {"effective": forms.DateField(label="Хүчинтэй огноо")}
        for name in start_missing:  # QC 1d: the MACS row has no placement, so the first event must give it
            start = _job_field(name)
            start.label = "Одоогийн хэлтэс" if name == "department" else "Одоогийн албан тушаал"
            fields[f"start_{name}"] = start
        for name in self.job_fields:
            fields[name] = _job_field(name)
        if self.with_salary:
            fields["salary"] = MoneyField(label="Үндсэн цалин", required=type == EventType.SALARY_CHANGE)
        choices = REASON_CHOICES.get(type)
        if type == EventType.TERMINATION:
            fields["fired_reason"] = forms.ModelChoiceField(
                FiredReason.objects.all(),
                label="Ажлаас гарсан шалтгаан",
                error_messages={"required": "Жагсаалтаас шалтгаан сонгоно уу."},
            )
        elif choices is not None:
            fields["reason"] = forms.ChoiceField(choices=[("", "—"), *choices.choices], label="Шалтгаан")
        else:
            fields["reason"] = forms.CharField(
                label="Шалтгаан", max_length=100, required=type == EventType.DEMOTION, widget=forms.TextInput()
            )
        if type == EventType.LEAVE_START:
            fields["expected_return"] = forms.DateField(label="Буцах төлөвлөсөн огноо", required=False)
        if type in (EventType.TERMINATION, EventType.CONTRACT):
            fields["pension"] = forms.BooleanField(label="Тэтгэвэрт гарсан", required=False)
        fields["note"] = forms.CharField(label="Тайлбар", required=False, widget=forms.Textarea(attrs={"rows": 2}))
        for name, field in fields.items():
            field.widget.attrs.setdefault("class", INPUT)
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(attrs={"type": "date", "class": INPUT}, format="%Y-%m-%d")
            self.fields[name] = field
        if "fired_reason" in self.fields:
            mark_addable({"fired_reason": self.fields["fired_reason"]})  # typing, addable dropdown (UI_RULES §2a)


# --- Personal tab: one form per row of the six personal lists (production tables, spec §4-§5) ---

PERSONAL_DATE_FIELDS = frozenset(
    {"birth_date", "startdate", "pdate", "start_date", "ending_date", "certify_date", "end_date"}
)  # snapshot dates
PERSONAL_DECIMAL_FIELDS = frozenset({"credit_score", "amount"})  # snapshot values that are decimals
SMALLINT_MAX = 32767
INT_MAX = 2147483647


def _pk(value: Any) -> Any:
    return value.pk if isinstance(value, Model) else value


class PersonalRowForm(StyledForm):
    """Base for the six per-row forms of the personal tab.

    COLUMNS: (form field, model attname) for production columns. EXT: HR-only fields (education, gift).
    LOADED: every key of personal_writes.snapshot() for the row. The values the row had when the form was
    opened travel back as hidden loaded_<key> fields (JSON, so NULL and '' stay different) and the write
    layer refuses the save when they no longer match (stale check, spec §5).
    LISTS: (form field, Lists slug) for code lists the form needs; an empty one gets a notice in the modal.
    """

    COLUMNS: tuple[tuple[str, str], ...] = ()
    EXT: tuple[str, ...] = ()
    LOADED: tuple[str, ...] = ()
    LISTS: tuple[tuple[str, str], ...] = ()

    def __init__(self, *args: Any, adding: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.adding = adding
        for name in self.LOADED:
            self.fields[f"loaded_{name}"] = forms.CharField(required=False, widget=forms.HiddenInput)

    @classmethod
    def from_snapshot(cls, snap: dict[str, Any], ext: dict[str, Any]) -> dict[str, Any]:
        """Initial values for the edit form: the visible fields plus the loaded values for the stale check."""
        initial: dict[str, Any] = {field: snap[attname] for field, attname in cls.COLUMNS}
        initial |= {name: ext.get(name) for name in cls.EXT}
        initial |= {f"loaded_{name}": json.dumps(snap[name], default=str) for name in cls.LOADED}
        return initial

    def snapshot(self) -> dict[str, Any]:
        """The loaded values posted back with the form; {} when one is missing or unreadable (counts as stale)."""
        out: dict[str, Any] = {}
        for name in self.LOADED:
            raw = self.data.get(f"loaded_{name}")
            if raw is None:
                return {}
            try:
                value = json.loads(raw)
                if name in PERSONAL_DATE_FIELDS and value is not None:
                    value = date.fromisoformat(value)
                elif name in PERSONAL_DECIMAL_FIELDS and value is not None:
                    value = Decimal(value)
            except (ValueError, TypeError):
                return {}
            out[name] = value
        return out

    def values(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """(production column values by attname, HR-only values) for the save."""
        cleaned = self.cleaned_data
        columns = {attname: _pk(cleaned[field]) for field, attname in self.COLUMNS}
        return columns, {name: cleaned[name] for name in self.EXT}

    def empty_lists(self) -> list[tuple[str, str]]:
        """(Lists slug, label) of each code list this form needs that has no entries yet."""
        return [
            (slug, str(self.fields[field].label))
            for field, slug in self.LISTS
            if not self.fields[field].queryset.exists()  # type: ignore[attr-defined]
        ]


class FamilyRowForm(PersonalRowForm):
    COLUMNS = (
        ("relation", "relation_id"),
        ("given_name", "given_name"),
        ("surname", "surname"),
        ("birth_date", "birth_date"),
        ("job", "job"),
        ("phone", "phone"),
    )
    LOADED = ("employee_id", "relation_id", "given_name", "surname", "birth_date", "job", "phone")
    LISTS = (("relation", "family_relation"),)

    relation = forms.ModelChoiceField(FamilyRelation.objects.all(), label="Хамаарал")
    given_name = forms.CharField(label="Нэр", max_length=40)
    surname = forms.CharField(label="Овог", max_length=30, required=False, empty_value=None)
    birth_date = forms.DateField(label="Төрсөн огноо", required=False)
    job = forms.CharField(label="Ажил, албан тушаал", max_length=100, required=False, empty_value=None)
    phone = forms.CharField(label="Утас", max_length=14, required=False, empty_value=None)


def _known_country_pk(text: Any) -> int | None:
    """The Country id a stored country text names, or None when it is free text or an id that does not exist."""
    if isinstance(text, str) and text.strip().isdigit() and Country.objects.filter(pk=int(text.strip())).exists():
        return int(text.strip())
    return None


class EducationRowForm(PersonalRowForm):
    """Writes qualification (production). The country is a Country id, stored as its text.

    Legacy free text in country (for example "Монгол") cannot be picked from the list, so the form shows it
    blank and keeps the text in raw_country: it is written back unchanged unless the user picks a country.
    The stale check (LOADED) covers the whole row, so every production column stays as it was.
    """

    COLUMNS = (
        ("org_name", "org_name"),
        ("country", "country"),
        ("start_year", "start_year"),
        ("end_year", "end_year"),
        ("edu_level", "edu_level_id"),
        ("profession_type", "profession_type_id"),
        ("qualification_type", "qualification_type_id"),
        ("grade", "grade_id"),
        ("credit_score", "credit_score"),
        ("diplom_number", "diplom_number"),
    )
    LOADED = (
        "employee_id",
        "qualification_type_id",
        "profession_type_id",
        "org_name",
        "diplom_number",
        "start_date",
        "ending_date",
        "credit_score",
        "country",
        "edu_level_id",
        "grade_id",
        "start_year",
        "end_year",
    )
    LISTS = (
        ("country", "country"),
        ("edu_level", "education"),
        ("profession_type", "profession_type"),
        ("qualification_type", "qualification_type"),
        ("grade", "degree"),
    )

    org_name = forms.CharField(label="Сургуулийн нэр", max_length=60)
    country = forms.ModelChoiceField(Country.objects.all(), label="Улс", required=False)
    start_year = forms.IntegerField(label="Элссэн он", min_value=0, max_value=SMALLINT_MAX)
    end_year = forms.IntegerField(label="Төгссөн он", min_value=0, max_value=SMALLINT_MAX)
    edu_level = forms.ModelChoiceField(EducationLevel.objects.all(), label="Боловсрол", required=False)
    profession_type = forms.ModelChoiceField(ProfessionType.objects.all(), label="Мэргэжил", required=False)
    qualification_type = forms.ModelChoiceField(QualificationType.objects.all(), label="Мэргэшил", required=False)
    grade = forms.ModelChoiceField(AcademicDegree.objects.all(), label="Эрдмийн зэрэг", required=False)
    credit_score = forms.DecimalField(
        label="Голч оноо",
        required=False,
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("999.99"),  # wide enough for old rows on another scale; they stay editable
    )
    diplom_number = forms.CharField(label="Диплом/Гэрчилгээ №", max_length=10, required=False, empty_value=None)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The stored country text travels in the loaded_country hidden field (JSON), bound or unbound.
        raw = self.data.get("loaded_country") if self.is_bound else self.initial.get("loaded_country")
        self.raw_country: str | None = self._free_text_country(raw)

    @staticmethod
    def _free_text_country(raw: Any) -> str | None:
        try:
            text = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            return None
        if not isinstance(text, str) or text == "" or _known_country_pk(text) is not None:
            return None
        return text

    @classmethod
    def from_snapshot(cls, snap: dict[str, Any], ext: dict[str, Any]) -> dict[str, Any]:
        initial = super().from_snapshot(snap, ext)
        initial["country"] = _known_country_pk(snap["country"])  # free text stays blank; see raw_country
        return initial

    def values(self) -> tuple[dict[str, Any], dict[str, Any]]:
        columns, ext = super().values()
        picked = self.cleaned_data.get("country")
        columns["country"] = str(picked.pk) if picked is not None else self.raw_country
        return columns, ext

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        start, end = data.get("start_year"), data.get("end_year")
        if start is not None and end is not None and end < start:
            self.add_error("end_year", "Төгссөн он элссэн оноос өмнө байж болохгүй.")
        return data


class CertificateRowForm(PersonalRowForm):
    COLUMNS = (
        ("cert_type", "cert_type_id"),
        ("org_edu", "org_edu"),
        ("profession", "profession"),
        ("spec_profession", "spec_profession"),
        ("certify_number", "certify_number"),
        ("certify_date", "certify_date"),
        ("end_date", "end_date"),
        ("certify_year", "certify_year"),
    )
    LOADED = (
        "employee_id",
        "cert_type_id",
        "org_edu",
        "certify_number",
        "certify_date",
        "profession",
        "end_date",
        "spec_profession",
        "certify_year",
    )
    LISTS = (("cert_type", "spec_edu_type"),)

    cert_type = forms.ModelChoiceField(SpecEduType.objects.all(), label="Тусгай мэргэжлийн төрөл")
    org_edu = forms.CharField(label="Боловсрол олгосон байгууллага", max_length=30)
    profession = forms.CharField(label="Мэргэжил", max_length=20, required=False, empty_value=None)
    spec_profession = forms.CharField(label="Тусгай мэргэжил", max_length=20, required=False, empty_value=None)
    certify_number = forms.CharField(label="Сертификатын дугаар", max_length=20, required=False, empty_value=None)
    certify_date = forms.DateField(label="Сертификат олгосон огноо", required=False)
    end_date = forms.DateField(label="Дууссан огноо", required=False)
    certify_year = forms.IntegerField(label="Төгссөн он", min_value=0, max_value=SMALLINT_MAX)


class TrainingRowForm(PersonalRowForm):
    COLUMNS = (
        ("tr_type", "tr_type"),
        ("description", "description"),
        ("start_date", "start_date"),
        ("start_year", "start_year"),
        ("days", "days"),
        ("amount", "amount"),
        ("pay_type", "pay_type"),
        ("training_center", "training_center"),
    )
    LOADED = (
        "employee_id",
        "tr_type",
        "description",
        "start_date",
        "days",
        "amount",
        "pay_type",
        "training_center",
        "start_year",
    )

    start_year = forms.IntegerField(label="Сургалтын он", min_value=0, max_value=SMALLINT_MAX)
    start_date = forms.DateField(label="Эхэлсэн огноо", required=False)
    training_center = forms.CharField(label="Сургалтын төвийн нэр", max_length=100, required=False, empty_value=None)
    description = forms.CharField(label="Сургалтын төрөл", max_length=50)
    tr_type = forms.TypedChoiceField(label="Хэлбэр", choices=list(TR_TYPES.items()), coerce=int, initial=1)
    days = forms.IntegerField(label="Хоног", min_value=0, max_value=SMALLINT_MAX, required=False)
    amount = MoneyField(label="Төлбөр (₮)", initial=0)
    pay_type = forms.TypedChoiceField(label="Төлсөн хэлбэр", choices=list(PAY_TYPES.items()), coerce=int)

    def values(self) -> tuple[dict[str, Any], dict[str, Any]]:
        columns, ext = super().values()
        columns["amount"] = Decimal(columns["amount"])
        return columns, ext


LEVEL_FIELDS = ("understand_lvl", "speaking_lvl", "reading_lvl", "writing_lvl")


class LanguageRowForm(PersonalRowForm):
    """Level columns hold the level name text. A stored level that is not in the list stays selectable."""

    COLUMNS = (
        ("language", "language_id"),
        ("understand_lvl", "understand_lvl"),
        ("speaking_lvl", "speaking_lvl"),
        ("reading_lvl", "reading_lvl"),
        ("writing_lvl", "writing_lvl"),
        ("description", "description"),
    )
    LOADED = (
        "employee_id",
        "language_id",
        "understand_lvl",
        "speaking_lvl",
        "reading_lvl",
        "writing_lvl",
        "description",
    )
    LISTS = (("language", "language"),)

    language = forms.ModelChoiceField(ForeignLanguage.objects.all(), label="Гадаад хэл")
    understand_lvl = forms.ChoiceField(label="Сонсож ойлгох", required=False)
    speaking_lvl = forms.ChoiceField(label="Ярих", required=False)
    reading_lvl = forms.ChoiceField(label="Унших", required=False)
    writing_lvl = forms.ChoiceField(label="Бичих", required=False)
    description = forms.CharField(label="Тайлбар", max_length=50, required=False, empty_value=None)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        names = [name for name in LanguageLevel.objects.values_list("name", flat=True) if name]
        for field in LEVEL_FIELDS:
            choices: list[tuple[str, str]] = [("", "—")] + [(name, name) for name in names]
            stored = self._stored_level(field)
            if stored is not None and stored not in names:
                choices.append((stored, stored))
            level = cast(forms.ChoiceField, self.fields[field])
            level.choices = choices

    def _stored_level(self, field: str) -> str | None:
        """The level the row had when the form was opened (from the loaded_ hidden field)."""
        raw = self.data.get(f"loaded_{field}") if self.is_bound else self.initial.get(f"loaded_{field}")
        try:
            value = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            return None
        return value if isinstance(value, str) and value else None

    def values(self) -> tuple[dict[str, Any], dict[str, Any]]:
        columns, ext = super().values()
        for field in LEVEL_FIELDS:
            columns[field] = columns[field] or None
        return columns, ext

    def empty_lists(self) -> list[tuple[str, str]]:
        out = super().empty_lists()
        if not LanguageLevel.objects.exists():
            out.append(("language_level", "Хэлний түвшин"))
        return out


class TalentRowForm(PersonalRowForm):
    """Keyed by talent_ident: production has no key for emp_talents (one row per employee and talent)."""

    COLUMNS = (("talent", "talent_ident"), ("trained_year", "trained_year"), ("description", "description"))
    LOADED = ("talent_ident", "trained_year", "description")
    LISTS = (("talent", "talent"),)

    talent = forms.ModelChoiceField(TalentKind.objects.all(), label="Авьяас")
    trained_year = forms.IntegerField(label="Сургасан он", min_value=0, max_value=SMALLINT_MAX, required=False)
    description = forms.CharField(label="Тайлбар", max_length=200, required=False, empty_value=None)


class GiftRowForm(PersonalRowForm):
    COLUMNS = (
        ("present_type", "present_type_id"),
        ("pdate", "pdate"),
        ("given_year", "given_year"),
        ("childqty", "childqty"),
        ("child_age", "child_age"),
        ("price", "price"),
        ("given", "given"),
    )
    EXT = ("note",)
    LOADED = ("employee_id", "childqty", "price", "given_year", "pdate", "present_type_id", "child_age", "given")
    LISTS = (("present_type", "present_type"),)

    present_type = forms.ModelChoiceField(PresentType.objects.all(), label="Бэлгийн төрөл")
    pdate = forms.DateField(label="Огноо")
    given_year = forms.IntegerField(label="Бэлэглэсэн он", min_value=0, max_value=INT_MAX)
    childqty = forms.IntegerField(label="Хүүхдийн тоо", min_value=0, max_value=INT_MAX)
    child_age = forms.IntegerField(label="Хүүхдийн нас", min_value=0, max_value=SMALLINT_MAX)
    price = MoneyField(label="Үнэ (₮)", max_digits=14, decimal_places=0)
    given = forms.BooleanField(label="Өгсөн эсэх", required=False)
    note = forms.CharField(label="Тайлбар", max_length=200, required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.adding:
            self.fields["childqty"].initial = 1
            self.fields["given"].initial = True
            # The year defaults to the year of the date, on add only; never changed automatically on edit.
            if self.is_bound and not self.data.get("given_year"):
                try:
                    pdate = forms.DateField().clean(self.data.get("pdate"))
                except forms.ValidationError:
                    pdate = None
                if pdate is not None:
                    # QueryDict -> plain dict of last values (a QueryDict is read-only here).
                    self.data = {key: self.data[key] for key in self.data} | {"given_year": str(pdate.year)}

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        price = data.get("price")
        if price is not None and price != price.to_integral_value():
            self.add_error("price", "Бүхэл төгрөгөөр оруулна уу.")
        return data

    def values(self) -> tuple[dict[str, Any], dict[str, Any]]:
        columns, ext = super().values()
        columns["price"] = int(columns["price"])
        columns["given"] = 1 if columns["given"] else 0
        return columns, ext


class AddressRowForm(PersonalRowForm):
    COLUMNS = (("city", "city_id"), ("district", "district_id"), ("street", "street"))
    LOADED = ("employee_id", "street", "city_id", "district_id")
    LISTS = (("city", "city"),)

    city = forms.ModelChoiceField(City.objects.all(), label="Аймаг, хот")
    # Only the districts of the chosen city are offered (spec §4); the choices follow the city in the modal.
    district = forms.ModelChoiceField(
        District.objects.none(),
        label="Сум, дүүрэг",
        error_messages={"invalid_choice": "Энэ сум, дүүрэг сонгосон аймаг, хотод харьяалагдахгүй."},
    )
    street = forms.CharField(label="Хаяг", max_length=50, required=False, empty_value=None)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        raw = self.data.get(self.add_prefix("city")) if self.is_bound else self.initial.get("city")
        city_pk = getattr(raw, "pk", raw)
        if str(city_pk or "").isdigit():
            self.fields["district"].queryset = District.objects.filter(city_id=int(str(city_pk)))  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        city, district = data.get("city"), data.get("district")
        if city is not None and district is not None and district.city_id != city.pk:
            self.add_error("district", "Энэ сум, дүүрэг сонгосон аймаг, хотод харьяалагдахгүй.")
        return data


def _blank(value: Any) -> bool:
    return value is None or value == ""


class HireAddressForm(AddressRowForm):
    """The optional first address on the hire page: all fields may stay empty. Once one is filled,
    city and district are required (the production row needs both)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["city"].required = False
        self.fields["district"].required = False
        # Changing the city re-fetches only the district select (employees:district_options), so it follows the city.
        self.fields["city"].widget.attrs.update(
            {
                "hx-get": reverse("employees:district_options"),
                "hx-trigger": "change",
                "hx-target": "#addr-district-wrap",
                "hx-swap": "outerHTML",
                "hx-include": "this",
            }
        )

    def filled(self) -> bool:
        return any(not _blank(self.cleaned_data.get(name)) for name in ("city", "district", "street"))

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if self.filled():
            if data.get("city") is None and "city" not in self.errors:
                self.add_error("city", "Аймаг, хотыг сонгоно уу.")
            if data.get("district") is None and "district" not in self.errors:
                self.add_error("district", "Сум, дүүрэг сонгоогүй байна.")
        return data


class ContactRowForm(PersonalRowForm):
    COLUMNS = (
        ("contact_type", "contact_type_id"),
        ("name", "name"),
        ("relative", "relative"),
        ("value", "value"),
    )
    LOADED = ("employee_id", "contact_type_id", "name", "relative", "value")
    LISTS = (("contact_type", "contact_type"),)

    contact_type = forms.ModelChoiceField(ContactType.objects.all(), label="Холбоо барих төрөл")
    name = forms.CharField(label="Нэр", max_length=100)
    relative = forms.CharField(label="Хамаарал", max_length=10)
    value = forms.CharField(label="Утас, имэйл", max_length=30, required=False, empty_value=None)


class HireContactForm(ContactRowForm):
    """The optional emergency contact on the hire page: all fields may stay empty. Once one is filled,
    type, name and relation are required."""

    REQUIRED_WHEN_FILLED = ("contact_type", "name", "relative")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for name in self.REQUIRED_WHEN_FILLED:
            self.fields[name].required = False

    def filled(self) -> bool:
        return any(not _blank(self.cleaned_data.get(name)) for name in (*self.REQUIRED_WHEN_FILLED, "value"))

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if self.filled():
            for name in self.REQUIRED_WHEN_FILLED:
                if _blank(data.get(name)) and name not in self.errors:
                    self.add_error(name, "Заавал бөглөнө үү.")
        return data


FORMS: dict[str, type[PersonalRowForm]] = {
    "family": FamilyRowForm,
    "education": EducationRowForm,
    "certificate": CertificateRowForm,
    "training": TrainingRowForm,
    "language": LanguageRowForm,
    "talent": TalentRowForm,
    "gift": GiftRowForm,
    "address": AddressRowForm,
    "contact": ContactRowForm,
}
