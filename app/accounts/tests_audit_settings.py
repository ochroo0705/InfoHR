"""System log: changes to settings, lookup lists and leave rules are recorded.

Design: docs/superpowers/specs/2026-10-29-audit-logs-design.md §5.3a.
"""

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.urls import reverse
from employees.models import CompanySettings, DepartmentExt, OrderTemplate, OrderType, StaffImportSettings
from employees.services import macs_writes
from employees.staff_import import matching
from employees.staff_import.fields import BY_KEY
from leave.models import AnnualLeaveRule, LeaveSettings, LeaveTypeExt
from leave.services import writes as leave_writes
from lists.models import DEATH, MeaningfulEntry
from lists.registry import LISTS, QUICK
from macs.models import LeaveTypeRow, LegalHoliday

from accounts import audit_context, audit_models
from accounts.audit_registry import audited_models
from accounts.models import SystemLogEntry, User
from accounts.roles import ADMIN

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    audit_context.clear_context()
    yield
    audit_context.clear_context()


@pytest.fixture
def actor() -> User:
    return User.objects.create_user("audit_settings_actor", password="x-long-pass-123")  # noqa: S106


@pytest.fixture
def private_files(settings: Any, tmp_path: Path) -> None:
    settings.ORDER_FILES_ROOT = tmp_path


def _entries(action: str) -> list[SystemLogEntry]:
    return list(SystemLogEntry.objects.filter(action=action).order_by("id"))


def _boom(*args: object, **kwargs: object) -> None:
    raise RuntimeError("log is down")


def test_audited_models_cover_lists_and_settings() -> None:
    models = audited_models()

    for spec in QUICK.values():
        assert spec.model in models
    for model in (CompanySettings, OrderTemplate, LeaveSettings, LegalHoliday, MeaningfulEntry, LeaveTypeRow):
        assert model in models
    for ext_model in (DepartmentExt, LeaveTypeExt):
        assert ext_model in models
    assert len(models) == len(set(models))


def test_adding_list_entry_records_setting_added(actor: User) -> None:
    audit_context.set_context(actor, "10.0.0.7")

    LISTS["bank"].model.objects.create(name="Голомт банк")

    [entry] = _entries("setting_added")
    assert entry.category == "settings"
    assert entry.target_label == "Голомт банк"
    assert entry.target_type == "Банк"
    assert entry.actor == actor
    assert entry.actor_name == actor.username
    assert entry.ip == "10.0.0.7"


def test_order_switch_change_records_one_line(actor: User) -> None:
    audit_context.set_context(actor, None)
    row = CompanySettings.get()
    row.order_hired = False
    row.save()
    row = CompanySettings.objects.get(pk=1)
    row.order_hired = True
    row.save()

    changed = _entries("setting_changed")
    assert len(changed) == 2
    assert changed[-1].category == "settings"
    assert changed[-1].changes == [{"field": "Ажилд орсон", "old": "Үгүй", "new": "Тийм"}]


def test_save_without_real_change_records_nothing(actor: User) -> None:
    audit_context.set_context(actor, None)
    CompanySettings.get()
    before = SystemLogEntry.objects.count()

    row = CompanySettings.objects.get(pk=1)
    row.order_hired = row.order_hired  # same value
    row.save()  # auto_now bookkeeping fields change on every save, and must not count

    assert SystemLogEntry.objects.count() == before


def test_deleting_list_entry_records_setting_deleted(actor: User) -> None:
    """The Жагсаалтууд delete path: a queryset delete through macs_writes.delete_list_entry."""
    audit_context.set_context(actor, None)
    entry = LISTS["bank"].model.objects.create(name="Хасагдах банк")

    macs_writes.delete_list_entry(entry)

    [deleted] = _entries("setting_deleted")
    assert deleted.target_label == "Хасагдах банк"
    assert deleted.category == "settings"


