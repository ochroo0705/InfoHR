from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from assistant.catalog import DEFAULT_TIMEOUT, PROVIDER_CHOICES, TIMEOUT_MAX, TIMEOUT_MIN


class Outcome(models.TextChoices):
    """How a help question ended."""

    ANSWERED = "answered", "Хариулсан"
    NONE = "none", "Олдсонгүй"
    ERROR = "error", "Алдаа"
    LIMITED = "limited", "Хязгаарлагдсан"
    TABLE = "table", "Хүснэгт"
    ACTION = "action", "Үйлдэл"


class Kind(models.TextChoices):
    """What a corrected example is used for."""

    EXAMPLE = "example", "Жишээ (туслах сурна)"
    TEST = "test", "Тест (зөвхөн хэмжинэ)"


class HelpQuestion(models.Model):
    """One question typed into the help assistant. Written by the service, read in the admin."""

    asked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    question = models.CharField(max_length=300)
    entry = models.CharField(max_length=40, blank=True)  # the help entry shown as the answer, if any
    also = models.CharField(max_length=40, blank=True)  # a related help entry, if any
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    provider = models.CharField(max_length=20, blank=True)
    model = models.CharField(max_length=60, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    allowed = models.TextField(blank=True)  # asker's allowed entry keys, comma-separated
    error = models.CharField("Алдааны шалтгаан", max_length=300, blank=True)  # why a failed call failed
    tool = models.CharField("Хэрэгсэл", max_length=12, blank=True)  # the plan's tool: entry, staff_table, none
    query = models.CharField("Шүүлтүүрийн холбоос", max_length=300, blank=True)  # the table answer's filter query
    not_applied = models.CharField("Хэрэглээгүй хэсэг", max_length=300, blank=True)  # the parts not applied, joined

    class Meta:
        ordering = ["-asked_at"]
        verbose_name = "Туслахын асуулт"
        verbose_name_plural = "Туслахын асуултууд"

    def __str__(self) -> str:
        return self.question


class HelpExample(models.Model):
    """A corrected answer: a question and the entry that should answer it. Admins write these; no delete, use active."""

    question = models.CharField("Асуулт", max_length=300)
    entry = models.CharField("Зөв хариулт", max_length=40, blank=True)  # blank = no entry in the system does this
    expected = models.CharField(
        "Хүлээгдэх шүүлтүүр", max_length=300, blank=True
    )  # a filter query; set = a filter sentence (its entry stays blank)
    kind = models.CharField("Төрөл", max_length=10, choices=Kind.choices, default=Kind.EXAMPLE)
    active = models.BooleanField("Идэвхтэй", default=True)
    source = models.ForeignKey(
        HelpQuestion, on_delete=models.SET_NULL, null=True, blank=True, related_name="corrections"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField("Үүсгэсэн", auto_now_add=True)
    changed_at = models.DateTimeField("Өөрчилсөн", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Сурсан жишээ, тест"
        verbose_name_plural = "Сурсан жишээ, тест"

    def __str__(self) -> str:
        return self.question


class AssistantSettings(models.Model):
    """Single row (pk=1): which AI the help assistant uses. Set in the admin console; until the row is saved the
    .env values apply (see `assistant.config`). The key is written there and never shown again."""

    provider = models.CharField("Үйлчилгээ үзүүлэгч", max_length=20, choices=PROVIDER_CHOICES, blank=True)
    api_key = models.CharField("API түлхүүр", max_length=300, blank=True)
    model = models.CharField("Загвар", max_length=60, blank=True)
    timeout = models.PositiveSmallIntegerField(
        "Хугацааны хязгаар (секунд)",
        default=DEFAULT_TIMEOUT,
        validators=[MinValueValidator(TIMEOUT_MIN), MaxValueValidator(TIMEOUT_MAX)],
    )

    class Meta:
        verbose_name = "Туслахын тохиргоо"
        verbose_name_plural = "Туслахын тохиргоо"

    def __str__(self) -> str:
        return "Туслахын тохиргоо"
