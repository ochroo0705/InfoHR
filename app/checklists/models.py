"""Checklists: a generic task list per employee event (offboarding now, onboarding later).

A template is edited by an Admin; a checklist copies its tasks when it starts, so later template edits
never change a running checklist. Owners are not stored on the task as people: a task stores its owner
rule (a role group or the direct manager) and the people are resolved when someone acts
(checklists.services.owners).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class ChecklistKind(models.TextChoices):
    OFFBOARDING = "offboarding", "Ажлаас гарах"
    ONBOARDING = "onboarding", "Ажилд орох"


class ChecklistState(models.TextChoices):
    OPEN = "open", "Нээлттэй"
    COMPLETED = "completed", "Дууссан"
    CANCELLED = "cancelled", "Цуцлагдсан"


class ChecklistTemplate(models.Model):
    kind = models.CharField("Төрөл", max_length=20, choices=ChecklistKind.choices)
    name = models.CharField("Нэр", max_length=200)
    # Used when no template lists the reason. One default per kind (constraint below).
    is_default = models.BooleanField("Үндсэн загвар", default=False)
    # What this template covers: fired_reason ids (as text, macs.FiredReason pk) for offboarding,
    # employees.EmployeeType values for onboarding.
    reasons = models.JSONField("Шалтгаанууд", default=list, blank=True)
    active = models.BooleanField("Идэвхтэй", default=True)

    class Meta:
        verbose_name = "Жагсаалтын загвар"
        verbose_name_plural = "Жагсаалтын загварууд"
        ordering = ["kind", "name"]
        default_permissions = ()
        permissions = [
            ("manage_checklists", "Жагсаалтын загвар засах"),
            ("override_offboarding", "Жагсаалт дуусаагүй байхад ажлаас гаргах"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["kind"],
                condition=Q(is_default=True),
                name="checklist_tpl_one_default",
                violation_error_message="Энэ төрөлд үндсэн загвар аль хэдийн байна.",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ChecklistTemplateTask(models.Model):
    template = models.ForeignKey(ChecklistTemplate, on_delete=models.CASCADE, related_name="tasks")
    position = models.PositiveSmallIntegerField("Дараалал", default=0, db_column="position_no")
    title = models.CharField("Даалгавар", max_length=200)
    # Exactly one owner: a role group, or the direct manager. PROTECT: a role used by a template cannot vanish.
    group = models.ForeignKey(
        "auth.Group", on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="Эрхийн бүлэг"
    )
    manager = models.BooleanField("Шууд удирдлага", default=False)
    due_offset_days = models.SmallIntegerField(
        "Хугацаа (өдөр)",
        default=0,
        help_text="Хугацааны эхлэлээс (ажилд орсон / сүүлийн ажлын өдөр); хасах утга байж болно.",
    )
    required = models.BooleanField("Заавал биелүүлэх", default=True)

    class Meta:
        verbose_name = "Загварын даалгавар"
        verbose_name_plural = "Загварын даалгаврууд"
        ordering = ["position", "pk"]
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(Q(group__isnull=False, manager=False) | Q(group__isnull=True, manager=True)),
                name="checklist_tpl_task_one_owner",
                violation_error_message="Даалгаварт нэг эзэн (эрхийн бүлэг эсвэл шууд удирдлага) заана.",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class Checklist(models.Model):
    employee = models.ForeignKey("macs.Employee", on_delete=models.PROTECT, related_name="checklists")
    kind = models.CharField("Төрөл", max_length=20, choices=ChecklistKind.choices)
    template = models.ForeignKey(ChecklistTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    template_name = models.CharField("Загварын нэр", max_length=200)
    anchor_day = models.DateField("Хугацааны эхлэл (ажилд орсон / сүүлийн ажлын өдөр)")
    state = models.CharField("Төлөв", max_length=20, choices=ChecklistState.choices, default=ChecklistState.OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # The termination (employees.Event) this checklist was completed for.
    event = models.ForeignKey("employees.Event", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "Жагсаалт"
        verbose_name_plural = "Жагсаалтууд"
        ordering = ["-created_at", "-pk"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "kind"],
                condition=Q(state="open"),
                name="checklist_one_open_emp_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template_name} ({self.employee_id})"


class ChecklistTask(models.Model):
    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name="tasks")
    position = models.PositiveSmallIntegerField("Дараалал", default=0, db_column="position_no")
    title = models.CharField("Даалгавар", max_length=200)
    group = models.ForeignKey(
        "auth.Group", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Эрхийн бүлэг"
    )
    manager = models.BooleanField("Шууд удирдлага", default=False)
    due_on = models.DateField("Хугацаа")
    required = models.BooleanField("Заавал биелүүлэх", default=True)
    done_at = models.DateTimeField("Биелсэн огноо", null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Жагсаалтын даалгавар"
        verbose_name_plural = "Жагсаалтын даалгаврууд"
        ordering = ["position", "pk"]
        default_permissions = ()
        indexes = [
            models.Index(fields=["done_at"], name="checklist_task_done_at_idx"),
            models.Index(fields=["group"], name="checklist_task_group_idx"),
        ]

    def __str__(self) -> str:
        return self.title
