"""ExactMoneyField on Firebird: no wide-decimal warning, and exact values on a DOUBLE PRECISION column.

The settings-seam helpers run Django in a subprocess, so no test here changes this process's settings.
The round-trip test uses the fb_alias fixture (a clone of the Firebird template, never the template).
"""

from decimal import Decimal
from typing import Any

from django.db import connections, models
from django.test.utils import isolate_apps
from employees.exact_money import ExactMoneyField

from infohr_firebird.tests.test_settings_seam import FIREBIRD_PATH, result_of, run_django

CHECK_CODE = """
import json
import django
django.setup()
from django.core.checks import run_checks
issues = run_checks()
print("RESULT " + json.dumps({
    "w001": [i.msg for i in issues if i.id == "infohr_firebird.W001"],
}))
"""

TABLE = "IHR_T_EXACT_MONEY"
VALUES = [Decimal("1234567.89"), Decimal("99999999999.99")]


def test_check_does_not_warn_for_exact_money() -> None:
    data = result_of(run_django(CHECK_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH))
    assert not any(msg.startswith("employees.SalaryRecord.base_salary ") for msg in data["w001"]), data["w001"]


@isolate_apps("infohr_firebird")
def test_round_trip_on_double_column(fb_alias: str) -> None:
    connection = connections[fb_alias]
    meta = type("Meta", (), {"app_label": "infohr_firebird", "db_table": TABLE})
    attrs: dict[str, Any] = {"__module__": __name__, "Meta": meta, "sample": ExactMoneyField()}
    model = type("ProbeExactMoney", (models.Model,), attrs)
    field = model._meta.get_field("sample")
    assert field.db_type(connection) == "DOUBLE PRECISION"

    qn = connection.ops.quote_name  # dialect 1: identifiers are never double-quoted
    table, column = qn(TABLE), qn("sample")
    with connection.schema_editor() as editor:
        editor.create_model(model)
    try:
        with connection.cursor() as cursor:
            for value in VALUES:
                cursor.execute(
                    f"INSERT INTO {table} ({column}) VALUES (%s)",  # noqa: S608 (constant names, quoted by the backend)
                    [field.get_db_prep_value(value, connection)],
                )
            cursor.execute(f"SELECT {column} FROM {table} ORDER BY {column}")  # noqa: S608 (constant names)
            raw = [row[0] for row in cursor.fetchall()]
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(model)

    assert all(isinstance(value, float) for value in raw), raw  # the column really is a double
    assert [field.from_db_value(value, None, connection) for value in raw] == VALUES
