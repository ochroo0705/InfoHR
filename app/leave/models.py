"""Leave module: app-owned extension tables next to the production MACS leave tables.

Production rows (leave_type, leave_assign, entitlement, hr_legalholidays) live in `macs`
(app/macs/models.py). The tables here (schema `hr`) only add what production does not have.
Each ext row is keyed by the production row it extends; ext rows whose production row is
gone are ignored (no constraint on the production side, D-017).
"""

from django.conf import settings
from django.db import models
from macs.models import Entitlement, LeaveAssign, LeaveTypeRow


class LeaveTypeExt(models.Model):
    leave_type = models.OneToOneField(
        LeaveTypeRow,
        primary_key=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        verbose_name="Амралтын төрөл",
        related_name="+",
    )
    is_paid = models.BooleanField("Цалинтай", default=False)
    uses_annual_balance = models.BooleanField("Ээлжийн амралтаас хасна", default=False)
    is_active = models.BooleanField("Идэвхтэй", default=True)
    order = models.PositiveSmallIntegerField("Дараалал", default=0)

    class Meta:
        verbose_name = "Чөлөөний төрлийн тохиргоо"
        verbose_name_plural = "Чөлөөний төрлийн тохиргоо"
        ordering = ["order"]
        default_permissions = ()

    def __str__(self) -> str:
        return str(self.leave_type)


def type_ext(leave_type: LeaveTypeRow) -> LeaveTypeExt:
    """Saved settings for a leave type, or unsaved defaults when none were stored yet."""
    return LeaveTypeExt.objects.filter(pk=leave_type.pk).first() or LeaveTypeExt(leave_type=leave_type)


class LeaveExt(models.Model):
    assign = models.OneToOneField(
        LeaveAssign,
        primary_key=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        verbose_name="Ээлжийн амралт",
        related_name="+",
    )
    mistake = models.BooleanField("Буруу бүртгэсэн", default=False)
    override_reason = models.CharField("Үлдэгдэл хасах шалтгаан", max_length=200, blank=True)
    cancel_reason = models.CharField("Цуцлах шалтгаан", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Чөлөөний нэмэлт мэдээлэл"
        verbose_name_plural = "Чөлөөний нэмэлт мэдээлэл"
        default_permissions = ()
        permissions = [
            ("view_leave", "Чөлөө харах"),
            ("record_leave", "Чөлөө бүртгэх"),
            ("manage_leave_settings", "Чөлөөний тохиргоо"),
        ]

    def __str__(self) -> str:
        return f"Чөлөө {self.pk}"


class GrantKind(models.TextChoices):
    AUTO = "auto", "Хуулийн дагуу"
    ADJUSTMENT = "adjustment", "Гараар засвар"
    CARRY_OVER = "carry_over", "Шилжүүлсэн"
    MANUAL = "manual", "Гараар оруулсан"


class LeaveGrantExt(models.Model):
    grant = models.OneToOneField(
        Entitlement,
        primary_key=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        verbose_name="Амралтын эрх",
        related_name="+",
    )
    kind = models.CharField("Төрөл", max_length=20, choices=GrantKind.choices)
    breakdown = models.CharField("Тооцоо", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Амралтын эрхийн нэмэлт мэдээлэл"
        verbose_name_plural = "Амралтын эрхийн нэмэлт мэдээлэл"
        default_permissions = ()

    def __str__(self) -> str:
        return f"Эрх {self.pk}"


class LeaveSettings(models.Model):
    """Single row (pk=1) of leave switches."""

    auto_annual_grant = models.BooleanField("Ээлжийн амралтын эрхийг автоматаар нэмэх", default=False)

    class Meta:
        verbose_name = "Чөлөөний тохиргоо"
        verbose_name_plural = "Чөлөөний тохиргоо"
        default_permissions = ()

    def __str__(self) -> str:
        return "Чөлөөний тохиргоо"

    @classmethod
    def get(cls) -> "LeaveSettings":
        settings_row, _ = cls.objects.get_or_create(pk=1)
        return settings_row


class AnnualLeaveRule(models.Model):
    """Law values with an effective date; a law change is a new row (leave-scope §3)."""

    effective_from = models.DateField("Хүчинтэй огноо", unique=True)
    base_days = models.PositiveSmallIntegerField("Үндсэн амралт (ажлын өдөр)")
    base_days_minor_or_disabled = models.PositiveSmallIntegerField("18-аас доош / хөгжлийн бэрхшээлтэй")
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
