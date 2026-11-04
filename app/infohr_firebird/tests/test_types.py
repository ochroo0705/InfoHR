from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from django.db import connections, models
from django.test.utils import isolate_apps


def _make_model(kind: str, field: models.Field[Any, Any]) -> Any:
    """Build a throwaway model with one field named 'sample', stored in table IHR_T_<KIND>."""
    meta = type("Meta", (), {"app_label": "infohr_firebird", "db_table": f"IHR_T_{kind.upper()}"})
    attrs: dict[str, Any] = {"__module__": __name__, "Meta": meta, "sample": field}
    return type(f"Probe{kind.title()}", (models.Model,), attrs)


ZULAANBAATAR = ZoneInfo("Asia/Ulaanbaatar")

CASES: list[tuple[str, Callable[[], models.Field[Any, Any]], Any]] = [
    ("char", lambda: models.CharField(max_length=80), "Монгол Ө Ү ө ү — №12"),
    ("int", lambda: models.IntegerField(), 2_000_000_000),
    ("smallint", lambda: models.SmallIntegerField(), 30_000),
    ("bigint", lambda: models.BigIntegerField(), 2_000_000_000),
    ("decimal", lambda: models.DecimalField(max_digits=9, decimal_places=2), Decimal("1234567.89")),
    ("float", lambda: models.FloatField(), 3.14159),
    ("date", lambda: models.DateField(), date(2026, 11, 3)),
    ("datetime", lambda: models.DateTimeField(), datetime(2026, 11, 3, 14, 30, 5, tzinfo=ZULAANBAATAR)),
    ("bool", lambda: models.BooleanField(), True),
    ("text", lambda: models.TextField(), "урт текст " * 500),
    ("uuid", lambda: models.UUIDField(), UUID("12345678-1234-5678-1234-567812345678")),
    ("json", lambda: models.JSONField(), {"a": [1, 2], "b": "Ө"}),
]


@pytest.mark.parametrize(("kind", "make_field", "value"), CASES, ids=[case[0] for case in CASES])
def test_roundtrip(fb_alias: str, kind: str, make_field: Callable[[], models.Field[Any, Any]], value: Any) -> None:
    connection = connections[fb_alias]
    with isolate_apps("infohr_firebird"):
        model = _make_model(kind, make_field())
        with connection.schema_editor() as editor:
            editor.create_model(model)
        try:
            created = model.objects.using(fb_alias).create(sample=value)
            loaded = model.objects.using(fb_alias).get(pk=created.pk)
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(model)

    assert loaded.sample == value
    assert type(loaded.sample) is type(value)


@isolate_apps("infohr_firebird")
def test_big_autofield_primary_key_round_trip(fb_alias: str) -> None:
    connection = connections[fb_alias]
    model = _make_model("bigpk", models.CharField(max_length=20))
    with connection.schema_editor() as editor:
        editor.create_model(model)
    try:
        created = model.objects.using(fb_alias).create(sample="first")
        loaded = model.objects.using(fb_alias).get(pk=created.pk)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(model)

    assert type(created.pk) is int
    assert loaded.pk == created.pk
    assert loaded.sample == "first"


@isolate_apps("infohr_firebird")
def test_decimal_read_from_double_column(fb_alias: str) -> None:
    # EMPLOYEE.SALARY in the template copy is a column whose values come back as float in dialect 1.
    class Employee(models.Model):  # noqa: DJ008 - throwaway unmanaged model, no __str__ needed
        employee_id = models.AutoField(primary_key=True, db_column="EMPLOYEE_ID")
        salary = models.DecimalField(max_digits=12, decimal_places=2, db_column="SALARY")

        class Meta:
            app_label = "infohr_firebird"
            db_table = "EMPLOYEE"
            managed = False

    connection = connections[fb_alias]
    with connection.cursor() as cursor:
        cursor.execute("update employee set salary = 1234567.89 where employee_id = 1767")

    row = cast(Any, Employee).objects.using(fb_alias).get(pk=1767)

    assert row.salary == Decimal("1234567.89")
    assert type(row.salary) is Decimal


@isolate_apps("infohr_firebird")
def test_datetime_is_stored_as_local_wall_clock(fb_alias: str) -> None:
    # The alias TIME_ZONE is Asia/Ulaanbaatar (UTC+8): an aware 14:30 is stored as the naive wall-clock 14:30.
    connection = connections[fb_alias]
    model = _make_model("dtstore", models.DateTimeField())
    with connection.schema_editor() as editor:
        editor.create_model(model)
    try:
        created = model.objects.using(fb_alias).create(sample=datetime(2026, 11, 3, 14, 30, 5, tzinfo=ZULAANBAATAR))
        with connection.cursor() as cursor:
            cursor.execute("select sample from IHR_T_DTSTORE")
            rows = cursor.fetchall()
        loaded = model.objects.using(fb_alias).get(pk=created.pk)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(model)

    assert rows == [(datetime(2026, 11, 3, 14, 30, 5),)]
    assert rows[0][0].tzinfo is None
    assert loaded.sample == datetime(2026, 11, 3, 14, 30, 5, tzinfo=ZULAANBAATAR)
