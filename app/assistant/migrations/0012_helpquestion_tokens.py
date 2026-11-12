from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0011_deepseek_provider"),
    ]

    operations = [
        migrations.AddField(
            model_name="helpquestion",
            name="tokens_in",
            field=models.PositiveIntegerField(default=0, verbose_name="Оролтын токен"),
        ),
        migrations.AddField(
            model_name="helpquestion",
            name="tokens_out",
            field=models.PositiveIntegerField(default=0, verbose_name="Гаралтын токен"),
        ),
    ]
