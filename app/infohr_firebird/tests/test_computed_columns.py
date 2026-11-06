"""Computed (COMPUTED BY) columns of the MACS clone are read-only in HR (plan 3, Task 3).

Firebird refuses any write to a computed column ("attempted update of read-only column"). Django writes every concrete
field on insert and update, so an unmanaged model that maps a computed column must mark that field with
``generated = True`` on Firebird: Django then skips it on insert and update and the database computes it.
``macs.fields.ServerComputedCharField`` does this. On PostgreSQL the flag is False and nothing changes.
"""

from infohr_firebird.tests.test_settings_seam import result_of, run_django

SCAN_CODE = """
import json
import django
django.setup()
from django.apps import apps
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT TRIM(rf.RDB$RELATION_NAME), TRIM(rf.RDB$FIELD_NAME) "
        "FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME "
        "WHERE f.RDB$COMPUTED_BLR IS NOT NULL"
    )
    computed = sorted([row[0].upper(), row[1].upper()] for row in cursor.fetchall())
computed_pairs = {(table, column) for table, column in computed}
mapped = []
for model in apps.get_models():
    meta = model._meta
    if meta.managed:
        continue
    table = meta.db_table.upper()
    for field in meta.concrete_fields:
        column = (field.column or "").upper()
        if (table, column) in computed_pairs:
            mapped.append({
                "model": meta.label,
                "table": table,
                "column": column,
                "field": field.name,
                "generated": field.generated is True,
            })
mapped_pairs = {(row["table"], row["column"]) for row in mapped}
print("RESULT " + json.dumps({
    "computed": computed,
    "mapped": sorted(mapped, key=lambda row: (row["table"], row["column"])),
    "unmapped": sorted([list(pair) for pair in computed_pairs - mapped_pairs]),
}))
"""

SAVE_CODE = """
import json
import django
django.setup()
from macs.models import Employee
employee = Employee(
    family_name="Т", given_name="Б", gender="M", hr_flag="no", sector_years=0, emptype=1,
    status="active", contract_flag="no",
)
employee.save(force_insert=True)
employee.given_name = "В"
employee.save(update_fields=["given_name"])
fresh = Employee.objects.get(pk=employee.pk)
print("RESULT " + json.dumps({
    "pk": employee.pk,
    "given_name": fresh.given_name,
    "fullname": fresh.fullname,
}))
"""

# The computed columns of the MACS tables that the unmanaged models map. The probe scan (2026-11-06) found
# EMPLOYEE.FULLNAME and EMPLOYEE_HISTORY.FULLNAME. The other computed columns in the clone belong to tables no HR
# model maps (ACCOUNT, FDB_BUDGET, ...); they are printed, not asserted.
EXPECTED_MAPPED = {("EMPLOYEE", "FULLNAME"), ("EMPLOYEE_HISTORY", "FULLNAME")}


def test_every_computed_column_is_read_only(migrated_clone: str) -> None:
    data = result_of(run_django(SCAN_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    print(f"\ncomputed columns in the clone: {data['computed']}")
    print(f"computed columns mapped by unmanaged models: {data['mapped']}")
    print(f"computed columns with no unmanaged model: {data['unmapped']}")
    mapped_pairs = {(row["table"], row["column"]) for row in data["mapped"]}
    assert mapped_pairs == EXPECTED_MAPPED
    for row in data["mapped"]:
        assert row["generated"] is True, f"{row['model']}.{row['field']} must be read-only on Firebird"


def test_employee_save_and_update_with_computed_fullname(migrated_clone: str) -> None:
    data = result_of(run_django(SAVE_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert data["pk"] is not None
    assert data["given_name"] == "В"
    assert data["fullname"]
