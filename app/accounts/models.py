from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from macs.models import Employee


class User(AbstractUser):
    """Login account. Roles are Django groups (see accounts.roles)."""

    # Set when a manager hands over a system-made temporary password; cleared when the user changes it.
    must_change_password = models.BooleanField("нууц үгээ солих ёстой", default=False)

    class Meta:
        # Own Meta replaces AbstractUser's, so repeat its (translated) names.
        verbose_name = _("user")
        verbose_name_plural = _("users")
        permissions = [
            # Admin-controlled switches (core-hr-scope §1), granted per role group.
            ("approve_leave", "Чөлөө, амралт батлах"),
            ("issue_orders", "Тушаал гаргах / баталгаажуулах"),
            ("export_lists", "Жагсаалтыг Excel рүү гаргах"),
            ("view_audit", "Үйл ажиллагааны бүртгэл харах"),
        ]

    def get_full_name(self) -> str:
        """Mongolian order, like Employee.full_name: family (patronymic) name first."""
        return f"{self.last_name} {self.first_name}".strip()

    @property
    def employee(self) -> "Employee | None":
        ext = getattr(self, "employee_ext", None)
        return ext.employee if ext is not None else None


class AccessScope(models.Model):
    """Which employees a user may see. No row, or limited=False, means no limit (the default for every user).

    The ids are stored as plain lists: branches and departments are not foreign keys here, so a deleted
    branch or department id just stops matching anything.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Хэрэглэгч",
        on_delete=models.CASCADE,
        related_name="access_scope",
    )
    limited = models.BooleanField("Хязгаарлагдсан", default=False)
    branch_ids = models.JSONField("Салбарууд", default=list, blank=True)
    department_ids = models.JSONField("Хэлтсүүд", default=list, blank=True)
    include_sub_departments = models.BooleanField("Дэд хэлтсийг оруулах", default=True)
    own_team = models.BooleanField("Өөрийн багийг харах", default=False)

    class Meta:
        verbose_name = "Үзэх хүрээ"
        verbose_name_plural = "Үзэх хүрээ"

    def __str__(self) -> str:
        return str(self.user)


class AppendOnlyLogQuerySet(models.QuerySet["SystemLogEntry"]):
    def update(self, **kwargs: Any) -> int:
        raise PermissionError("System log is append-only")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise PermissionError("System log is append-only")


class SystemLogEntry(models.Model):
    """System log (audit trail): who did what, when, from which IP. Never edited or deleted.

    Deleting a User does not delete its log rows: the actor FK is SET_NULL, and Django's collector
    updates it without going through AppendOnlyLogQuerySet. That rewrite is intended; actor_name
    keeps the username, so the entry still says who did it.
    """

    at = models.DateTimeField("Огноо", auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Хэн", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_name = models.CharField("Хэний нэр", max_length=150, blank=True)  # kept even if the user is deleted
    category = models.CharField("Ангилал", max_length=20)
    action = models.CharField("Үйлдэл", max_length=40)
    target_type = models.CharField("Объектын төрөл", max_length=60, blank=True)
    target_label = models.CharField("Объект", max_length=200, blank=True)
    message = models.TextField("Мессеж", blank=True)
    changes = models.JSONField("Өөрчлөлтүүд", default=list, blank=True)  # [{"field", "old", "new"}]
    ip = models.GenericIPAddressField("IP хаяг", null=True, blank=True)

    objects = AppendOnlyLogQuerySet.as_manager()

    class Meta:
        verbose_name = "Системийн бүртгэл"
        verbose_name_plural = "Системийн бүртгэл"
        ordering = ["-at", "-id"]
        indexes = [
            models.Index(fields=["at"]),
            models.Index(fields=["actor", "at"]),
            models.Index(fields=["category", "at"]),
        ]

    def __str__(self) -> str:
        when = f"{self.at:%Y-%m-%d %H:%M}" if self.at is not None else "-"  # unsaved instances have no time yet
        return f"{when} {self.actor_name} {self.action}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise PermissionError("System log is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise PermissionError("System log is append-only")
