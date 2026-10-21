import os
from datetime import date
from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import models
from macs.models import Department as Department
from macs.models import EducRow as EducRow
from macs.models import Employee as Employee
from macs.models import Position as Position
from macs.models import PresentRow as PresentRow

from employees.validators import normalize_register_no as normalize_register_no
from employees.validators import validate_register_no as validate_register_no


class BloodRh(models.TextChoices):
    POS = "+", "Rh+"
    NEG = "-", "Rh−"


class EmployeeExt(models.Model):
    """HR-only data for a production employee (spec §3). One row per employee_id."""

    employee = models.OneToOneField(
        Employee, primary_key=True, on_delete=models.PROTECT, related_name="ext", db_constraint=True
    )
    prior_service_months = models.PositiveSmallIntegerField("Өмнөх ажилласан сар", default=0)
    probation_end = models.DateField("Туршилтын хугацаа дуусах", null=True, blank=True)
    blood_rh = models.CharField("Rh хүчин зүйл", max_length=1, choices=BloodRh.choices, blank=True)
    living_standard = models.CharField("Амьжиргааны түвшин", max_length=100, blank=True)
    setup_required = models.BooleanField(default=False)
    is_pensioner = models.BooleanField("Тэтгэврийн настай", default=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Нэвтрэх эрх",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employee_ext",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "employees_employeeext"

    def __str__(self) -> str:
        return f"HR мэдээлэл: {self.employee}"


def ensure_ext(employee: Employee) -> EmployeeExt:
    ext, _ = EmployeeExt.objects.get_or_create(employee=employee)
    return ext


def ext_of(employee: Employee) -> EmployeeExt | None:
    """The HR row of a production employee, or None when HR has never touched them."""
    return getattr(employee, "ext", None)  # the reverse one-to-one raises AttributeError when missing


class DepartmentExt(models.Model):
    department = models.OneToOneField(Department, primary_key=True, on_delete=models.PROTECT, related_name="ext")
    active = models.BooleanField("Идэвхтэй", default=True)

    class Meta:
        db_table = "employees_departmentext"

    def __str__(self) -> str:
        return f"HR мэдээлэл: {self.department}"


class PositionExt(models.Model):
    position = models.OneToOneField(Position, primary_key=True, on_delete=models.PROTECT, related_name="ext")
    active = models.BooleanField("Идэвхтэй", default=True)

    class Meta:
        db_table = "employees_positionext"

    def __str__(self) -> str:
        return f"HR мэдээлэл: {self.position}"


class EducationExt(models.Model):
    """HR-only details of a production education row (educ). Keyed by educ_id; no DB constraint (D-017)."""

    educ = models.OneToOneField(
        EducRow,
        primary_key=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="ext",
    )
    school = models.CharField("Сургууль", max_length=200, blank=True)
    field = models.CharField("Мэргэжил", max_length=150, blank=True)
    graduation_year = models.PositiveSmallIntegerField("Төгссөн он", null=True, blank=True)

    class Meta:
        db_table = "employees_educationext"

    def __str__(self) -> str:
        return f"HR мэдээлэл: боловсрол {self.educ_id}"


class GiftExt(models.Model):
    """HR-only details of a production gift row (given_present). Keyed by present_id; no DB constraint (D-017)."""

    present = models.OneToOneField(
        PresentRow,
        primary_key=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="ext",
    )
    note = models.CharField("Тайлбар", max_length=200, blank=True)

    class Meta:
        db_table = "employees_giftext"

    def __str__(self) -> str:
        return f"HR мэдээлэл: бэлэг {self.present_id}"


class EmployeeType(models.TextChoices):
    FULL_TIME = "full_time", "Үндсэн, бүтэн цаг"
    PART_TIME = "part_time", "Хагас цаг"
    CONTRACT = "contract", "Гэрээт"


class ContractType(models.TextChoices):
    OPEN_ENDED = "open_ended", "Хугацаагүй"
    FIXED_TERM = "fixed_term", "Хугацаатай"


class JobStatus(models.TextChoices):
    ACTIVE = "active", "Ажиллаж байгаа"
    LONG_LEAVE = "long_leave", "Урт хугацааны чөлөөтэй"
    LEFT = "left", "Ажлаас гарсан"


class ChangeType(models.TextChoices):
    HIRE = "hire", "Ажилд авсан"
    OPENING = "opening", "Эхлэл (MACS-аас)"
    CORRECTION = "correction", "Засвар"
    TRANSFER = "transfer", "Шилжүүлсэн"
    PROMOTION = "promotion", "Дэвшүүлсэн"
    DEMOTION = "demotion", "Бууруулсан"
    SALARY_CHANGE = "salary_change", "Цалин өөрчилсөн"
    CONTRACT = "contract", "Гэрээ сунгасан/өөрчилсөн"
    LEAVE_START = "leave_start", "Урт чөлөө эхэлсэн"
    LEAVE_RETURN = "leave_return", "Чөлөөнөөс буцсан"
    TERMINATION = "termination", "Ажлаас чөлөөлсөн"
    REHIRE = "rehire", "Дахин ажилд авсан"


class EventType(models.TextChoices):
    TRANSFER = "transfer", "Шилжүүлэх"
    PROMOTION = "promotion", "Дэвшүүлэх"
    DEMOTION = "demotion", "Бууруулах"
    SALARY_CHANGE = "salary_change", "Цалин өөрчлөх"
    CONTRACT = "contract", "Гэрээ сунгах / өөрчлөх"
    LEAVE_START = "leave_start", "Урт чөлөө эхлэх"
    LEAVE_RETURN = "leave_return", "Буцаж ирэх"
    TERMINATION = "termination", "Ажлаас чөлөөлөх"
    REHIRE = "rehire", "Дахин ажилд авах"

    @property
    def change_type(self) -> str:
        """The ChangeType with the same value."""
        return str(ChangeType(self.value).value)


class LeaveKind(models.TextChoices):
    MATERNITY = "maternity", "Жирэмсний амралт"
    CHILDCARE = "childcare", "Хүүхэд асрах чөлөө"
    UNPAID = "unpaid", "Цалингүй чөлөө"


class Event(models.Model):
    """An HR event (transfer, promotion, ...). Never deleted; cancelling removes its history rows."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="events")
    type = models.CharField("Төрөл", max_length=20, choices=EventType.choices)
    effective = models.DateField("Хүчинтэй огноо")
    reason = models.CharField("Шалтгаан", max_length=100, blank=True)
    note = models.TextField("Тайлбар", blank=True)
    # Termination only: the production leaving-reason list (macs.FiredReason); `reason` keeps the long-leave kind.
    fired_reason = models.ForeignKey(
        "macs.FiredReason",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="Ажлаас гарсан шалтгаан",
    )
    # Long leave only: planned, for reminders; the actual return is its own event (scoping D-012).
    expected_return = models.DateField("Буцах төлөвлөсөн огноо", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cancel_reason = models.CharField("Цуцлах шалтгаан", max_length=200, blank=True)
    pension = models.BooleanField("Тэтгэвэрт гарсан", default=False)

    class Meta:
        verbose_name = "Өөрчлөлт"
        verbose_name_plural = "Өөрчлөлтүүд"
        ordering = ["-effective", "-id"]

    def __str__(self) -> str:
        return f"{self.employee.code} {self.get_type_display()} {self.effective}"

    def status(self, today: date) -> str:
        if self.cancelled_at is not None:
            return "cancelled"
        return "scheduled" if self.effective > today else "effective"


class OrderType(models.IntegerChoices):
    HIRED = 1, "Ажилд орсон"
    DEPARTMENT = 2, "Хэлтэс, салбар шилжсэн"
    POSITION = 3, "Албан тушаал сольсон"
    FIRED = 4, "Ажлаас гарсан"
    PENSION = 5, "Тэтгэвэрт гарсан"
    TYPE_CHANGED = 6, "Төрөл солигдсон"


class OrderState(models.TextChoices):
    PENDING = "pending", "Дугаар оруулаагүй"
    REGISTERED = "registered", "Бүртгэсэн"
    SIGNED = "signed", "Гарын үсэгтэй"
    CANCELLED = "cancelled", "Цуцалсан"


class OrderFileStorage(FileSystemStorage):
    """Order files live under settings.ORDER_FILES_ROOT, read on every access (not cached),
    so tests can override the setting after the models are loaded."""

    @property
    def base_location(self) -> str:
        return str(settings.ORDER_FILES_ROOT)

    @property
    def location(self) -> str:
        return os.path.abspath(self.base_location)


def order_storage() -> FileSystemStorage:
    return OrderFileStorage()


class HrOrder(models.Model):
    """An HR order (тушаал) tied to one change or to the hire."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="hr_orders")
    event = models.OneToOneField(Event, null=True, blank=True, on_delete=models.PROTECT, related_name="order")
    is_hire = models.BooleanField(default=False)
    order_type = models.SmallIntegerField("Тушаалын төрөл", choices=OrderType.choices)
    state = models.CharField("Төлөв", max_length=12, choices=OrderState.choices, default=OrderState.PENDING)
    number = models.CharField("Тушаалын дугаар", max_length=10, blank=True)
    number_key = models.CharField(max_length=10, blank=True)
    date = models.DateField("Тушаалын огноо", null=True, blank=True)
    summary = models.CharField("Агуулга", max_length=50, blank=True)
    issued_by = models.CharField("Гаргасан", max_length=25, blank=True)
    file = models.FileField("Файл", storage=order_storage, upload_to="%Y/", blank=True)
    command_id = models.IntegerField(null=True, blank=True)
    history_id = models.IntegerField(null=True, blank=True)
    cancel_reason = models.CharField("Цуцлах шалтгаан", max_length=200, blank=True)
    cancel_order_no = models.CharField("Цуцалсан тушаалын дугаар", max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Тушаал"
        verbose_name_plural = "Тушаалууд"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(event__isnull=False, is_hire=False) | models.Q(event__isnull=True, is_hire=True)),
                name="hrorder_event_xor_hire",
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.get_order_type_display()} {self.number}"


