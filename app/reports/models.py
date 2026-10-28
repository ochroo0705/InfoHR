from django.conf import settings
from django.db import models


class SavedView(models.Model):
    """A report setup (filters, columns, sort) that a user saved under a name, so it can be opened again."""

    report = models.CharField(max_length=40)
    name = models.CharField("Нэр", max_length=60)
    query = models.CharField(max_length=2000, blank=True)  # the report's query string, as shown in the address
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["report", "name"], name="reports_savedview_unique_name")]
        ordering = ["name"]
        verbose_name = "Хадгалсан харагдац"
        permissions = [
            ("view_reports", "Тайлан харах"),
            ("manage_saved_views", "Хадгалсан харагдацыг засах, устгах"),
        ]

    def __str__(self) -> str:
        return self.name
