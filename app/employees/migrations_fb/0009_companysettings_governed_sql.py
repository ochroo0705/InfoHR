"""The governed SQL switch (CompanySettings.governed_sql_enabled), for the Firebird initial set."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0008_companysettings_soon_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="governed_sql_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Идэвхжүүлвэл туслах өгөгдлийн санд зөвхөн унших SQL асуулгаар хариулж чадна. Асуулга хэрэглэгчийн өөрийн эрхийн хүрээнд ажиллана.",
                verbose_name="Өгөгдлөөс шууд хариулах (SQL)",
            ),
        ),
    ]
