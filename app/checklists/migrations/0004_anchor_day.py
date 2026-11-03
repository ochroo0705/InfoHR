from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("checklists", "0003_cancelled_state"),
    ]

    operations = [
        migrations.RenameField(model_name="checklist", old_name="last_day", new_name="anchor_day"),
        migrations.AlterField(
            model_name="checklist",
            name="anchor_day",
            field=models.DateField(verbose_name="Хугацааны эхлэл (ажилд орсон / сүүлийн ажлын өдөр)"),
        ),
        migrations.AlterField(
            model_name="checklisttemplatetask",
            name="due_offset_days",
            field=models.SmallIntegerField(
                default=0,
                help_text="Хугацааны эхлэлээс (ажилд орсон / сүүлийн ажлын өдөр); хасах утга байж болно.",
                verbose_name="Хугацаа (өдөр)",
            ),
        ),
    ]
