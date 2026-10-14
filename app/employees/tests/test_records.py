import pytest
from accounts.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from employees.models import ActivityEntry, Employee
from employees.services import records

pytestmark = pytest.mark.django_db


def test_clearing_empty_photo_logs_nothing(hired: Employee, actor: User) -> None:
    before = ActivityEntry.objects.count()
    assert records.update_employee(hired, {"photo": False}, actor) == []
    assert records.update_employee(hired, {"photo": None}, actor) == []
    assert ActivityEntry.objects.count() == before


def test_new_photo_is_logged_once(hired: Employee, actor: User, settings: object, tmp_path: object) -> None:
    settings.MEDIA_ROOT = str(tmp_path)  # type: ignore[attr-defined]
    upload = SimpleUploadedFile("face.jpg", b"fake-bytes", content_type="image/jpeg")
    changes = records.update_employee(hired, {"photo": upload}, actor)
    assert len(changes) == 1 and changes[0]["old"] == "" and changes[0]["new"]
    assert ActivityEntry.objects.filter(employee=hired, kind="changed").count() == 1
