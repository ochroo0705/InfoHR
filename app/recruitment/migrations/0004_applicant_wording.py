import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0003_vacancy_desired_start"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="candidate",
            options={
                "default_permissions": (),
                "ordering": ["-created_at", "-pk"],
                "verbose_name": "Ажил хүсэгч",
                "verbose_name_plural": "Ажил хүсэгчид",
            },
        ),
        migrations.AlterModelOptions(
            name="candidateevent",
            options={
                "default_permissions": (),
                "ordering": ["at", "pk"],
                "verbose_name": "Ажил хүсэгчийн түүх",
                "verbose_name_plural": "Ажил хүсэгчийн түүх",
            },
        ),
        migrations.AlterModelOptions(
            name="candidatefile",
            options={
                "default_permissions": (),
                "ordering": ["uploaded_at", "pk"],
                "verbose_name": "Ажил хүсэгчийн файл",
                "verbose_name_plural": "Ажил хүсэгчийн файлууд",
            },
        ),
        migrations.AlterField(
            model_name="recruitmentsettings",
            name="retention_months",
            field=models.PositiveSmallIntegerField(
                default=12,
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(120)],
                verbose_name="Татгалзсан ажил хүсэгчийг хадгалах хугацаа (сар)",
            ),
        ),
    ]
