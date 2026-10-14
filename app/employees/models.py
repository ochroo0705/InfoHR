from collections.abc import Collection
from datetime import date
from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.db import models

from .validators import normalize_register_no, validate_register_no


class ReferenceItem(models.Model):
    """Short list HR edits in the admin. Inactive items stay on old records but can't be chosen."""

    name = models.CharField("Нэр", max_length=150, unique=True)
    active = models.BooleanField("Идэвхтэй", default=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Department(ReferenceItem):
    class Meta(ReferenceItem.Meta):
        verbose_name = "Хэлтэс"
        verbose_name_plural = "Хэлтсүүд"


class Position(ReferenceItem):
    class Meta(ReferenceItem.Meta):
        verbose_name = "Албан тушаал"
        verbose_name_plural = "Албан тушаалууд"


class Gender(models.TextChoices):
    MALE = "male", "Эрэгтэй"
    FEMALE = "female", "Эмэгтэй"


class MaritalStatus(models.TextChoices):
    SINGLE = "single", "Гэрлээгүй"
    MARRIED = "married", "Гэрлэсэн"
    DIVORCED = "divorced", "Салсан"
    WIDOWED = "widowed", "Бэлэвсэн"


class WorkConditions(models.TextChoices):
    NORMAL = "normal", "Хэвийн"
    HARSH = "harsh", "Хүнд, хортой"


class BloodType(models.TextChoices):
    I_POS = "I+", "I (O) Rh+"
    I_NEG = "I-", "I (O) Rh−"
    II_POS = "II+", "II (A) Rh+"
    II_NEG = "II-", "II (A) Rh−"
    III_POS = "III+", "III (B) Rh+"
    III_NEG = "III-", "III (B) Rh−"
    IV_POS = "IV+", "IV (AB) Rh+"
    IV_NEG = "IV-", "IV (AB) Rh−"


class MilitaryService(models.TextChoices):
    SERVED = "served", "Цэргийн алба хаасан"
    NOT_SERVED = "not_served", "Хаагаагүй"
    EXEMPT = "exempt", "Чөлөөлөгдсөн"


class Employee(models.Model):
    code = models.CharField("Ажилтны код", max_length=10, unique=True, editable=False)
    erp_employee_id = models.CharField("ERP ажилтны ID", max_length=50, unique=True, null=True, blank=True)
    family_name = models.CharField("Эцэг/эхийн нэр", max_length=100)
    given_name = models.CharField("Нэр", max_length=100)
    clan_name = models.CharField("Ургийн овог", max_length=100, blank=True)
    register_no = models.CharField("Регистрийн дугаар", max_length=20, unique=True, validators=[validate_register_no])
    birth_date = models.DateField("Төрсөн огноо")
    gender = models.CharField("Хүйс", max_length=10, choices=Gender.choices)
    photo = models.ImageField("Зураг", upload_to="employees/photos/", blank=True)
    work_phone = models.CharField("Ажлын утас", max_length=30)
    private_phone = models.CharField("Хувийн утас", max_length=30, blank=True)
    email = models.EmailField("И-мэйл", blank=True)
    address = models.TextField("Хаяг", blank=True)
    emergency_name = models.CharField("Яаралтай үед холбогдох хүн", max_length=150, blank=True)
    emergency_phone = models.CharField("Яаралтай үед утас", max_length=30, blank=True)
    citizenship = models.CharField("Иргэншил", max_length=50, default="Монгол")
    is_foreigner = models.BooleanField("Гадаадын иргэн", default=False)
    passport_no = models.CharField("Гадаад паспортын дугаар", max_length=30, blank=True)
    marital_status = models.CharField("Гэрлэлтийн байдал", max_length=10, choices=MaritalStatus.choices, blank=True)
    first_hire_date = models.DateField("Анх ажилд орсон огноо")
    prior_service_years = models.PositiveSmallIntegerField("Өмнөх ажилласан жил", default=0)
    prior_service_months = models.PositiveSmallIntegerField("Өмнөх ажилласан сар", default=0)
    work_conditions = models.CharField(
        "Ажлын нөхцөл", max_length=10, choices=WorkConditions.choices, default=WorkConditions.NORMAL
    )
    work_schedule = models.CharField("Ажлын цагийн хуваарь", max_length=100, blank=True)
    probation_end = models.DateField("Туршилтын хугацаа дуусах", null=True, blank=True)
    blood_type = models.CharField("Цусны бүлэг", max_length=5, choices=BloodType.choices, blank=True)
    social_origin = models.CharField("Нийгмийн гарал", max_length=100, blank=True)
    military_service = models.CharField("Цэргийн алба", max_length=20, choices=MilitaryService.choices, blank=True)
    housing_condition = models.CharField("Орон байрны нөхцөл", max_length=100, blank=True)
    living_standard = models.CharField("Амьжиргааны түвшин", max_length=100, blank=True)
    car_ownership = models.CharField("Автомашин эзэмшил", max_length=100, blank=True)
    clothing_size = models.CharField("Хувцасны хэмжээ", max_length=20, blank=True)
    shoe_size = models.CharField("Гутлын хэмжээ", max_length=20, blank=True)
    elected_position = models.CharField("Сонгуульт ажил", max_length=150, blank=True)
    setup_required = models.BooleanField(default=False)  # new hires get the onboarding checklist
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Нэвтрэх эрх",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employee",
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
        verbose_name = "Ажилтан"
        verbose_name_plural = "Ажилтнууд"
        ordering = ["family_name", "given_name"]
        permissions = [
            ("view_employees", "Бүх ажилтныг харах"),
            ("manage_employees", "Ажилтан нэмэх, засах, засвар хийх"),
            ("view_personal", "Хувийн мэдээллийг харах"),
            ("view_salary", "Цалин, даатгалын мэдээллийг харах"),
            ("manage_salary", "Цалин, даатгалын мэдээллийг засах"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.full_name}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.register_no = normalize_register_no(self.register_no)
        super().save(*args, **kwargs)

    @property
    def full_name(self) -> str:
        return f"{self.family_name} {self.given_name}"

    @property
    def short_name(self) -> str:
        """'Алтангэрэлийн Номин' -> 'А. Номин': the usual short form (father's/mother's name initial)."""
        return f"{self.family_name[:1]}. {self.given_name}" if self.family_name else self.given_name

    def clean_fields(self, exclude: Collection[str] | None = None) -> None:
        # Normalise first so length and uniqueness checks see the canonical value.
        self.register_no = normalize_register_no(self.register_no)
        super().clean_fields(exclude=exclude)

    def clean(self) -> None:
        self.register_no = normalize_register_no(self.register_no)

    @classmethod
    def next_code(cls) -> str:
        last = cls.objects.order_by("-code").values_list("code", flat=True).first()
        number = int(last[1:]) + 1 if last else 1
        return f"E{number:04d}"


class FamilyMember(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="family")
    name = models.CharField("Нэр", max_length=150)
    relation = models.CharField("Хамаарал", max_length=50)
    birth_year = models.PositiveSmallIntegerField("Төрсөн он", null=True, blank=True)

    class Meta:
        verbose_name = "Гэр бүлийн гишүүн"
        verbose_name_plural = "Гэр бүлийн гишүүд"

    def __str__(self) -> str:
        return f"{self.name} ({self.relation})"


class Education(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="education")
    school = models.CharField("Сургууль", max_length=200)
    degree = models.CharField("Зэрэг", max_length=100, blank=True)
    field = models.CharField("Мэргэжил", max_length=150, blank=True)
    graduation_year = models.PositiveSmallIntegerField("Төгссөн он", null=True, blank=True)

    class Meta:
        verbose_name = "Боловсрол"
        verbose_name_plural = "Боловсрол"

    def __str__(self) -> str:
        return self.school


class Talent(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="talents")
    name = models.CharField("Авьяас", max_length=150)
    trained_year = models.PositiveSmallIntegerField("Суралцсан он", null=True, blank=True)
    description = models.CharField("Тайлбар", max_length=200, blank=True)

    class Meta:
        verbose_name = "Авьяас"
        verbose_name_plural = "Авьяас"
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class Gift(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="gifts")
    gift_type = models.CharField("Бэлгийн төрөл", max_length=100)
    given_date = models.DateField("Олгосон огноо")
    child_count = models.PositiveSmallIntegerField("Хүүхдийн тоо", null=True, blank=True)
    amount = models.DecimalField("Үнэ", max_digits=14, decimal_places=2, null=True, blank=True)
    note = models.CharField("Тайлбар", max_length=200, blank=True)

    class Meta:
        verbose_name = "Олгосон бэлэг"
        verbose_name_plural = "Олгосон бэлэг"
        ordering = ["-given_date"]

    def __str__(self) -> str:
        return f"{self.gift_type} {self.given_date}"


class SalaryInsurance(models.Model):
    """Protected details: guarded by employees.view_salary / manage_salary."""

    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="salary_insurance")
    bank = models.CharField("Банк", max_length=100, blank=True)
    account_no = models.CharField("Дансны дугаар", max_length=50, blank=True)
    social_insurance_no = models.CharField("НДД-ийн дугаар", max_length=50, blank=True)
    health_insurance_no = models.CharField("ЭМДД-ийн дугаар", max_length=50, blank=True)
    insured_category = models.CharField("Даатгуулагчийн төрөл", max_length=100, blank=True)
    taxpayer_no = models.CharField("Татвар төлөгчийн дугаар", max_length=50, blank=True)
    has_disability = models.BooleanField("Хөгжлийн бэрхшээлтэй", default=False)

    class Meta:
        verbose_name = "Цалин, даатгал"
        verbose_name_plural = "Цалин, даатгал"

    def __str__(self) -> str:
        return f"Цалин, даатгал: {self.employee}"


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


class TerminationReason(models.TextChoices):
    RESIGNATION = "resignation", "Өөрийн хүсэлтээр"
    MUTUAL = "mutual", "Харилцан тохиролцсон"
    CONTRACT_END = "contract_end", "Гэрээний хугацаа дууссан"
    DISMISSAL = "dismissal", "Ажлаас халсан"
    RETIREMENT = "retirement", "Тэтгэвэрт гарсан"
    DEATH = "death", "Нас барсан"


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


def no_overlap(name: str) -> ExclusionConstraint:
    return ExclusionConstraint(
        name=name,
        expressions=[("employee", RangeOperators.EQUAL), ("period", RangeOperators.OVERLAPS)],
    )


class JobRecord(models.Model):
    """One period of position/department/status. Written only by services.history."""

    JOB_FIELDS = (
        "position",
        "department",
        "manager",
        "employee_type",
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
    status = models.CharField("Төлөв", max_length=20, choices=JobStatus.choices, default=JobStatus.ACTIVE)
    contract_type = models.CharField("Гэрээний төрөл", max_length=20, choices=ContractType.choices)
    contract_no = models.CharField("Гэрээний дугаар", max_length=50, blank=True)
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


class SalaryRecord(models.Model):
    """One period of base salary. Protected by employees.view_salary."""

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
        "is_foreigner",
        "passport_no",
        "marital_status",
        "private_phone",
        "address",
        "emergency_name",
        "emergency_phone",
        "prior_service_years",
        "prior_service_months",
        "blood_type",
        "social_origin",
        "military_service",
        "housing_condition",
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