class EventProdRow(models.Model):
    """The production rows an event wrote, so cancelling can remove exactly those (spec §4)."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="prod_rows")
    movement_id = models.IntegerField(null=True, blank=True)
    history_id = models.IntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.event_id}: {self.movement_id}/{self.history_id}"


def no_overlap(name: str) -> ExclusionConstraint:
    return ExclusionConstraint(
        name=name,
        expressions=[("employee", RangeOperators.EQUAL), ("period", RangeOperators.OVERLAPS)],
    )


def contract_errors(contract_type: str, start: date | None, end: date | None) -> dict[str, str]:
    """The contract rule shared by the hire form, corrections and job-change events.
    An open-ended contract has no end date (callers clear it); a fixed-term one must have one."""
    if contract_type == ContractType.FIXED_TERM and end is None:
        return {"contract_end": "Хугацаатай гэрээнд дуусах огноог заавал оруулна."}
    if start and end and end < start:
        return {"contract_end": "Гэрээ дуусах огноо эхлэх огнооноос өмнө байж болохгүй."}
    return {}


class JobRecord(models.Model):
    """One period of position/department/status. Written only by services.history."""

    JOB_FIELDS = (
        "position",
        "department",
        "manager",
        "employee_type",
        "emptype",
        "status",
        "contract_type",
        "contract_no",
        "contract_start",
        "contract_end",
    )

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="job_records")
    period = DateRangeField("Хугацаа")
    position = models.ForeignKey(Position, verbose_name="Албан тушаал", on_delete=models.PROTECT)
    department = models.ForeignKey(Department, verbose_name="Хэлтэс", on_delete=models.PROTECT)
    manager = models.ForeignKey(
        Employee, verbose_name="Шууд удирдлага", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    employee_type = models.CharField("Ажилтны төрөл", max_length=20, choices=EmployeeType.choices)
    emptype = models.SmallIntegerField(
        "Ажилтны төрлийн код",
        null=True,
        blank=True,
        choices=[
            (1, "Үндсэн"),
            (3, "Ажлаас гарсан"),
            (5, "Гэрээт (хугацаатай)"),
            (6, "Тэтгэвэрт гарсан"),
            (9, "Туршилтын"),
        ],
    )
    status = models.CharField("Төлөв", max_length=20, choices=JobStatus.choices, default=JobStatus.ACTIVE)
    contract_type = models.CharField("Гэрээний төрөл", max_length=20, choices=ContractType.choices)
    contract_no = models.CharField("Гэрээний дугаар", max_length=10, blank=True)
    contract_start = models.DateField("Гэрээ эхлэх", null=True, blank=True)
    contract_end = models.DateField("Гэрээ дуусах", null=True, blank=True)
    change_type = models.CharField("Өөрчлөлтийн төрөл", max_length=20, choices=ChangeType.choices)
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.PROTECT, related_name="job_records")
    note = models.TextField("Тайлбар", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Ажлын түүх"
        verbose_name_plural = "Ажлын түүх"
        ordering = ["employee", "-period"]
        constraints = [no_overlap("job_record_no_overlap")]

    def __str__(self) -> str:
        return f"{self.employee.code} {self.period}"

    def clean(self) -> None:
        if self.contract_type == ContractType.OPEN_ENDED:
            self.contract_end = None
        if errors := contract_errors(self.contract_type, self.contract_start, self.contract_end):
            raise ValidationError(errors)


class SalaryRecord(models.Model):
    """One period of base salary. Protected by macs.view_salary."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="salary_records")
    period = DateRangeField("Хугацаа")
    base_salary = models.DecimalField("Үндсэн цалин", max_digits=14, decimal_places=2)
    change_type = models.CharField("Өөрчлөлтийн төрөл", max_length=20, choices=ChangeType.choices)
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.PROTECT, related_name="salary_records")
    note = models.TextField("Тайлбар", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Цалингийн түүх"
        verbose_name_plural = "Цалингийн түүх"
        ordering = ["employee", "-period"]
        constraints = [no_overlap("salary_record_no_overlap")]

    def __str__(self) -> str:
        return f"{self.employee.code} {self.period}"


class ActivityKind(models.TextChoices):
    CREATED = "created", "Үүсгэсэн"
    CHANGED = "changed", "Өөрчилсөн"
    CORRECTION = "correction", "Засвар"
    HISTORY = "history", "Огноотой өөрчлөлт"
    NOTE = "note", "Тэмдэглэл"


class AppendOnlyQuerySet(models.QuerySet["ActivityEntry"]):
    def update(self, **kwargs: Any) -> int:
        raise PermissionError("Activity log is append-only")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise PermissionError("Activity log is append-only")


PERSONAL_FIELDS = frozenset(
    {
        "register_no",
        "birth_date",
        "gender",
        "clan_name",
        "citizenship",
        "foreign_emp",
        "nationality",
        "passport_no",
        "marital_status",
        "private_phone",
        "phone2",
        "prior_service_years",
        "prior_service_months",
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
    }
)

EXT_FIELDS = frozenset(
    {
        "prior_service_months",
        "probation_end",
        "blood_rh",
        "living_standard",
    }
)


class AttentionDismissal(models.Model):
    """One user's "Мэдлээ" on one Анхаарах item. The key holds the item's text, so a changed
    item (new date, now overdue) is a different key and shows again (scoping D-013)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="attention_dismissal_once")]

    def __str__(self) -> str:
        return self.key


class ActivityEntry(models.Model):
    """Chatter entry. Never edited or deleted (spec §4)."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="activity")
    at = models.DateTimeField("Огноо", auto_now_add=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField("Төрөл", max_length=20, choices=ActivityKind.choices)
    message = models.TextField("Мессеж")
    changes = models.JSONField("Өөрчлөлтүүд", default=list, blank=True)  # [{"field", "old", "new"}]
    sensitive = models.BooleanField(default=False)  # salary data: hidden without view_salary
    personal = models.BooleanField(default=False)  # Personal-tab data: hidden without view_personal (or own record)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        verbose_name = "Үйл ажиллагааны бүртгэл"
        verbose_name_plural = "Үйл ажиллагааны бүртгэл"
        ordering = ["-at", "-id"]

    def __str__(self) -> str:
        return f"{self.employee.code} {self.get_kind_display()}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise PermissionError("Activity log is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise PermissionError("Activity log is append-only")


class SetupItem(models.Model):
    """One ticked onboarding step (services.setup.ITEMS). Absence = not done."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="setup_items")
    key = models.CharField(max_length=30)
    done_at = models.DateTimeField(auto_now_add=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["employee", "key"], name="setup_item_unique")]

    def __str__(self) -> str:
        return f"{self.employee.code} {self.key}"


class DailySync(models.Model):
    """One row (pk 1): the calendar day the daily MACS sync last ran. See employees/daily_sync.py."""

    day = models.DateField(null=True)

    class Meta:
        db_table = "employees_dailysync"

    def __str__(self) -> str:
        return f"Last daily sync: {self.day}"


class CompanySettings(models.Model):
    """Single row (pk=1) of company details, edited in the admin: used by HR orders (print header, issued-by)."""

    name = models.CharField("Байгууллагын нэр", max_length=100, blank=True)
    director_name = models.CharField(
        "Захирлын нэр", max_length=25, blank=True, help_text="Тушаал гаргасан албан тушаалтны анхны утга."
    )

    class Meta:
        verbose_name = "Байгууллагын тохиргоо"
        verbose_name_plural = "Байгууллагын тохиргоо"
        default_permissions = ("change", "view")

    def __str__(self) -> str:
        return "Байгууллагын тохиргоо"

    @classmethod
    def get(cls) -> "CompanySettings":
        row, _ = cls.objects.get_or_create(pk=1)
        return row
