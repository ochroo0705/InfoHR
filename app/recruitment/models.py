"""Recruitment: vacancies and candidates moving through fixed stages (spec 2026-11-02).

Own Info HR tables only. Stage moves, rejection, conversion and purge are rules kept in
recruitment.services; these models just hold the data. CandidateEvent and CandidateComment are append-only.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class Stage(models.TextChoices):
    NEW = "new", "Шинэ"
    SCREENING = "screening", "Шалгаруулалт"
    INTERVIEW = "interview", "Ярилцлага"
    OFFER = "offer", "Санал"
    HIRED = "hired", "Ажилд авсан"
    REJECTED = "rejected", "Татгалзсан"
    WITHDRAWN = "withdrawn", "Өөрөө татгалзсан"


class VacancyStatus(models.TextChoices):
    OPEN = "open", "Нээлттэй"
    CLOSED = "closed", "Хаагдсан"
    FILLED = "filled", "Бөглөгдсөн"


class Vacancy(models.Model):
    title = models.CharField("Нэр", max_length=200)
    position = models.ForeignKey(
        "macs.Position", verbose_name="Албан тушаал", on_delete=models.PROTECT, related_name="+"
    )
    department = models.ForeignKey("macs.Department", verbose_name="Хэлтэс", on_delete=models.PROTECT, related_name="+")
    branch = models.ForeignKey(
        "macs.Branch", verbose_name="Салбар", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    headcount = models.PositiveSmallIntegerField("Авах хүний тоо", default=1, validators=[MinValueValidator(1)])
    hiring_manager = models.ForeignKey(
        "macs.Employee",
        verbose_name="Ажилд авах удирдлага",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    deadline = models.DateField("Авах эцсийн хугацаа", null=True, blank=True)
    desired_start = models.DateField("Ажил эхлэх огноо", null=True, blank=True)
    description = models.TextField("Тайлбар", blank=True)
    status = models.CharField("Төлөв", max_length=10, choices=VacancyStatus.choices, default=VacancyStatus.OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Нээлттэй ажлын байр"
        verbose_name_plural = "Нээлттэй ажлын байрууд"
        ordering = ["-created_at", "-pk"]
        default_permissions = ()
        permissions = [("manage_recruitment", "Ажилд авах ажил удирдах")]
        constraints = [
            models.CheckConstraint(
                condition=Q(headcount__gte=1),
                name="recruitment_vacancy_headcount_gte_1",
                violation_error_message="Авах хүний тоо 1-ээс бага байж болохгүй.",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class Candidate(models.Model):
    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE, related_name="candidates")
    surname = models.CharField("Овог", max_length=100)
    given_name = models.CharField("Нэр", max_length=100)
    phone = models.CharField("Утас", max_length=50, blank=True)
    email = models.EmailField("И-мэйл", blank=True)
    source = models.CharField("Эх сурвалж", max_length=100, blank=True)
    notes = models.TextField("Тэмдэглэл", blank=True)
    stage = models.CharField("Шат", max_length=10, choices=Stage.choices, default=Stage.NEW)
    reject_reason = models.TextField("Татгалзсан шалтгаан", blank=True)
    # Set when the candidate is rejected or withdraws; the purge cutoff counts from here.
    closed_at = models.DateTimeField("Хаагдсан огноо", null=True, blank=True)
    employee = models.ForeignKey(
        "macs.Employee", verbose_name="Ажилтан", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ажил хүсэгч"
        verbose_name_plural = "Ажил хүсэгчид"
        ordering = ["-created_at", "-pk"]
        default_permissions = ()
        indexes = [
            models.Index(fields=["vacancy", "stage"], name="recruit_cand_vacancy_stage_idx"),
            models.Index(fields=["stage", "closed_at"], name="recruit_cand_stage_closed_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.surname} {self.given_name}"


class CandidateFile(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="files")
    # Path under the private storage root (outside MEDIA_ROOT); served only by a view that checks visibility.
    file = models.CharField("Файл", max_length=500)
    name = models.CharField("Файлын нэр", max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ажил хүсэгчийн файл"
        verbose_name_plural = "Ажил хүсэгчийн файлууд"
        ordering = ["uploaded_at", "pk"]
        default_permissions = ()

    def __str__(self) -> str:
        return self.name


class CandidateEvent(models.Model):
    """One stage move (append-only). from_stage is empty for the first row (candidate added)."""

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="events")
    from_stage = models.CharField("Өмнөх шат", max_length=10, choices=Stage.choices, blank=True)
    to_stage = models.CharField("Шат", max_length=10, choices=Stage.choices)
    note = models.TextField("Тайлбар", blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    at = models.DateTimeField(auto_now_add=True, db_column="at_time")

    class Meta:
        verbose_name = "Ажил хүсэгчийн түүх"
        verbose_name_plural = "Ажил хүсэгчийн түүх"
        ordering = ["at", "pk"]
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.from_stage or '-'} -> {self.to_stage}"


class CandidateComment(models.Model):
    """A comment on a candidate (append-only)."""

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField("Сэтгэгдэл")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    at = models.DateTimeField(auto_now_add=True, db_column="at_time")

    class Meta:
        verbose_name = "Сэтгэгдэл"
        verbose_name_plural = "Сэтгэгдлүүд"
        ordering = ["at", "pk"]
        default_permissions = ()

    def __str__(self) -> str:
        return self.text[:50]


class RecruitmentSettings(models.Model):
    """Single row (pk=1). Admin edits it in the admin."""

    retention_months = models.PositiveSmallIntegerField(
        "Татгалзсан ажил хүсэгчийг хадгалах хугацаа (сар)",
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
    )

    class Meta:
        verbose_name = "Ажилд авах тохиргоо"
        verbose_name_plural = "Ажилд авах тохиргоо"
        default_permissions = ()

    def __str__(self) -> str:
        return "Ажилд авах тохиргоо"

    @classmethod
    def get(cls) -> "RecruitmentSettings":
        row, _ = cls.objects.get_or_create(pk=1)
        return row
