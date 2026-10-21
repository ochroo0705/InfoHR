from django.db import models

MONGOLIA = "country.mongolia"
DEATH = "fired_reason.death"


class MeaningfulEntry(models.Model):
    """Which list entry carries a meaning the code relies on (spec §5), chosen by an HR admin."""

    key = models.CharField(max_length=50, unique=True)
    value = models.IntegerField()

    class Meta:
        permissions = [("manage_lists", "Жагсаалт засах")]

    def __str__(self) -> str:
        return f"{self.key} = {self.value}"

    @classmethod
    def get(cls, key: str) -> int | None:
        return cls.objects.filter(key=key).values_list("value", flat=True).first()
