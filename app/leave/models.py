"""Leave module: app-owned extension tables next to the production MACS leave tables.

Production rows (leave_type, leave_assign, entitlement, hr_legalholidays) live in `macs`
(app/macs/models.py). The tables here (schema `hr`) only add what production does not have.
Each ext row is keyed by the production row it extends; ext rows whose production row is
gone are ignored (no constraint on the production side, D-017).
"""

from typing import NamedTuple

from django.conf import settings
from django.db import models
from macs.models import Entitlement, LeaveAssign, LeaveTypeRow


class Step(NamedTuple):
    """One approval step: a role group (group id) or the person's line manager (manager=True)."""

    group_id: int | None
    manager: bool


class RequestStatus(models.TextChoices):
    WAITING = "waiting", "Хүлээгдэж буй"
    APPROVED = "approved", "Батлагдсан"
    REJECTED = "rejected", "Татгалзсан"
    WITHDRAWN = "withdrawn", "Буцаасан"


class ActionKind(models.TextChoices):
    SUBMITTED = "submitted", "Хүсэлт гаргасан"
    APPROVED = "approved", "Батласан"
    REJECTED = "rejected", "Татгалзсан"
    WITHDRAWN = "withdrawn", "Буцаасан"


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
    staff_may_request = models.BooleanField("Ажилтан хүсэлт гаргана", default=True)

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
    approval1_group = models.ForeignKey(
        "auth.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="1-р шат: баталгаажуулах бүлэг",
        related_name="+",
    )
    approval1_manager = models.BooleanField("1-р шат: шууд удирдлага", default=False)
    approval2_group = models.ForeignKey(
        "auth.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="2-р шат: баталгаажуулах бүлэг",
        related_name="+",
    )
    approval2_manager = models.BooleanField("2-р шат: шууд удирдлага", default=False)
    approval_role_removed = models.BooleanField("Баталгаажуулах эрх хасагдсан", default=False)

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

    @property
    def approval_on(self) -> bool:
        """Approval is on when step 1 has a group or the line manager."""
        return bool(self.approval1_group_id or self.approval1_manager)

    def steps(self) -> list[Step]:
        """Configured approval steps in order. Step 2 counts only when step 1 is set."""
        if not self.approval_on:
            return []
        steps = [Step(self.approval1_group_id, self.approval1_manager)]
        if self.approval2_group_id or self.approval2_manager:
            steps.append(Step(self.approval2_group_id, self.approval2_manager))
        return steps


class LeaveRequest(models.Model):
    """A leave request from a staff member, waiting for approval or already decided."""

    employee = models.ForeignKey(
        "macs.Employee",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        verbose_name="Ажилтан",
        related_name="+",
    )
    leave_type = models.ForeignKey(
        LeaveTypeRow,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        verbose_name="Амралтын төрөл",
        related_name="+",
    )
    start_date = models.DateField("Эхлэх огноо")
    end_date = models.DateField("Дуусах огноо")
    working_days = models.PositiveSmallIntegerField("Ажлын өдөр")
    note = models.CharField("Тайлбар", max_length=200, blank=True)
    status = models.CharField(
        "Төлөв", max_length=20, choices=RequestStatus.choices, default=RequestStatus.WAITING, db_index=True
    )
    current_step = models.PositiveSmallIntegerField("Одоогийн шат", default=1)
    step1_group = models.ForeignKey(
        "auth.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="1-р шат: бүлэг",
        related_name="+",
    )
    step2_group = models.ForeignKey(
        "auth.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="2-р шат: бүлэг",
        related_name="+",
    )
    step1_manager = models.BooleanField("1-р шат: шууд удирдлага", default=False)
    step2_manager = models.BooleanField("2-р шат: шууд удирдлага", default=False)
    step_count = models.PositiveSmallIntegerField("Шатны тоо")
    reason = models.CharField("Татгалзсан шалтгаан", max_length=200, blank=True)
    assign_id = models.IntegerField("Бүртгэсэн чөлөөний ID", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField("Үүсгэсэн огноо", auto_now_add=True)
    updated_at = models.DateTimeField("Засварласан огноо", auto_now=True)

    class Meta:
        verbose_name = "Чөлөөний хүсэлт"
        verbose_name_plural = "Чөлөөний хүсэлтүүд"
        default_permissions = ()
        permissions = [("request_own_leave", "Өөрийн чөлөө хүсэх")]

    def __str__(self) -> str:
        return f"Хүсэлт {self.pk}"

    def step(self, n: int) -> Step:
        """Approver of step n (1 or 2)."""
        if n == 1:
            return Step(self.step1_group_id, self.step1_manager)
        if n == 2:
            return Step(self.step2_group_id, self.step2_manager)
        raise ValueError(f"Шат {n} байхгүй")


class LeaveRequestAction(models.Model):
    """One entry in the history of a leave request (submitted, approved, rejected, withdrawn)."""

    request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="actions")
    step = models.PositiveSmallIntegerField("Шат", default=0)
    action = models.CharField("Үйлдэл", max_length=20, choices=ActionKind.choices)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    override = models.BooleanField("Онцгой эрхээр", default=False)
    reason = models.CharField("Шалтгаан", max_length=200, blank=True)
    at = models.DateTimeField("Огноо", auto_now_add=True)

    class Meta:
        verbose_name = "Чөлөөний хүсэлтийн түүх"
        verbose_name_plural = "Чөлөөний хүсэлтийн түүх"
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.request_id}: {self.action}"


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
