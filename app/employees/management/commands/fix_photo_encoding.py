"""Converts emp_photo rows that hold base64 text (written by older HR versions) to raw image bytes.

Safe to run again: rows that are already raw bytes, and rows that are not an image, are left alone.
"""

from django.core.management.base import BaseCommand
from macs.models import EmployeePhoto

from employees.images import photo_bytes
from employees.services import macs_writes


class Command(BaseCommand):
    help = "Convert base64-encoded emp_photo rows to raw JPEG/PNG bytes."

    def handle(self, *args: object, **options: object) -> None:
        changed = 0
        for photo in EmployeePhoto.objects.all():
            raw = bytes(photo.data) if photo.data is not None else b""
            image = photo_bytes(raw)
            if image is None or image == raw:
                continue  # not an image, or already raw bytes
            macs_writes.replace_photo_bytes(photo.pk, image)
            changed += 1
        self.stdout.write(f"{changed} зургийн мөр base64-ээс шилжлээ")
