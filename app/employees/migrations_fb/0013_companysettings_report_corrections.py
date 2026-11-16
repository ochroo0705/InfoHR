"""The report corrections switch (CompanySettings.report_corrections), for the Firebird initial set.

The same operation as the PostgreSQL 0037_companysettings_report_corrections.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0012_ordertemplate_show_letterhead"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="report_corrections",
            field=models.BooleanField(
                default=True,
                help_text="Тайлангийн хүснэгтээс хэлтэс, албан тушаал, удирдлага, цалинг засвараар (шалтгаантай) өөрчлөх.",
                verbose_name="Тайлангаас засвар хийх",
            ),
        ),
    ]
