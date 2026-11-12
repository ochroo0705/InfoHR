from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0013_helpquestion_mongolian_labels"),
    ]

    operations = [
        migrations.AlterField(
            model_name="helpquestion",
            name="outcome",
            field=models.CharField(choices=[('answered', 'Хариулсан'), ('none', 'Олдсонгүй'), ('error', 'Алдаа'), ('limited', 'Хязгаарлагдсан'), ('table', 'Хүснэгт'), ('action', 'Үйлдэл'), ('sql', 'SQL хариулт')], max_length=10, verbose_name='Үр дүн'),
        ),
        migrations.AddField(
            model_name="helpquestion",
            name="sql",
            field=models.TextField(blank=True, verbose_name="SQL"),
        ),
        migrations.AddField(
            model_name="helpquestion",
            name="sql_rows",
            field=models.PositiveIntegerField(default=0, verbose_name="SQL мөрийн тоо"),
        ),
        migrations.AddField(
            model_name="helpquestion",
            name="salary_flag",
            field=models.BooleanField(default=False, verbose_name="Цалингийн өгөгдөл"),
        ),
    ]
