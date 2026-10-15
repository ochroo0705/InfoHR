"""Leave module (spec docs/superpowers/specs/2026-10-14-leave-design.md §3)."""

from datetime import date

from django.conf import settings
from django.db import models
from employees.models import Employee

DAYS = {"max_digits": 5, "decimal_places": 1}


class Holiday(models.Model):
    date = models.DateField("Огноо", unique=True)
    name = models.CharField("Нэр", max_length=100)

    class Meta:
        verbose_name = "Баярын өдөр"
        verbose_name_plural = "Баярын өдрүүд"
        ordering = ["date"]
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.date} {self.name}"


class LeaveType(models.Model):
    ANNUAL = "annual"

    code = models.SlugField("Код", max_length=30, unique=True)
    name = models.CharField("Нэр", max_length=100)
    is_paid = models.BooleanField("Цалинтай", default=False)
    uses_annual_balance = models.BooleanField("Ээлжийн амралтаас хасна", default=False)
    is_active = models.BooleanField("Идэвхтэй", default=True)
    order = models.PositiveSmallIntegerField("Дараалал", default=0)

    class Meta:
        verbose_name = "Чөлөөний төрөл"
        verbose_name_plural = "Чөлөөний төрлүүд"
        ordering = ["order", "name"]
        default_permissions = ()

    def __str__(self) -> str:
        return self.name


class AnnualLeaveRule(models.Model):
    """Law values with an effective date; a law change is a new row (leave-scope §3)."""

    effective_from = models.DateField("Хүчинтэй огноо", unique=True)
    base_days = models.DecimalField("Үндсэн амралт (ажлын өдөр)", max_digits=5, decimal_places=1)
    base_days_minor_or_disabled = models.DecimalField(
        "18-аас доош / хөгжлийн бэрхшээлтэй", max_digits=5, decimal_places=1
    )
    brackets = models.JSONField("Нэмэгдэл амралт", help_text='[{"from_month": 61, "extra_days": 3}, ...]')
    min_continuous_part = models.PositiveSmallIntegerField("Тасралтгүй хэсгийн доод хэмжээ", default=10)
    eligibility_months = models.PositiveSmallIntegerField("Эрх үүсэх сар", default=6)

    class Meta:
        verbose_name = "Ээлжийн амралтын хуулийн тохиргоо"
        verbose_name_plural = "Ээлжийн амралтын хуулийн тохиргоо"
        ordering = ["-effective_from"]
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.effective_from}-аас"


class GrantKind(models.TextChoices):
    AUTO = "auto", "Хуулийн дагуу"
    ADJUSTMENT = "adjustment", "Гараар засвар"
    CARRY_OVER = "carry_over", "Шилжүүлсэн"


class LeaveGrant(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leave_grants")
    year_start = models.DateField("Ажлын жил эхлэх")
    days = models.DecimalField("Хоног", max_digits=5, decimal_places=1)
    kind = models.CharField("Төрөл", max_length=20, choices=GrantKind.choices)
    reason = models.CharField("Шалтгаан", max_length=200, blank=True)
    breakdown = models.CharField("Тооцоо", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Амралтын эрх"
        verbose_name_plural = "Амралтын эрх"
        ordering = ["employee", "-year_start", "created_at"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year_start"], condition=models.Q(kind="auto"), name="leave_one_auto_grant_per_year"
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee.code} {self.year_start} {self.days}"


class LeaveStatus(models.TextChoices):
    RECORDED = "recorded", "Бүртгэсэн"
    CANCELLED = "cancelled", "Цуцалсан"
    MISTAKE = "mistake", "Буруу бүртгэсэн"  # a leave that had started or ended, removed as a recording error


class Leave(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leaves")
    leave_type = models.ForeignKey(LeaveType, verbose_name="Төрөл", on_delete=models.PROTECT, related_name="+")
    start_date = models.DateField("Эхлэх")
    end_date = models.DateField("Дуусах")
    start_half = models.BooleanField("Эхний өдөр хагас", default=False)
    end_half = models.BooleanField("Сүүлийн өдөр хагас", default=False)
    working_days = models.DecimalField("Ажлын өдөр", max_digits=5, decimal_places=1)
    year_start = models.DateField("Ажлын жил", null=True, blank=True)  # annual only: the year it is charged to
    note = models.TextField("Тайлбар", blank=True)
    override_reason = models.CharField("Үлдэгдэл хасах шалтгаан", max_length=200, blank=True)
    status = models.CharField("Төлөв", max_length=20, choices=LeaveStatus.choices, default=LeaveStatus.RECORDED)
    cancel_reason = models.CharField("Цуцлах шалтгаан", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Чөлөө"
        verbose_name_plural = "Чөлөө"
        ordering = ["-start_date", "-id"]
        default_permissions = ()
        permissions = [
            ("view_leave", "Чөлөө харах"),
            ("record_leave", "Чөлөө бүртгэх"),
            ("manage_leave_settings", "Чөлөөний тохиргоо"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")), name="leave_end_after_start"
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee.code} {self.leave_type} {self.start_date}–{self.end_date}"

    def started(self, today: date) -> bool:
        """Started or over: removing it is a correction ("Буруу бүртгэсэн"), not a change of plan."""
        return self.start_date <= today
