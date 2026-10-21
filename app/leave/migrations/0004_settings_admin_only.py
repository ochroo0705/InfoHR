"""Leave settings (auto-grant switch, leave types, holidays) become Admin only (user decision 2026-10-19)."""

from typing import Any

from django.db import migrations


def forwards(apps: Any, schema_editor: Any) -> None:
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perm = Permission.objects.filter(content_type__app_label="leave", codename="manage_leave_settings").first()
    hr = Group.objects.filter(name="HR").first()
    if perm and hr:
        hr.permissions.remove(perm)


def backwards(apps: Any, schema_editor: Any) -> None:
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perm = Permission.objects.filter(content_type__app_label="leave", codename="manage_leave_settings").first()
    hr = Group.objects.filter(name="HR").first()
    if perm and hr:
        hr.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [("leave", "0003_production_tables")]

    operations = [migrations.RunPython(forwards, backwards)]
