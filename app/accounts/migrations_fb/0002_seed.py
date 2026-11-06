from typing import Any

from config.seed_firebird import seed_accounts
from django.db import migrations


def seed(apps: Any, schema_editor: Any) -> None:
    seed_accounts(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
