from django.db import models

SIZE_BAND_CHOICES: list[tuple[str, str]] = [
    ("1-10", "1-10"),
    ("11-50", "11-50"),
    ("51-200", "51-200"),
    ("200+", "200+"),
]

MAIL_STATUS_CHOICES: list[tuple[str, str]] = [
    ("pending", "Хүлээгдэж буй"),
    ("sent", "Илгээсэн"),
    ("failed", "Алдаатай"),
    ("not_configured", "Имэйл тохируулаагүй"),
]


class DemoRequest(models.Model):
    name = models.CharField("Нэр", max_length=120)
    email = models.EmailField("Имэйл", max_length=254)
    organisation = models.CharField("Байгууллага", max_length=200)
    phone = models.CharField("Утас", max_length=40, blank=True)
    size_band = models.CharField("Ажилтны тоо", max_length=8, blank=True, choices=SIZE_BAND_CHOICES)
    note = models.TextField("Тайлбар", blank=True)
    ip = models.CharField("IP хаяг", max_length=45, blank=True)
    created_at = models.DateTimeField("Үүсгэсэн огноо", auto_now_add=True)
    mail_status = models.CharField("Имэйлийн төлөв", max_length=16, default="pending", choices=MAIL_STATUS_CHOICES)
    mail_error = models.CharField("Имэйлийн алдаа", max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Демо хүсэлт"
        verbose_name_plural = "Демо хүсэлтүүд"

    def __str__(self) -> str:
        return f"{self.organisation} — {self.name}"
