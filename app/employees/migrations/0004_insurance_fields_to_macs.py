from django.db import migrations


class Migration(migrations.Migration):
    """The salary/insurance fields now live on the production employee row (macs 0003); no data kept."""

    dependencies = [
        ("employees", "0003_bank_ident_on_employee"),
    ]

    operations = [
        migrations.RemoveField(model_name="salaryinsurance", name="social_insurance_no"),
        migrations.RemoveField(model_name="salaryinsurance", name="health_insurance_no"),
        migrations.RemoveField(model_name="salaryinsurance", name="insured_category"),
        migrations.RemoveField(model_name="salaryinsurance", name="taxpayer_no"),
        migrations.RemoveField(model_name="salaryinsurance", name="has_disability"),
    ]
