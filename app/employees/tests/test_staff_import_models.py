import pytest
from accounts.models import User

from employees.models import StaffImportDraft, StaffImportSettings

pytestmark = pytest.mark.django_db


def test_staff_import_settings_is_a_single_row() -> None:
    first = StaffImportSettings.get()
    second = StaffImportSettings.get()

    assert first.pk == 1
    assert second.pk == first.pk
    assert StaffImportSettings.objects.count() == 1
    assert first.mapping == {}
    assert first.defaults == {}
    assert first.date_format == "iso"


def test_staff_import_draft_round_trips_json_and_bytes() -> None:
    user = User.objects.create_user("import_user", password="x-long-pass-123")  # noqa: S106
    draft = StaffImportDraft.objects.create(
        created_by=user,
        filename="staff.xlsx",
        data=b"x",
        mapping={"0": "last_name", "1": "first_name"},
        defaults={"nationality": "Монгол"},
    )

    reloaded = StaffImportDraft.objects.get(pk=draft.pk)

    assert reloaded.id == draft.id
    assert reloaded.created_by == user
    assert bytes(reloaded.data) == b"x"
    assert reloaded.mapping == {"0": "last_name", "1": "first_name"}
    assert reloaded.defaults == {"nationality": "Монгол"}
    assert reloaded.state == "uploaded"
    assert reloaded.header_rows == 1
    assert reloaded.created_count == 0
    assert reloaded.duplicate_count == 0
    assert reloaded.rejected_count == 0
    assert reloaded.rejected_file is None
    assert reloaded.finished_at is None
