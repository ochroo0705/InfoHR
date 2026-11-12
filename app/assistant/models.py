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
    SQL = "sql", "SQL хариулт"  # needs native read


class Kind(models.TextChoices):
    """What a corrected example is used for."""

    EXAMPLE = "example", "Жишээ (туслах сурна)"
    TEST = "test", "Тест (зөвхөн хэмжинэ)"


class HelpQuestion(models.Model):
    """One question typed into the help assistant. Written by the service, read in the admin."""

    asked_at = models.DateTimeField("Асуусан", auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Хэрэглэгч"
    )
    question = models.CharField("Асуулт", max_length=300)
    entry = models.CharField("Хариулсан хэсэг", max_length=40, blank=True)  # the help entry shown as the answer, if any
    also = models.CharField("Холбоотой хэсэг", max_length=40, blank=True)  # a related help entry, if any
    outcome = models.CharField("Үр дүн", max_length=10, choices=Outcome.choices)
    provider = models.CharField("Нийлүүлэгч", max_length=20, blank=True)
    model = models.CharField("Загвар", max_length=60, blank=True)
    duration_ms = models.PositiveIntegerField("Хугацаа (мс)", default=0)
    allowed = models.TextField("Зөвшөөрөгдсөн хэсгүүд", blank=True)  # asker's allowed entry keys, comma-separated
    error = models.CharField("Алдааны шалтгаан", max_length=300, blank=True)  # why a failed call failed
    tool = models.CharField("Хэрэгсэл", max_length=12, blank=True)  # the plan's tool: entry, staff_table, none
    query = models.CharField("Шүүлтүүрийн холбоос", max_length=300, blank=True)  # the table answer's filter query
    not_applied = models.CharField("Хэрэглээгүй хэсэг", max_length=300, blank=True)  # the parts not applied, joined
    # Tokens the provider reported for this question (all its calls). 0 = none reported (failed call, no call made,
    # or a provider that does not say).
    tokens_in = models.PositiveIntegerField("Оролтын токен", default=0)
    tokens_out = models.PositiveIntegerField("Гаралтын токен", default=0)
    # The governed SQL answer: the checked SQL, its row count, and whether it read salary or loan views.
    sql = models.TextField("SQL", blank=True)
    sql_rows = models.PositiveIntegerField("SQL мөрийн тоо", default=0)
    salary_flag = models.BooleanField("Цалингийн өгөгдөл", default=False)
    sql_labels = models.TextField("Баганын нэр", blank=True, default="")  # JSON {"COLUMN": "heading"} the model gave

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


class VerifiedStatus(models.TextChoices):
    """Where a proposed verified query stands."""

    PROPOSED = "proposed", "Шалгагдаж буй"  # needs native read
    APPROVED = "approved", "Зөвшөөрсөн"  # needs native read
    REJECTED = "rejected", "Татгалзсан"  # needs native read


class VerifiedQuery(models.Model):
    """An answer the asker marked as correct, proposed for review. Only an approved row may be used later. The SQL is
    the checked SQL of the source answer; `views` is computed from the checker, never taken from the client."""

    question = models.CharField("Асуулт", max_length=300)
    sql = models.TextField("SQL")
    views = models.CharField("Хүснэгтүүд", max_length=200, blank=True)  # upper-case view names, comma-separated
    status = models.CharField(
        "Төлөв", max_length=10, choices=VerifiedStatus.choices, default=VerifiedStatus.PROPOSED
    )
    source = models.ForeignKey(
        HelpQuestion, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_queries"
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField("Шалгасан", null=True, blank=True)
    note = models.CharField("Тэмдэглэл", max_length=200, blank=True)
    created_at = models.DateTimeField("Санал болгосон", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Баталгаажуулсан асуулт"
        verbose_name_plural = "Баталгаажуулсан асуултууд"

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


class WorkspaceTab(models.Model):
    """One tab of the assistant workspace: a governed-SQL table the user keeps and refines. The tab holds the checked
    SQL of each version, never rows; rows are run again every time the tab is shown."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_tabs", verbose_name="Эзэмшигч"
    )
    title = models.CharField("Гарчиг", max_length=80)
    source = models.ForeignKey(
        HelpQuestion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_tabs",
        verbose_name="Эх асуулт",
    )
    created_at = models.DateTimeField("Үүсгэсэн", auto_now_add=True)
    updated_at = models.DateTimeField("Өөрчилсөн", auto_now=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Ажлын хуудасны таб"
        verbose_name_plural = "Ажлын хуудасны табууд"

    def __str__(self) -> str:
        return self.title

    def current(self) -> "WorkspaceVersion | None":
        """The newest version of the tab, or None when it has none yet."""
        return self.versions.last()


class WorkspaceVersion(models.Model):
    """One saved state of a workspace tab: the question, its checked SQL and the tool settings used with it. Undo
    goes back to an older version."""

    tab = models.ForeignKey(WorkspaceTab, on_delete=models.CASCADE, related_name="versions", verbose_name="Таб")
    question = models.TextField("Асуулт")
    sql = models.TextField("SQL")
    settings = models.TextField("Тохиргоо", default="")  # JSON text, written by spec_to_json
    labels = models.TextField("Баганын нэр", default="", blank=True)  # JSON text {"COLUMN": "heading"}, from the model
    created_at = models.DateTimeField("Үүсгэсэн", auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Ажлын хуудасны хувилбар"
        verbose_name_plural = "Ажлын хуудасны хувилбарууд"

    def __str__(self) -> str:
        return self.question


class WorkspaceMessage(models.Model):
    """One line of the chat panel that belongs to a workspace tab."""

    class Role(models.TextChoices):
        USER = "user", "Хэрэглэгч"
        ASSISTANT = "assistant", "Туслах"

    tab = models.ForeignKey(WorkspaceTab, on_delete=models.CASCADE, related_name="messages", verbose_name="Таб")
    role = models.CharField("Үүрэг", max_length=10, choices=Role.choices)
    text = models.TextField("Текст")
    created_at = models.DateTimeField("Үүсгэсэн", auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Ажлын хуудасны мессеж"
        verbose_name_plural = "Ажлын хуудасны мессежүүд"

    def __str__(self) -> str:
        return self.text[:60]


class SavedTable(models.Model):
    """A table saved from the workspace: its checked SQL, the model's column labels and the table settings. It is
    shown again with the same tools, and its SQL runs fresh as the viewer. `visibility` says who may see it."""

    name = models.CharField("Нэр", max_length=80)
    sql = models.TextField("SQL")
    labels = models.TextField("Баганын нэр", default="", blank=True)  # JSON text {"COLUMN": "heading"}
    # `author` is declared before `settings`: inside the class body the name `settings` is the field below.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+", verbose_name="Зохиогч"
    )
    settings = models.TextField("Тохиргоо", default="", blank=True)  # JSON text, written by spec_to_json
    visibility = models.CharField(
        "Харагдах байдал",
        max_length=10,
        default="shared",
        choices=[("shared", "Хамтын"), ("private", "Хувийн")],
    )
    created_at = models.DateTimeField("Үүсгэсэн", auto_now_add=True)
    updated_at = models.DateTimeField("Өөрчилсөн", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Хадгалсан хүснэгт"
        verbose_name_plural = "Хадгалсан хүснэгтүүд"
        permissions = [("manage_saved_tables", "Хадгалсан хүснэгтийг устгах")]

    def __str__(self) -> str:
        return self.name
