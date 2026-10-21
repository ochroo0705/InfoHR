"""Run daily: copies the job and salary valid today onto every production employee row, so
changes dated in the future reach production on their day (plan Review Focus 1).
Also records the day, so the request-time safety net (employees.daily_sync) skips today."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from employees.daily_sync import run_daily_sync


class Command(BaseCommand):
    help = "Copy today's job and salary onto production employee rows."

    def handle(self, *args: object, **options: object) -> None:
        changed = run_daily_sync(timezone.localdate(), force=True) or 0
        self.stdout.write(f"{changed} ажилтны мэдээлэл шинэчлэгдлээ")
