import pytest
from django.apps import apps
from django.db import connection


@pytest.mark.django_db
def test_every_macs_field_is_a_real_production_column() -> None:
    with connection.cursor() as c:
        c.execute(
            "select table_name, column_name, character_maximum_length "
            "from information_schema.columns where table_schema='public'"
        )
        columns = {(t, col): length for t, col, length in c.fetchall()}
    for model in apps.get_app_config("macs").get_models():
        assert model._meta.managed is False, model
        for field in model._meta.concrete_fields:
            key = (model._meta.db_table, field.column)
            assert key in columns, f"{model.__name__}.{field.name} -> {key}"
            max_length = getattr(field, "max_length", None)
            if max_length and columns[key]:
                assert max_length <= columns[key], f"{model.__name__}.{field.name} longer than production"


@pytest.mark.django_db
def test_timestamp_date_field_reads_a_date() -> None:
    from datetime import date

    from macs.models import Employee

    e = Employee.objects.create(given_name="Т", family_name="Б", birth_date=date(1990, 5, 1))
    e.refresh_from_db()
    assert e.birth_date == date(1990, 5, 1)
