import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Employee.bank -> production column bank_ident (unmanaged table: state only, no SQL)."""

    dependencies = [
        ("macs", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="bank",
            field=models.ForeignKey(
                blank=True,
                db_column="bank_ident",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="macs.bank",
                verbose_name="Банк",
            ),
        ),
    ]
