from django.db import models


class McpToken(models.Model):
    """A per-user access token for an MCP client. Only the SHA-256 hash of the token is stored."""

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="mcp_tokens",
        verbose_name="Хэрэглэгч",
    )
    name = models.CharField(
        max_length=100,
        verbose_name="Нэр",
        help_text="Аль туслах эсвэл системд энэ токеныг ашиглахыг заана. Жишээ нь: Claude Desktop.",
    )
    # first characters of the raw token, to recognise it in a list
    prefix = models.CharField(max_length=12, verbose_name="Эхний тэмдэгтүүд")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Үүсгэсэн")
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name="Сүүлд ашигласан")
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="Цуцалсан")

    class Meta:
        verbose_name = "MCP токен"
        verbose_name_plural = "MCP токенууд"

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"


class McpCall(models.Model):
    """One MCP tool call: who made it, what was asked, and whether it was answered or refused."""

    token = models.ForeignKey(
        McpToken,
        on_delete=models.CASCADE,
        related_name="calls",
        verbose_name="Токен",
    )
    tool = models.CharField(max_length=40, verbose_name="Хэрэгсэл")
    sql = models.TextField(blank=True, verbose_name="SQL")
    ok = models.BooleanField(verbose_name="Амжилттай")
    reason = models.CharField(max_length=300, blank=True, verbose_name="Шалтгаан")
    row_count = models.IntegerField(null=True, verbose_name="Мөрийн тоо")
    duration_ms = models.IntegerField(verbose_name="Хугацаа (мс)")
    at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Огноо")

    class Meta:
        verbose_name = "MCP дуудлага"
        verbose_name_plural = "MCP дуудлагын түүх"

    def __str__(self) -> str:
        return f"{self.tool} {'ok' if self.ok else 'refused'} ({self.at:%Y-%m-%d %H:%M})"