def test_order_template_upload_records_field_name_and_no_file_bytes(actor: User, private_files: None) -> None:
    audit_context.set_context(actor, None)
    row, _ = OrderTemplate.objects.get_or_create(order_type=OrderType.FIRED.value)
    row.file = SimpleUploadedFile("mine.docx", b"SECRET-FILE-BYTES")
    row.save()

    last = _entries("setting_changed")[-1]
    assert last.changes == [{"field": "Загварын файл (.docx)", "old": "", "new": "(файл)"}]
    assert "SECRET-FILE-BYTES" not in json.dumps(last.changes, ensure_ascii=False)
    assert "SECRET-FILE-BYTES" not in last.message


def test_failure_rolls_back_setting_change(actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    audit_context.set_context(actor, None)
    row = CompanySettings.get()
    row.order_hired = False
    row.save()

    monkeypatch.setattr(SystemLogEntry.objects, "create", _boom)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            row = CompanySettings.objects.get(pk=1)
            row.order_hired = True
            row.save()
    monkeypatch.undo()

    assert CompanySettings.objects.get(pk=1).order_hired is False


# --- Fix round 1 -----------------------------------------------------------------------------------------------


def test_list_entry_save_does_not_persist_when_log_fails(actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    """post_save runs after the save's own atomic block, so the helper must be atomic itself.

    pytest-django wraps the test in a transaction, but a write that is not atomic still shows up inside it, so the
    row would be found by the query below. transaction=True would give a truly outer-less test, but flushing the
    database breaks test_view_salary_migration_carries_over_existing_grants (serialized rollback), so it is not used.
    """
    audit_context.set_context(actor, None)
    model = LISTS["bank"].model
    monkeypatch.setattr(audit_models, "record", _boom)

    with pytest.raises(RuntimeError):
        macs_writes.save_list_entry(model, {"name": "Не хадгалагдах банк"})

    assert not model.objects.filter(name="Не хадгалагдах банк").exists()


def test_list_entry_edit_does_not_persist_when_log_fails(actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    audit_context.set_context(actor, None)
    entry = macs_writes.save_list_entry(LISTS["bank"].model, {"name": "Анхны нэр"})
    monkeypatch.setattr(audit_models, "record", _boom)

    with pytest.raises(RuntimeError):
        macs_writes.save_list_entry(LISTS["bank"].model, {"name": "Шинэ нэр"}, entry=entry)

    entry.refresh_from_db()
    assert entry.name == "Анхны нэр"


def test_leave_settings_switch_does_not_persist_when_log_fails(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    user = User.objects.create_user("leave_settings_admin", password="x-long-pass-123")  # noqa: S106
    group, _ = Group.objects.get_or_create(name=ADMIN)  # a flushed test database has no role groups
    group.permissions.add(Permission.objects.get(codename="manage_leave_settings", content_type__app_label="leave"))
    user.groups.add(group)
    client.force_login(user)
    LeaveSettings.get()
    monkeypatch.setattr(audit_models, "record", _boom)

    with pytest.raises(RuntimeError):
        client.post(reverse("leave:settings"), {"auto_annual_grant": "on"})

    assert LeaveSettings.get().auto_annual_grant is False


def test_no_actor_write_records_nothing() -> None:
    """Management commands and seeds have no request user: they write rows but no log lines."""
    LISTS["bank"].model.objects.create(name="Актор байхгүй банк")

    assert not SystemLogEntry.objects.filter(target_label="Актор байхгүй банк").exists()


def test_singleton_default_rows_create_without_a_log_line(actor: User) -> None:
    audit_context.set_context(actor, None)
    LeaveSettings.get()
    StaffImportSettings.get()
    OrderTemplate.objects.get_or_create(order_type=OrderType.FIRED.value)

    assert not _entries("setting_added")


def test_company_settings_creation_is_logged(actor: User) -> None:
    """Unlike the other singletons, an admin adds this row by choice, so its creation is a setting change."""
    audit_context.set_context(actor, None)

    CompanySettings.get()

    [added] = _entries("setting_added")
    assert added.target_type == "Байгууллагын тохиргоо"
    assert added.target_label == "Байгууллагын тохиргоо"


def test_bookkeeping_field_alone_is_not_a_change(actor: User) -> None:
    audit_context.set_context(actor, None)
    row, _ = OrderTemplate.objects.get_or_create(order_type=OrderType.PENSION.value)
    before = SystemLogEntry.objects.count()

    row.updated_by = actor
    row.save()

    assert SystemLogEntry.objects.count() == before


def test_foreign_key_and_choice_changes_show_names(actor: User) -> None:
    audit_context.set_context(actor, None)
    district_model = LISTS["district"].model
    city_a = LISTS["city"].model.objects.create(name="Улаанбаатар")
    city_b = LISTS["city"].model.objects.create(name="Дархан")
    district = district_model.objects.create(name="Баянзүрх", city=city_a)
    district.city = city_b
    district.save()

    [changed] = _entries("setting_changed")
    city_field = str(district_model._meta.get_field("city").verbose_name)
    assert changed.changes == [{"field": city_field, "old": "Улаанбаатар", "new": "Дархан"}]

    StaffImportSettings.get()
    settings_row = StaffImportSettings.objects.get(pk=1)
    settings_row.date_format = "dmy"
    settings_row.save()
    last = _entries("setting_changed")[-1]
    assert last.changes == [{"field": "Огнооны хэлбэр", "old": "ОО-СС-ӨӨ (2026-01-31)", "new": "ӨӨ.СС.ОО (31.01.2026)"}]


def test_queryset_delete_of_department_logs_once_under_its_name(actor: User) -> None:
    audit_context.set_context(actor, None)
    department = macs_writes.save_department("Устах хэлтэс")

    macs_writes.delete_department(department)

    deleted = _entries("setting_deleted")
    assert [entry.target_label for entry in deleted] == ["Устах хэлтэс"]


def test_department_creation_logs_once_and_flag_changes_log_under_name(actor: User) -> None:
    audit_context.set_context(actor, None)
    department = macs_writes.save_department("Тест хэлтэс")
    [added] = _entries("setting_added")
    assert added.target_label == "Тест хэлтэс"  # the HR flag row adds no second line

    ext = DepartmentExt.objects.get(department=department)
    ext.active = False
    ext.save()
    macs_writes.reactivate_department(department)

    flags = _entries("setting_changed")
    assert [entry.target_label for entry in flags] == ["Тест хэлтэс", "Тест хэлтэс"]
    assert flags[-1].changes == [{"field": "Идэвхтэй", "old": "Үгүй", "new": "Тийм"}]


def test_meaning_pick_is_logged_with_its_meaning(actor: User) -> None:
    audit_context.set_context(actor, None)
    reason = LISTS["fired_reason"].model.objects.create(name="Тест шалтгаан")

    MeaningfulEntry.objects.update_or_create(key=DEATH, defaults={"value": reason.pk})

    [added] = [e for e in _entries("setting_added") if e.target_type == "Утгатай жагсаалтын сонголт"]
    assert added.target_label == "Нас барсан: Тест шалтгаан"  # the meaning and the chosen entry, not the code key


def test_leave_type_create_and_rename_are_logged(actor: User) -> None:
    audit_context.set_context(actor, None)
    values = {"is_paid": False, "uses_annual_balance": False, "is_active": True, "order": 1}
    row = leave_writes.save_leave_type("Тест чөлөө", values)
    [added] = _entries("setting_added")
    assert added.target_label == "Тест чөлөө"  # the leave-type extension row adds no second line

    leave_writes.save_leave_type("Шинэ нэр", {**values, "is_paid": True}, row=row)

    changed = _entries("setting_changed")
    assert {"field": "Нэр", "old": "Тест чөлөө", "new": "Шинэ нэр"} in [c for e in changed for c in e.changes]
    paid = [e for e in changed if any(c["field"] == "Цалинтай" for c in e.changes)]
    assert [e.target_label for e in paid] == ["Шинэ нэр"]


def test_meaning_change_shows_entry_names_and_delete_names_the_entry(actor: User) -> None:
    audit_context.set_context(actor, None)
    first = LISTS["fired_reason"].model.objects.create(name="Өмнөх шалтгаан")
    second = LISTS["fired_reason"].model.objects.create(name="Шинэ шалтгаан")
    MeaningfulEntry.objects.update_or_create(key=DEATH, defaults={"value": first.pk})

    MeaningfulEntry.objects.update_or_create(key=DEATH, defaults={"value": second.pk})

    [changed] = _entries("setting_changed")
    assert changed.changes == [{"field": "Нас барсан", "old": "Өмнөх шалтгаан", "new": "Шинэ шалтгаан"}]
    assert changed.target_label == "Нас барсан: Шинэ шалтгаан"

    MeaningfulEntry.objects.get(key=DEATH).delete()

    [deleted] = _entries("setting_deleted")
    assert deleted.target_label == "Нас барсан: Шинэ шалтгаан"


def test_staff_import_mapping_not_saved_when_log_fails(actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    """matching.remember saves the audited StaffImportSettings row; a failed log line must roll the mapping back."""
    audit_context.set_context(actor, None)
    row = StaffImportSettings.get()
    key = next(iter(BY_KEY))
    monkeypatch.setattr(audit_models, "record", _boom)

    with pytest.raises(RuntimeError):
        matching.remember(row, ["Нэр"], {"0": key}, {}, "dmy")

    stored = StaffImportSettings.objects.get(pk=1)
    assert stored.mapping == {}
    assert stored.date_format == "iso"


def test_staff_import_defaults_change_is_masked(actor: User) -> None:
    """defaults can hold salary-gated values; the system log is readable without the salary right, so none is logged."""
    audit_context.set_context(actor, None)
    row = StaffImportSettings.get()
    secret_key, secret_value = "base_salary", "SECRET-SALARY-4500000"
    row.defaults = {secret_key: secret_value}
    row.save()

    [changed] = _entries("setting_changed")
    field = str(StaffImportSettings._meta.get_field("defaults").verbose_name)
    assert changed.changes == [{"field": field, "old": "", "new": "(өөрчлөгдсөн)"}]
    stored_text = " ".join(
        [changed.message, changed.target_label, changed.target_type, json.dumps(changed.changes, ensure_ascii=False)]
    )
    assert secret_value not in stored_text
    assert secret_key not in stored_text


def test_staff_import_mapping_change_is_masked_and_unchanged_save_logs_nothing(actor: User) -> None:
    audit_context.set_context(actor, None)
    row = StaffImportSettings.get()
    row.mapping = {"3": "salary_key"}
    row.save()
    count = SystemLogEntry.objects.count()

    row = StaffImportSettings.objects.get(pk=1)
    row.save()  # nothing changed

    assert SystemLogEntry.objects.count() == count
    [changed] = _entries("setting_changed")
    assert [c["new"] for c in changed.changes] == ["(өөрчлөгдсөн)"]
    assert "salary_key" not in json.dumps(changed.changes, ensure_ascii=False)


def test_any_json_setting_is_masked_by_default(actor: User) -> None:
    audit_context.set_context(actor, None)
    rule = AnnualLeaveRule.objects.create(
        effective_from=date(2026, 1, 1),
        base_days=15,
        base_days_minor_or_disabled=21,
        brackets=[{"from_month": 61, "extra_days": 3}],
    )
    rule.brackets = [{"from_month": 73, "extra_days": 5}]
    rule.save()

    [changed] = _entries("setting_changed")
    assert [c["new"] for c in changed.changes] == ["(өөрчлөгдсөн)"]
    assert "extra_days" not in json.dumps(changed.changes, ensure_ascii=False)
